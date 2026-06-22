"""
Supabase storage backend for the alpha bot.
Drop-in replacement for the SQLite Storage class - same method signatures.

Requires SUPABASE_URL and SUPABASE_ANON_KEY in the environment or passed to the
constructor. Tables and RPC functions are created via supabase_schema.sql.
"""
from __future__ import annotations

import json
import os
import logging
from datetime import datetime, timezone
from typing import Optional, Any
from contextlib import contextmanager

import requests
from requests import RequestException
import time

from models import Candidate, Run, Metrics

logger = logging.getLogger(__name__)


def dt_to_str(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat()


class Storage:
    """Supabase-backed storage with the same interface as the SQLite version."""

    def __init__(self, db_path: str | None = None, supabase_url: str | None = None, supabase_key: str | None = None, owner: str | None = None):
        """
        db_path is ignored (kept for compatibility with config.DB_PATH).
        supabase_url / supabase_key fall back to the SUPABASE_URL / SUPABASE_ANON_KEY
        env vars. owner tags every insert (e.g. BRAIN_USERNAME).
        """
        self.url = (supabase_url or os.environ.get("SUPABASE_URL", "")).rstrip("/")
        self.key = supabase_key or os.environ.get("SUPABASE_ANON_KEY", "")
        self.owner = owner or os.environ.get("BRAIN_USERNAME", "unknown")
        if not self.url or not self.key:
            raise ValueError("SUPABASE_URL and SUPABASE_ANON_KEY must be set")
        self.base = f"{self.url}/rest/v1"
        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    # http helpers

    def _request_with_retry(self, method: str, url: str, *, retries: int = 3, **kwargs):
        """
        Small Supabase retry wrapper. The public helpers still return []/None for
        compatibility, but transient 429/5xx/network errors are retried and logged
        distinctly so coordination bugs don't masquerade as empty tables.
        """
        last_exc = None
        last_response = None
        for attempt in range(retries):
            try:
                r = requests.request(method, url, timeout=30, **kwargs)
                last_response = r
                if r.status_code not in (429, 500, 502, 503, 504):
                    return r
                logger.warning(f"{method} {url} transient failure: {r.status_code} {r.text[:200]}")
            except RequestException as exc:
                last_exc = exc
                logger.warning(f"{method} {url} request error attempt {attempt + 1}/{retries}: {exc}")
            time.sleep(0.5 * (attempt + 1))
        if last_exc:
            raise last_exc
        return last_response

    def _get(self, table: str, params: dict | None = None) -> list[dict]:
        try:
            r = self._request_with_retry("GET", f"{self.base}/{table}", headers=self.headers, params=params or {})
        except RequestException as exc:
            logger.error(f"GET {table} unavailable: {exc}")
            return []
        if r.status_code not in (200, 206):
            logger.warning(f"GET {table} failed: {r.status_code} {r.text[:300]}")
            return []
        return r.json()

    def _post(self, table: str, data: dict, upsert: bool = False, on_conflict: str = "") -> dict | None:
        headers = dict(self.headers)
        url = f"{self.base}/{table}"
        if upsert:
            headers["Prefer"] = "resolution=merge-duplicates,return=representation"
            if on_conflict:
                url += f"?on_conflict={on_conflict}"
        try:
            r = self._request_with_retry("POST", url, headers=headers, json=data)
        except RequestException as exc:
            logger.error(f"POST {table} unavailable: {exc}")
            return None
        if r.status_code not in (200, 201):
            logger.warning(f"POST {table} failed: {r.status_code} {r.text[:300]}")
            return None
        result = r.json()
        return result[0] if isinstance(result, list) and result else result

    def _patch(self, table: str, match: dict, data: dict) -> dict | None:
        params = {k: f"eq.{v}" for k, v in match.items()}
        try:
            r = self._request_with_retry("PATCH", f"{self.base}/{table}", headers=self.headers, params=params, json=data)
        except RequestException as exc:
            logger.error(f"PATCH {table} unavailable: {exc}")
            return None
        if r.status_code not in (200, 204):
            logger.warning(f"PATCH {table} failed: {r.status_code} {r.text[:300]}")
            return None
        result = r.json() if r.text else None
        return result[0] if isinstance(result, list) and result else result

    def _delete(self, table: str, match: dict) -> bool:
        params = {k: f"eq.{v}" for k, v in match.items()}
        try:
            r = self._request_with_retry("DELETE", f"{self.base}/{table}", headers=self.headers, params=params)
            return r.status_code in (200, 204)
        except RequestException as exc:
            logger.error(f"DELETE {table} unavailable: {exc}")
            return False

    def _rpc(self, function: str, params: dict | None = None) -> list[dict]:
        try:
            r = self._request_with_retry(
                "POST",
                f"{self.base}/rpc/{function}",
                headers=self.headers,
                json=params or {},
            )
        except RequestException as exc:
            logger.error(f"RPC {function} unavailable: {exc}")
            return []
        if r.status_code != 200:
            logger.warning(f"RPC {function} failed: {r.status_code} {r.text[:300]}")
            return []
        return r.json()

    # compatibility shims

    @contextmanager
    def connect(self):
        """Yields self so `with storage.connect() as conn` still works."""
        yield self

    def execute(self, sql: str, params: tuple = ()):
        """Raw SQL is not supported in Supabase mode - only used by cleanup scripts."""
        logger.warning(f"Raw SQL not supported in Supabase mode: {sql[:100]}")
        return _EmptyResult()

    def init_db(self):
        """No-op - tables are created via supabase_schema.sql."""
        pass

    def parse_dt(self, value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    # candidates

    def candidate_exists(self, expression_hash: str) -> bool:
        rows = self._get("candidates", {
            "expression_hash": f"eq.{expression_hash}",
            "select": "candidate_id",
        })
        return len(rows) > 0

    def insert_candidate(self, candidate: Candidate) -> None:
        self._post("candidates", {
            "candidate_id": candidate.candidate_id,
            "expression": candidate.expression,
            "canonical_expression": candidate.canonical_expression,
            "expression_hash": candidate.expression_hash,
            "template_id": candidate.template_id,
            "family": candidate.family,
            "fields_json": candidate.fields,
            "params_json": candidate.params,
            "settings_json": candidate.settings.to_dict(),
            "created_at": dt_to_str(candidate.created_at),
            "owner": self.owner,
        })

    def get_candidate_by_id(self, candidate_id: str) -> Optional[dict]:
        rows = self._get("candidates", {
            "candidate_id": f"eq.{candidate_id}",
            "select": "*",
        })
        return rows[0] if rows else None

    def get_candidate_by_hash(self, expression_hash: str) -> Optional[dict]:
        rows = self._get("candidates", {
            "expression_hash": f"eq.{expression_hash}",
            "select": "*",
        })
        return rows[0] if rows else None

    # runs

    def insert_run(self, run: Run) -> None:
        self._post("runs", {
            "run_id": run.run_id,
            "candidate_id": run.candidate_id,
            "sim_id": run.sim_id,
            "alpha_id": run.alpha_id,
            "status": run.status,
            "submitted_at": dt_to_str(run.submitted_at),
            "completed_at": dt_to_str(run.completed_at),
            "error_message": run.error_message,
            "raw_result_json": run.raw_result,
            "owner": self.owner,
        })

    def update_run(
        self,
        run_id: str,
        status: str | None = None,
        sim_id: str | None = None,
        alpha_id: str | None = None,
        submitted_at: datetime | None = None,
        completed_at: datetime | None = None,
        error_message: str | None = None,
        raw_result: dict | None = None,
    ) -> None:
        data = {}
        if status is not None:
            data["status"] = status
        if sim_id is not None:
            data["sim_id"] = sim_id
        if alpha_id is not None:
            data["alpha_id"] = alpha_id
        if submitted_at is not None:
            data["submitted_at"] = dt_to_str(submitted_at)
        if completed_at is not None:
            data["completed_at"] = dt_to_str(completed_at)
        if error_message is not None:
            data["error_message"] = error_message
        if raw_result is not None:
            data["raw_result_json"] = raw_result
        if data:
            self._patch("runs", {"run_id": run_id}, data)

    def get_run_by_id(self, run_id: str) -> Optional[dict]:
        rows = self._get("runs", {
            "run_id": f"eq.{run_id}",
            "select": "*",
        })
        return rows[0] if rows else None

    def get_running_runs(self) -> list[dict]:
        return self._get("runs", {
            "status": "eq.running",
            "owner": f"eq.{self.owner}",
            "select": "*",
        })

    # metrics

    def insert_metrics(self, metrics: Metrics) -> None:
        self._post("metrics", {
            "run_id": metrics.run_id,
            "sharpe": metrics.sharpe,
            "fitness": metrics.fitness,
            "turnover": metrics.turnover,
            "returns": metrics.returns,
            "margin": metrics.margin,
            "drawdown": metrics.drawdown,
            "checks_passed": metrics.checks_passed,
            "submit_eligible": metrics.submit_eligible,
            "fail_reason": metrics.fail_reason,
        }, upsert=True, on_conflict="run_id")

    # submissions

    def insert_submission(
        self,
        submission_id: str,
        candidate_id: str,
        run_id: str,
        submitted_at: datetime,
        submission_status: str,
        message: str | None = None,
    ) -> None:
        self._post("submissions", {
            "submission_id": submission_id,
            "candidate_id": candidate_id,
            "run_id": run_id,
            "submitted_at": dt_to_str(submitted_at),
            "submission_status": submission_status,
            "message": message,
            "owner": self.owner,
        })

    # refinement queue

    def add_refinement_candidate(
        self,
        candidate_id: str,
        run_id: str,
        priority: float,
        reason: str,
        created_at: datetime,
        source_stage: str = "unknown",
        base_sharpe: float | None = None,
        base_fitness: float | None = None,
        base_turnover: float | None = None,
    ) -> None:
        self._post("refinement_queue", {
            "candidate_id": candidate_id,
            "run_id": run_id,
            "priority": priority,
            "reason": reason,
            "created_at": dt_to_str(created_at),
            "consumed": False,
            "source_stage": source_stage,
            "base_sharpe": base_sharpe,
            "base_fitness": base_fitness,
            "base_turnover": base_turnover,
            "owner": self.owner,
        }, upsert=True)

    def get_next_refinement_candidate(self) -> Optional[dict]:
        # try owner-scoped first, fall back to global (pre-migration)
        try:
            rows = self._get("refinement_queue", {
                "consumed": "eq.false",
                "owner": f"eq.{self.owner}",
                "select": "*",
                "order": "priority.desc",
                "limit": "1",
            })
        except Exception:
            rows = self._get("refinement_queue", {
                "consumed": "eq.false",
                "select": "*",
                "order": "priority.desc",
                "limit": "1",
            })
        if not rows:
            return None

        row = rows[0]
        cid = row["candidate_id"]

        # get the full candidate data
        cand = self.get_candidate_by_id(cid)
        if not cand:
            return None

        # merge refinement queue data with candidate data
        merged = dict(cand)
        merged["reason"] = row.get("reason", "")
        merged["source_stage"] = row.get("source_stage", "unknown")
        merged["base_sharpe"] = row.get("base_sharpe")
        merged["base_fitness"] = row.get("base_fitness")
        merged["base_turnover"] = row.get("base_turnover")
        return merged

    def mark_refinement_consumed(self, candidate_id: str) -> None:
        self._patch("refinement_queue", {"candidate_id": candidate_id}, {"consumed": True})

    # complex queries (via RPC, with local-aggregation fallbacks)

    def get_recent_family_stats(self, limit: int = 50) -> list[dict]:
        """Direct query + local aggregation to avoid RPC timeout on free Supabase."""
        # try RPC first (fastest if it works)
        try:
            result = self._rpc("get_family_stats", {"run_limit": limit, "owner_filter": self.owner})
            if result:
                print(f"[STATS] RPC get_family_stats OK ({len(result)} families, owner-filtered)")
                return result
        except Exception:
            pass
        try:
            result = self._rpc("get_family_stats", {"run_limit": limit})
            if result:
                print(f"[STATS] RPC get_family_stats OK ({len(result)} families, unfiltered)")
                return result
        except Exception:
            pass
        # fallback: query 3 tables separately and join in Python
        # (runs table doesn't have family/sharpe - those live in candidates/metrics)
        try:
            # recent candidates with family info
            candidates = self._get("candidates", {
                "select": "candidate_id,family,template_id",
                "order": "created_at.desc",
                "limit": str(limit),
            })
            if not candidates:
                print("[STATS_FALLBACK] No candidates found")
                return []
            print(f"[STATS_FALLBACK] Got {len(candidates)} candidates")
            cand_ids = [c["candidate_id"] for c in candidates]
            cand_map = {c["candidate_id"]: c for c in candidates}

            # runs for those candidates
            runs = self._get("runs", {
                "select": "run_id,candidate_id",
                "candidate_id": f"in.({','.join(cand_ids[:200])})",
                "status": "eq.completed",
                "limit": str(limit),
            })
            if not runs:
                return []
            run_ids = [r["run_id"] for r in runs]
            run_to_cand = {r["run_id"]: r["candidate_id"] for r in runs}

            # metrics for those runs
            metrics = self._get("metrics", {
                "select": "run_id,sharpe,fitness,turnover",
                "run_id": f"in.({','.join(run_ids[:200])})",
                "limit": str(limit),
            })
            if not metrics:
                return []

            # join: metrics -> runs -> candidates -> family
            from collections import defaultdict
            fam_data = defaultdict(list)
            for m in metrics:
                rid = m.get("run_id")
                cid = run_to_cand.get(rid)
                if cid and cid in cand_map:
                    fam = cand_map[cid].get("family", "unknown")
                    fam_data[fam].append(m)

            results = []
            for fam, mets in fam_data.items():
                n = len(mets)
                sharpes = [float(m.get("sharpe") or 0) for m in mets]
                fitnesses = [float(m.get("fitness") or 0) for m in mets]
                turnovers = [float(m.get("turnover") or 0) for m in mets]
                results.append({
                    "family": fam,
                    "n_runs": n,
                    "avg_sharpe": sum(sharpes) / n if n else 0,
                    "avg_fitness": sum(fitnesses) / n if n else 0,
                    "avg_turnover": sum(turnovers) / n if n else 0,
                })
            if results:
                print(f"[STATS_FALLBACK] Aggregated {len(results)} families from {len(metrics)} runs (RPC unavailable)")
            return results
        except Exception as e:
            print(f"[STATS_FALLBACK_ERROR] family stats fallback failed: {e}")
            return []

    def get_recent_template_stats(self, limit: int = 50) -> list[dict]:
        """Direct query + local aggregation to avoid RPC timeout."""
        try:
            result = self._rpc("get_template_stats", {"run_limit": limit, "owner_filter": self.owner})
            if result:
                return result
        except Exception:
            pass
        try:
            result = self._rpc("get_template_stats", {"run_limit": limit})
            if result:
                return result
        except Exception:
            pass
        # fallback: query 3 tables and join in Python
        try:
            candidates = self._get("candidates", {
                "select": "candidate_id,family,template_id",
                "order": "created_at.desc",
                "limit": str(limit),
            })
            if not candidates:
                return []
            cand_ids = [c["candidate_id"] for c in candidates]
            cand_map = {c["candidate_id"]: c for c in candidates}

            runs = self._get("runs", {
                "select": "run_id,candidate_id",
                "candidate_id": f"in.({','.join(cand_ids[:200])})",
                "status": "eq.completed",
                "limit": str(limit),
            })
            if not runs:
                return []
            run_ids = [r["run_id"] for r in runs]
            run_to_cand = {r["run_id"]: r["candidate_id"] for r in runs}

            metrics = self._get("metrics", {
                "select": "run_id,sharpe,fitness,turnover",
                "run_id": f"in.({','.join(run_ids[:200])})",
                "limit": str(limit),
            })
            if not metrics:
                return []

            from collections import defaultdict
            tmpl_data = defaultdict(list)
            for m in metrics:
                rid = m.get("run_id")
                cid = run_to_cand.get(rid)
                if cid and cid in cand_map:
                    tid = cand_map[cid].get("template_id", "unknown")
                    fam = cand_map[cid].get("family", "unknown")
                    tmpl_data[(tid, fam)].append(m)

            results = []
            for (tid, fam), mets in tmpl_data.items():
                n = len(mets)
                sharpes = [float(m.get("sharpe") or 0) for m in mets]
                fitnesses = [float(m.get("fitness") or 0) for m in mets]
                turnovers = [float(m.get("turnover") or 0) for m in mets]
                results.append({
                    "template_id": tid,
                    "family": fam,
                    "n_runs": n,
                    "avg_sharpe": sum(sharpes) / n if n else 0,
                    "avg_fitness": sum(fitnesses) / n if n else 0,
                    "avg_turnover": sum(turnovers) / n if n else 0,
                })
            if results:
                print(f"[STATS_FALLBACK] Aggregated {len(results)} templates from {len(metrics)} runs (RPC unavailable)")
            return results
        except Exception as e:
            print(f"[STATS_FALLBACK_ERROR] template stats fallback failed: {e}")
            return []

    def get_recent_settings_stats(self, limit: int = 500) -> dict[str, list[dict]]:
        """Performance stats grouped by each settings dimension."""
        try:
            rows = self._rpc("get_settings_stats", {"run_limit": limit, "owner_filter": self.owner})
        except Exception:
            rows = self._rpc("get_settings_stats", {"run_limit": limit})
        # RPC returns flat rows with a 'dimension' column - group by dimension
        results: dict[str, list[dict]] = {
            "universe": [], "neutralization": [], "decay": [], "truncation": [],
        }
        for row in rows:
            dim = row.get("dimension", "")
            if dim in results:
                results[dim].append(row)
        return results

    def get_submitted_candidate_rows(self, *, limit: int = 300) -> list[dict]:
        try:
            return self._rpc("get_submitted_candidates", {"row_limit": limit, "owner_filter": self.owner})
        except Exception:
            return self._rpc("get_submitted_candidates", {"row_limit": limit})

    def get_all_team_submissions(self, *, limit: int = 500) -> list[dict]:
        """All team submissions (no owner filter) for cross-bot correlation checks."""
        try:
            return self._rpc("get_submitted_candidates", {"row_limit": limit, "owner_filter": None})
        except Exception:
            return self._rpc("get_submitted_candidates", {"row_limit": limit})

    def get_submission_eligible_candidates(self, *, limit: int = 50) -> list[dict]:
        try:
            return self._rpc("get_eligible_candidates", {"row_limit": limit, "owner_filter": self.owner})
        except Exception:
            return self._rpc("get_eligible_candidates", {"row_limit": limit})

    def get_similarity_reference_candidates(
        self, *, limit: int, min_sharpe: float, min_fitness: float,
    ) -> list[dict]:
        return self._rpc("get_reference_candidates", {
            "row_limit": limit,
            "min_s": min_sharpe,
            "min_f": min_fitness,
        })

    def get_recent_bucket_reference_candidates(self, *, limit: int) -> list[dict]:
        # reuse reference candidates with low thresholds
        return self.get_similarity_reference_candidates(
            limit=limit, min_sharpe=0.0, min_fitness=0.0,
        )

    # utility / compatibility

    def get_submitted_alphas(self, *, limit: int = 300) -> list[dict]:
        return self.get_submitted_candidate_rows(limit=limit)

    def get_refinement_report(self, limit: int = 250) -> list[dict]:
        return self._get("refinement_queue", {
            "select": "*",
            "order": "priority.desc",
            "limit": str(limit),
        })

    def register_manual_submission(self, expression_hash: str, alpha_id: str | None = None) -> bool:
        cand = self.get_candidate_by_hash(expression_hash)
        if not cand:
            return False

        cid = cand["candidate_id"]

        # find the best completed run for this candidate
        runs = self._get("runs", {
            "candidate_id": f"eq.{cid}",
            "status": "eq.completed",
            "select": "run_id",
            "order": "completed_at.desc",
            "limit": "1",
        })
        rid = runs[0]["run_id"] if runs else "manual_run"

        from models import new_id, utc_now
        self.insert_submission(
            submission_id=new_id("sub"),
            candidate_id=cid,
            run_id=rid,
            submitted_at=utc_now(),
            submission_status="submitted",
            message="manually_registered",
        )
        return True

    def register_manual_submission_by_candidate_id(self, candidate_id: str) -> bool:
        cand = self.get_candidate_by_id(candidate_id)
        if not cand:
            return False

        runs = self._get("runs", {
            "candidate_id": f"eq.{candidate_id}",
            "status": "eq.completed",
            "select": "run_id",
            "order": "completed_at.desc",
            "limit": "1",
        })
        rid = runs[0]["run_id"] if runs else "manual_run"

        from models import new_id, utc_now
        self.insert_submission(
            submission_id=new_id("sub"),
            candidate_id=candidate_id,
            run_id=rid,
            submitted_at=utc_now(),
            submission_status="submitted",
            message="manually_registered",
        )
        return True

    # optuna warm-start data retrieval

    def get_runs_for_expression(self, expression: str) -> list[dict]:
        """
        Completed runs for a specific expression, with full settings + metrics.
        Three batch queries (PostgREST IN filters) replace the old N+1 pattern -
        this runs on every Optuna warm-start, so it was a major latency/load source.
        """
        # step 1: candidates matching this expression
        cands = self._get("candidates", {
            "select": "candidate_id,settings_json,canonical_expression",
            "canonical_expression": f"eq.{expression}",
            "limit": "50",
        })
        if not cands:
            return []

        # step 2: batch-fetch all completed runs for these candidates in one call
        cand_id_csv = ",".join(c["candidate_id"] for c in cands)
        runs = self._get("runs", {
            "select": "run_id,candidate_id",
            "candidate_id": f"in.({cand_id_csv})",
            "status": "eq.completed",
            "limit": "1000",
        })
        if not runs:
            return []

        # step 3: batch-fetch all metrics for these runs in one call
        run_id_csv = ",".join(r["run_id"] for r in runs)
        mets_rows = self._get("metrics", {
            "select": "run_id,sharpe,fitness,turnover",
            "run_id": f"in.({run_id_csv})",
            "limit": "1000",
        })

        # run_id -> metrics row
        mets_by_run = {m["run_id"]: m for m in mets_rows}
        # candidate_id -> settings dict
        import json as _json
        cands_by_id = {}
        for c in cands:
            sj = c.get("settings_json")
            settings = _json.loads(sj) if isinstance(sj, str) else (sj or {})
            cands_by_id[c["candidate_id"]] = settings

        # assemble results
        results = []
        for run in runs:
            mets = mets_by_run.get(run["run_id"])
            if not mets:
                continue
            settings = cands_by_id.get(run["candidate_id"], {})
            results.append({
                "run_id": run["run_id"],
                "settings_json": settings,
                "sharpe": mets.get("sharpe"),
                "fitness": mets.get("fitness"),
                "turnover": mets.get("turnover"),
            })
        return results

    def get_runs_for_core_signal(self, core_signal: str) -> list[dict]:
        """
        Completed runs whose expression contains the core signal.
        Batch IN-filter queries replace the old N+1 pattern (3 queries regardless
        of candidate count).
        """
        # PostgREST LIKE query for candidates
        cands = self._get("candidates", {
            "select": "candidate_id,settings_json,canonical_expression",
            "canonical_expression": f"like.*{core_signal[:40]}*",
            "limit": "30",
        })
        if not cands:
            return []

        # batch fetch runs
        cand_id_csv = ",".join(c["candidate_id"] for c in cands)
        runs = self._get("runs", {
            "select": "run_id,candidate_id",
            "candidate_id": f"in.({cand_id_csv})",
            "status": "eq.completed",
            "limit": "300",
        })
        if not runs:
            return []

        # batch fetch metrics (only useful ones - fitness present)
        run_id_csv = ",".join(r["run_id"] for r in runs)
        mets_rows = self._get("metrics", {
            "select": "run_id,sharpe,fitness,turnover",
            "run_id": f"in.({run_id_csv})",
            "limit": "300",
        })

        mets_by_run = {m["run_id"]: m for m in mets_rows}
        import json as _json
        cands_by_id = {}
        for c in cands:
            sj = c.get("settings_json")
            settings = _json.loads(sj) if isinstance(sj, str) else (sj or {})
            cands_by_id[c["candidate_id"]] = settings

        results = []
        for run in runs:
            mets = mets_by_run.get(run["run_id"])
            if not mets or not mets.get("fitness"):
                continue
            settings = cands_by_id.get(run["candidate_id"], {})
            results.append({
                "run_id": run["run_id"],
                "settings_json": settings,
                "sharpe": mets.get("sharpe"),
                "fitness": mets.get("fitness"),
                "turnover": mets.get("turnover"),
            })
            if len(results) >= 30:
                break
        return results

    def get_runs_for_family(self, family: str) -> list[dict]:
        """
        Top completed runs from the same family, for cross-pollination.
        Batch IN-filter queries replace the old N+1 pattern.
        """
        cands = self._get("candidates", {
            "select": "candidate_id,settings_json",
            "family": f"eq.{family}",
            "limit": "50",
        })
        if not cands:
            return []

        cand_id_csv = ",".join(c["candidate_id"] for c in cands)
        runs = self._get("runs", {
            "select": "run_id,candidate_id",
            "candidate_id": f"in.({cand_id_csv})",
            "status": "eq.completed",
            "limit": "250",
        })
        if not runs:
            return []

        run_id_csv = ",".join(r["run_id"] for r in runs)
        mets_rows = self._get("metrics", {
            "select": "run_id,sharpe,fitness,turnover",
            "run_id": f"in.({run_id_csv})",
            "limit": "250",
        })

        mets_by_run = {m["run_id"]: m for m in mets_rows}
        import json as _json
        cands_by_id = {}
        for c in cands:
            sj = c.get("settings_json")
            settings = _json.loads(sj) if isinstance(sj, str) else (sj or {})
            cands_by_id[c["candidate_id"]] = settings

        results = []
        for run in runs:
            mets = mets_by_run.get(run["run_id"])
            if not mets or (mets.get("fitness") or 0) <= 0.5:
                continue
            settings = cands_by_id.get(run["candidate_id"], {})
            results.append({
                "run_id": run["run_id"],
                "settings_json": settings,
                "sharpe": mets.get("sharpe"),
                "fitness": mets.get("fitness"),
                "turnover": mets.get("turnover"),
            })
            if len(results) >= 30:
                break
        return results

    def get_concentrated_weight_failures(self, *, limit: int = 500) -> list[str]:
        """Canonical expressions that failed the CONCENTRATED_WEIGHT check."""
        mets = self._get("metrics", {
            "select": "run_id",
            "fail_reason": "like.*CONCENTRATED_WEIGHT*",
            "limit": str(limit),
        })
        if not mets:
            return []

        expressions = set()
        for m in mets:
            rid = m["run_id"]
            runs = self._get("runs", {
                "select": "candidate_id",
                "run_id": f"eq.{rid}",
                "limit": "1",
            })
            if runs:
                cid = runs[0]["candidate_id"]
                cands = self._get("candidates", {
                    "select": "canonical_expression",
                    "candidate_id": f"eq.{cid}",
                    "limit": "1",
                })
                if cands and cands[0].get("canonical_expression"):
                    expressions.add(cands[0]["canonical_expression"])
        return list(expressions)

    def get_self_correlation_rejections(self, *, limit: int = 500) -> list[dict]:
        """
        Candidates rejected by WQ for self-correlation. Checks both the
        submissions and submissions_archive tables.
        """
        subs = []
        # active submissions
        try:
            subs.extend(self._get("submissions", {
                "select": "candidate_id",
                "submission_status": "eq.rejected",
                "message": "like.*SELF_CORRELATION*",
                "limit": str(limit),
            }) or [])
        except Exception:
            pass
        # archive
        try:
            subs.extend(self._get("submissions_archive", {
                "select": "candidate_id",
                "submission_status": "eq.rejected",
                "message": "like.*SELF_CORRELATION*",
                "limit": str(limit),
            }) or [])
        except Exception:
            pass

        if not subs:
            return []

        results = []
        seen = set()
        for s in subs:
            cid = s["candidate_id"]
            if cid in seen:
                continue
            seen.add(cid)
            cands = self._get("candidates", {
                "select": "canonical_expression,candidate_id",
                "candidate_id": f"eq.{cid}",
                "limit": "1",
            })
            if cands:
                results.append({
                    "canonical_expression": cands[0].get("canonical_expression", ""),
                    "candidate_id": cid,
                })
        return results

    def insert_review_queue(self, *, candidate_id, run_id, expression, core_signal,
                            family, template_id, sharpe, fitness, turnover, settings_json):
        """Add an eligible alpha to the review queue for a manual submission decision."""
        self._post("review_queue", {
            "candidate_id": candidate_id,
            "run_id": run_id,
            "expression": expression,
            "core_signal": core_signal,
            "family": family,
            "template_id": template_id,
            "sharpe": sharpe,
            "fitness": fitness,
            "turnover": turnover,
            "settings_json": settings_json,
            "status": "pending",
            "owner": self.owner,
        })

    def insert_ready_alpha(self, *, candidate_id, run_id, alpha_id, expression,
                           core_signal, family, template_id, sharpe, fitness,
                           turnover, score_before, score_after, score_change,
                           settings_json, variant_desc, status="ready"):
        """Stage an optimised alpha for manual submission."""
        self._post("ready_alphas", {
            "candidate_id": candidate_id,
            "run_id": run_id,
            "alpha_id": alpha_id,
            "expression": expression,
            "core_signal": core_signal,
            "family": family,
            "template_id": template_id,
            "sharpe": sharpe,
            "fitness": fitness,
            "turnover": turnover,
            "score_before": score_before,
            "score_after": score_after,
            "score_change": score_change,
            "settings_json": settings_json,
            "variant_desc": variant_desc,
            "status": status,
            "owner": self.owner,
        })


    # bot state (graceful shutdown / resume)

    def save_bot_state(
        self,
        status: str,
        completion_count: int = 0,
        interrupted_refinement_ids: list[str] | None = None,
        interrupted_optuna_ids: list[str] | None = None,
        refinement_counters: dict | None = None,
    ) -> None:
        """Save bot state for graceful shutdown / resume."""
        now = datetime.now(timezone.utc).isoformat()
        self._post("bot_state", {
            "owner": self.owner,
            "status": status,
            "last_heartbeat": now,
            "last_completion_count": completion_count,
            "interrupted_refinement_ids": json.dumps(interrupted_refinement_ids or []),
            "interrupted_optuna_ids": json.dumps(interrupted_optuna_ids or []),
            "config_snapshot": json.dumps(refinement_counters or {}),
            "stopped_at": now if status in ("stopped", "interrupted") else None,
            "started_at": now if status == "running" else None,
            "updated_at": now,
        }, upsert=True)

    def get_bot_state(self) -> Optional[dict]:
        """Load this bot's last saved state."""
        rows = self._get("bot_state", {
            "owner": f"eq.{self.owner}",
            "limit": "1",
        })
        return rows[0] if rows else None

    def heartbeat(self) -> None:
        """Update the heartbeat timestamp - shows the bot is alive."""
        now = datetime.now(timezone.utc).isoformat()
        self._patch("bot_state", {"owner": self.owner}, {
            "last_heartbeat": now,
            "status": "running",
            "updated_at": now,
        })

    def get_own_unconsumed_refinement_count(self) -> int:
        """How many refinement items are queued for this bot."""
        rows = self._get("refinement_queue", {
            "consumed": "eq.false",
            "owner": f"eq.{self.owner}",
            "select": "candidate_id",
        })
        return len(rows)

    def un_consume_refinement(self, candidate_id: str) -> None:
        """Re-queue a refinement candidate that was interrupted mid-processing."""
        self._patch("refinement_queue", {"candidate_id": candidate_id}, {
            "consumed": False,
        })

    def mark_runs_interrupted(self, run_ids: list[str]) -> None:
        """Mark in-flight runs as interrupted (resumable on next start)."""
        for rid in run_ids:
            try:
                self._patch("runs", {"run_id": rid}, {
                    "status": "interrupted",
                    "error_message": "Bot shutdown - will resume on restart",
                })
            except Exception as e:
                logger.warning(f"[SHUTDOWN] Failed to mark run {rid} interrupted: {e}")

    # activity log (team monitoring)

    def log_activity(
        self,
        family: str,
        template_id: str,
        expression_short: str,
        sharpe: float | None = None,
        fitness: float | None = None,
        turnover: float | None = None,
        eligible: bool = False,
        fail_reason: str | None = None,
        was_refinement: bool = False,
        submitted: bool = False,
        score_change: float | None = None,
    ) -> None:
        """Log a completed sim to the activity table for team monitoring."""
        try:
            self._post("bot_activity", {
                "owner": self.owner,
                "family": family,
                "template_id": template_id,
                "expression_short": expression_short[:80],
                "sharpe": sharpe,
                "fitness": fitness,
                "turnover": turnover,
                "eligible": eligible,
                "fail_reason": fail_reason,
                "was_refinement": was_refinement,
                "submitted": submitted,
                "score_change": score_change,
            })
        except Exception as e:
            pass  # never crash the bot over logging

    def update_dashboard(
        self,
        total_sims: int = 0,
        total_eligible: int = 0,
        total_submitted: int = 0,
        sims_since_eligible: int = 0,
        stall_level: int = 0,
        last_error: str | None = None,
        last_report: str | None = None,
    ) -> None:
        """Update the bot_state dashboard fields."""
        now = datetime.now(timezone.utc).isoformat()
        try:
            self._patch("bot_state", {"owner": self.owner}, {
                "total_sims": total_sims,
                "total_eligible": total_eligible,
                "total_submitted": total_submitted,
                "sims_since_eligible": sims_since_eligible,
                "stall_level": stall_level,
                "last_error": last_error,
                "last_report": (last_report or "")[:4000],  # cap at 4KB
                "updated_at": now,
            })
        except Exception as e:
            pass  # never crash over dashboard

    def prune_activity_log(self, max_per_owner: int = 2000) -> None:
        """Remove old activity rows to keep the table small."""
        try:
            self._rpc("prune_bot_activity", {"max_per_owner": max_per_owner})
        except Exception:
            pass


class _EmptyResult:
    """Stub for compatibility with raw SQL execute calls."""
    def fetchall(self):
        return []
    def fetchone(self):
        return None
