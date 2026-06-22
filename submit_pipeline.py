"""Automated submission pipeline.

Each teammate runs this at their scheduled window (2x daily, 12h apart).
Processes only their own ready_alphas, re-checks scores after each submission,
never submits negative.

Schedule (configured via SUBMIT_SCHEDULE in config.py):
    Owner 1: 05:00, 17:00
    Owner 2: 06:00, 18:00
    Owner 3: 07:00, 19:00
    Owner 4: 08:00, 20:00

Can also be triggered manually: python submit_pipeline.py
"""
from __future__ import annotations

import json
import time
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class SubmitPipeline:
    """Automated alpha submission with score re-checking."""

    # delay between submissions (seconds) - let WQ update portfolio state
    DELAY_BETWEEN_SUBMISSIONS = 10

    # delay after re-checking scores (seconds) - API rate limiting
    DELAY_BETWEEN_CHECKS = 3

    def __init__(self, storage, client, config):
        self.storage = storage
        self.client = client
        self.config = config
        self.owner = storage.owner
        self.MIN_SCORE_TO_SUBMIT = getattr(config, "SUBMIT_MIN_SCORE", 3)

    def run(self) -> dict[str, Any]:
        """
        Run the full submission pipeline.

        Returns summary dict with counts.
        """
        print(f"\n{'='*60}")
        print(f"  SUBMISSION PIPELINE - {self.owner}")
        print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        print(f"{'='*60}\n")

        # step 0: retry unverified alphas - promote to 'ready' if score available
        self._retry_unverified()

        # step 1: load all ready alphas for this owner
        alphas = self._load_ready_alphas()
        if not alphas:
            print("  No ready alphas to submit.")
            return {"submitted": 0, "rejected": 0, "total": 0}

        print(f"  Loaded {len(alphas)} ready alphas\n")

        # step 2: re-check all scores (landscape may have shifted)
        print("  Re-checking scores for all alphas...")
        alphas = self._recheck_scores(alphas)

        # step 3: drop truly negative scores (< STAGING_FLOOR), keep marginal for recheck.
        # uses config.STAGING_FLOOR (-25) instead of a hardcoded -10, which used to
        # silently reject valid marginal alphas during recheck.
        _floor = getattr(self.config, "STAGING_FLOOR", -25)
        positive = [a for a in alphas if a.get("live_score") is not None and a["live_score"] >= self.MIN_SCORE_TO_SUBMIT]
        truly_negative = [a for a in alphas if a.get("live_score") is not None and a["live_score"] < _floor]
        unknown = [a for a in alphas if a.get("live_score") is None]

        # retry unknowns once after a pause - the API can be intermittent
        if unknown:
            print(f"\n  {len(unknown)} unknown scores - retrying after 10s pause...")
            time.sleep(10)
            still_unknown = []
            for a in unknown:
                alpha_id = a.get("alpha_id")
                if not alpha_id:
                    still_unknown.append(a)
                    continue
                try:
                    perf = self.client.check_before_after_performance(
                        alpha_id, competition_id=self.config.IQC_COMPETITION_ID,
                    )
                    score = perf.get("_score_change")
                    if score is not None:
                        a["live_score"] = score
                        direction = "+" if score > 0 else ""
                        print(f"    + {a.get('family','')}/{a.get('template_id','')} "
                              f"S={a.get('sharpe',0):.2f} -> score: {direction}{score}")
                        if score >= self.MIN_SCORE_TO_SUBMIT:
                            positive.append(a)
                        elif score < _floor:
                            truly_negative.append(a)
                    else:
                        still_unknown.append(a)
                except Exception:
                    still_unknown.append(a)
                time.sleep(3)
            unknown = still_unknown

        print(f"\n  After re-check: {len(positive)} positive, {len(truly_negative)} truly negative, {len(unknown)} unknown")

        for a in truly_negative:
            self._mark_status(a, "rejected", f"negative_score={a['live_score']}")

        # step 4: greedy loop - submit highest, re-check all, repeat
        submitted = 0
        rejected = len(truly_negative)
        remaining = list(positive)

        while remaining:
            # sort by score descending
            remaining.sort(key=lambda a: a.get("live_score", 0) or 0, reverse=True)
            best = remaining[0]

            print(f"\n  -- Submitting #{submitted+1}: score +{best['live_score']:.0f} "
                  f"S={best['sharpe']:.2f} F={best['fitness']:.2f} "
                  f"family={best.get('family','')} core={best.get('core_signal','')[:50]}")

            success = self._submit_alpha(best)
            remaining = [a for a in remaining if a["id"] != best["id"]]

            if success:
                submitted += 1
                self._mark_status(best, "submitted", f"score={best['live_score']:+.0f}")

                if remaining:
                    # re-check all remaining after submission
                    print(f"\n  Re-checking {len(remaining)} remaining alphas...")
                    remaining = self._recheck_scores(remaining)

                    # drop anything that went truly negative (< STAGING_FLOOR)
                    for a in remaining:
                        if a.get("live_score") is not None and a["live_score"] < _floor:
                            self._mark_status(a, "rejected", f"went_negative={a['live_score']}")
                            rejected += 1

                    remaining = [a for a in remaining
                                 if a.get("live_score") is not None
                                 and a["live_score"] >= self.MIN_SCORE_TO_SUBMIT]
                    print(f"  {len(remaining)} still positive")
            else:
                self._mark_status(best, "rejected", "submit_failed")
                rejected += 1

        # summary
        print(f"\n{'='*60}")
        print(f"  SUBMISSION COMPLETE")
        print(f"  Submitted: {submitted}")
        print(f"  Rejected:  {rejected}")
        print(f"  Skipped:   {len(unknown)} (unknown score)")
        print(f"{'='*60}\n")

        return {"submitted": submitted, "rejected": rejected, "skipped": len(unknown), "total": len(alphas)}

    # data loading

    def _load_ready_alphas(self) -> list[dict]:
        """Load ready alphas for this owner only."""
        try:
            rows = self.storage._get("ready_alphas", {
                "owner": f"eq.{self.owner}",
                "status": "eq.ready",
                "select": "*",
                "order": "score_change.desc.nullslast",
            })
            return rows or []
        except Exception as e:
            print(f"  ERROR loading ready_alphas: {e}")
            return []

    def _load_unverified_alphas(self) -> list[dict]:
        """Load unverified alphas for this owner."""
        try:
            rows = self.storage._get("ready_alphas", {
                "owner": f"eq.{self.owner}",
                "status": "eq.unverified",
                "select": "*",
                "order": "sharpe.desc",
            })
            return rows or []
        except Exception as e:
            print(f"  ERROR loading unverified alphas: {e}")
            return []

    def _retry_unverified(self) -> None:
        """
        Retry unverified alphas - check self-corr and before-after score.
        Promote to 'ready' if self-corr passes, reject if self-corr fails or score negative.
        """
        unverified = self._load_unverified_alphas()
        if not unverified:
            return

        print(f"  Retrying {len(unverified)} unverified alphas...")
        promoted = 0
        rejected = 0

        for a in unverified:
            alpha_id = a.get("alpha_id")
            if not alpha_id:
                continue

            # step 1: check self-correlation first
            try:
                check = self.client.check_alpha(alpha_id)
            except Exception:
                print(f"    ~ API timeout S={a.get('sharpe',0):.2f}")
                time.sleep(self.DELAY_BETWEEN_CHECKS)
                continue

            if check.get("_passed") is False:
                self._mark_status(a, "rejected",
                    f"self_corr_fail: corr={check.get('_self_correlation')} with={check.get('_correlated_with')}")
                rejected += 1
                print(f"    x SELF-CORR FAILED S={a.get('sharpe',0):.2f} corr={check.get('_self_correlation')}")
                time.sleep(self.DELAY_BETWEEN_CHECKS)
                continue

            if check.get("_passed") is None:
                print(f"    ~ Self-corr still pending S={a.get('sharpe',0):.2f}")
                time.sleep(self.DELAY_BETWEEN_CHECKS)
                continue

            # step 2: self-corr passed - check before-after score
            score = None
            for attempt in range(3):
                try:
                    perf = self.client.check_before_after_performance(
                        alpha_id, competition_id=self.config.IQC_COMPETITION_ID,
                    )
                    score = perf.get("_score_change")
                    if score is not None:
                        break
                except Exception:
                    pass
                if attempt < 2:
                    time.sleep(self.DELAY_BETWEEN_CHECKS)

            if score is not None and score >= self.MIN_SCORE_TO_SUBMIT:
                self._mark_status(a, "ready", f"retry_promoted: score={score:+.0f}")
                promoted += 1
                print(f"    + PROMOTED S={a.get('sharpe',0):.2f} score={score:+.0f} -> ready")
            elif score is not None and score < 0:
                self._mark_status(a, "rejected", f"retry_negative: score={score:+.0f}")
                rejected += 1
                print(f"    x REJECTED S={a.get('sharpe',0):.2f} score={score:+.0f}")
            else:
                # self-corr passed but score unavailable - promote anyway.
                # the main pipeline will re-check score before submitting.
                self._mark_status(a, "ready", f"self_corr_passed_score_unknown")
                promoted += 1
                print(f"    + PROMOTED (self-corr passed, score pending) S={a.get('sharpe',0):.2f} -> ready")

            time.sleep(self.DELAY_BETWEEN_CHECKS)

        if promoted or rejected:
            print(f"  Unverified retry: {promoted} promoted, {rejected} rejected, "
                  f"{len(unverified) - promoted - rejected} still pending\n")

    # score checking

    def _recheck_scores(self, alphas: list[dict]) -> list[dict]:
        """Re-check before-after scores for all alphas. Updates live_score field."""
        for i, a in enumerate(alphas):
            alpha_id = a.get("alpha_id")
            if not alpha_id:
                a["live_score"] = None
                continue

            # retry up to 3 times
            score = None
            for attempt in range(3):
                try:
                    perf = self.client.check_before_after_performance(
                        alpha_id, competition_id=self.config.IQC_COMPETITION_ID,
                    )
                    score = perf.get("_score_change")
                    if score is not None:
                        break
                except Exception:
                    pass
                if attempt < 2:
                    time.sleep(self.DELAY_BETWEEN_CHECKS)

            a["live_score"] = score
            direction = "+" if score and score > 0 else "" if score else "?"
            print(f"    [{i+1}/{len(alphas)}] {a.get('family','')}/{a.get('template_id','')} "
                  f"S={a.get('sharpe',0):.2f} -> score: {direction}{score if score is not None else 'unknown'}")

            time.sleep(self.DELAY_BETWEEN_CHECKS)

        return alphas

    def _recheck_single(self, alpha: dict) -> dict | None:
        """Re-check a single alpha's score."""
        alpha_id = alpha.get("alpha_id")
        if not alpha_id:
            return None

        for attempt in range(3):
            try:
                perf = self.client.check_before_after_performance(
                    alpha_id, competition_id=self.config.IQC_COMPETITION_ID,
                )
                score = perf.get("_score_change")
                if score is not None:
                    alpha["live_score"] = score
                    return alpha
            except Exception:
                pass
            if attempt < 2:
                time.sleep(self.DELAY_BETWEEN_CHECKS)

        alpha["live_score"] = None
        return alpha

    # grouping

    def _group_by_core(self, alphas: list[dict]) -> list[tuple[str, list[dict]]]:
        """Group alphas by core_signal, sorted by best score in group (descending)."""
        groups: dict[str, list[dict]] = {}
        for a in alphas:
            core = a.get("core_signal") or a.get("expression", "")[:80]
            groups.setdefault(core, []).append(a)

        # sort groups by the best live_score in each group
        sorted_groups = sorted(
            groups.items(),
            key=lambda x: max((a.get("live_score") or 0) for a in x[1]),
            reverse=True,
        )
        return sorted_groups

    # submission

    def _submit_alpha(self, alpha: dict) -> bool:
        """Submit a single alpha to WQ. Returns True if accepted.

        Defense-in-depth score guard. the greedy loop in run() already filters by
        live_score >= MIN_SCORE_TO_SUBMIT, but this guard is the final boundary so
        the rule can never be bypassed by future refactors.
        """
        alpha_id = alpha.get("alpha_id")
        if not alpha_id:
            print(f"     x No alpha_id - cannot submit")
            return False

        # hard score floor - never submit anything below SUBMIT_MIN_SCORE.
        min_score = getattr(self.config, "SUBMIT_MIN_SCORE", 15)
        # submit_pipeline uses 'live_score' as the freshly-rechecked score
        score = alpha.get("live_score")
        if score is None:
            score = alpha.get("score_change")
        if score is None or float(score) < min_score:
            print(
                f"     [SCORE_GUARD] Refusing to submit alpha_id={alpha_id} "
                f"score={score} < min_score={min_score}"
            )
            return False

        print(f"     Submitting alpha_id={alpha_id}...")
        time.sleep(self.DELAY_BETWEEN_SUBMISSIONS)

        try:
            result = self.client.submit_alpha(alpha_id)
            accepted = result.get("_accepted")

            if accepted is True:
                print(f"     + ACCEPTED - score +{alpha.get('live_score', '?')}")
                # log to submissions table
                try:
                    from models import new_id, utc_now
                    self.storage.insert_submission(
                        submission_id=new_id("sub"),
                        candidate_id=alpha.get("candidate_id", ""),
                        run_id=alpha.get("run_id", ""),
                        submitted_at=utc_now(),
                        submission_status="confirmed",
                        message=f"auto_pipeline: score={alpha.get('live_score', '?')} "
                                f"S={alpha.get('sharpe', 0):.2f} F={alpha.get('fitness', 0):.2f}",
                    )
                except Exception:
                    pass
                return True
            else:
                fail = result.get("_fail_reason", "unknown")
                corr = result.get("_self_correlation", "")
                # track rejected submissions in the submissions table too so warm-start
                # can learn rejected cores and skip them next run.
                try:
                    from models import new_id, utc_now
                    self.storage.insert_submission(
                        submission_id=new_id("sub"),
                        candidate_id=alpha.get("candidate_id", ""),
                        run_id=alpha.get("run_id", ""),
                        submitted_at=utc_now(),
                        submission_status="rejected",
                        message=f"rejected at submit: {fail}" + (f" (corr={corr})" if corr else ""),
                    )
                except Exception:
                    pass
                print(f"     x Rejected: {fail} (corr={corr})")
                return False

        except Exception as exc:
            print(f"     x Submit error: {exc}")
            return False

    # status management

    def _mark_status(self, alpha: dict, status: str, notes: str = "") -> None:
        """Update the status of a ready_alpha row."""
        # try 'id' first (Supabase dashboard-created tables), fall back to candidate_id
        match_key = None
        match_val = None
        for key in ["id", "candidate_id"]:
            if alpha.get(key) is not None:
                match_key = key
                match_val = str(alpha[key])
                break
        if match_key is None:
            return
        try:
            self.storage._patch("ready_alphas", {match_key: match_val}, {
                "status": status,
                "notes": notes[:500],
            })
        except Exception:
            pass


# scheduling logic

def get_submit_schedule(owner: str) -> list[int]:
    """Return submission hours (UTC) for this owner.

    Returns empty list if owner not in schedule (= disabled).
    Configure in config.py SUBMIT_SCHEDULE.
    """
    import config
    schedule = getattr(config, "SUBMIT_SCHEDULE", {})
    return schedule.get(owner, [])


def should_submit_now(owner: str) -> bool:
    """Check if current UTC time matches this owner's submission window.
    Fires at SUBMIT_MINUTE past the scheduled hour (default :30)."""
    import config
    hours = get_submit_schedule(owner)
    if not hours:
        return False
    now = datetime.now(timezone.utc)
    submit_minute = getattr(config, "SUBMIT_MINUTE", 0)
    return now.hour in hours and now.minute >= submit_minute


# standalone entry point

if __name__ == "__main__":
    """Run submission pipeline directly: python submit_pipeline.py"""
    import config
    from brain_client import BrainClient
    from storage_factory import get_storage

    storage = get_storage()
    client = BrainClient(
        username=config.BRAIN_USERNAME,
        password=config.BRAIN_PASSWORD,
        base_url="https://api.worldquantbrain.com",
    )

    pipeline = SubmitPipeline(storage, client, config)
    result = pipeline.run()
    print(f"\nResult: {result}")


# teammate score checking

class TeammateScoreChecker:
    """
    Re-simulate teammates' alphas through the coordinator's own credentials to
    get scores. Runs concurrent sims for speed. Updates scores in Supabase
    (keeping original owner) for manual submission.
    """

    CONCURRENT = 2       # leave 1 slot free for any trailing bot sims
    SIM_TIMEOUT = 180    # 3 minutes per batch - WQ can be slow under load
    SCORE_TIMEOUT = 45   # seconds for before-after check

    def __init__(self, storage, client, config):
        self.storage = storage
        self.client = client
        self.config = config

    def run(self, teammate_owners: list[str]) -> dict:
        """Check scores for all teammates' ready alphas using parallel re-simulation."""
        import time
        import json
        from datetime import datetime, timezone

        total_checked = 0
        total_positive = 0
        total_negative = 0
        total_unknown = 0

        for owner in teammate_owners:
            print(f"\n{'='*60}")
            print(f"  TEAMMATE SCORE CHECK - {owner}")
            print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
            print(f"{'='*60}\n")

            alphas = self._load_teammate_alphas(owner)
            if not alphas:
                print(f"  No ready/unverified alphas for {owner}")
                continue

            print(f"  Checking {len(alphas)} alphas ({self.CONCURRENT} concurrent)\n")

            # process in batches of CONCURRENT
            for batch_start in range(0, len(alphas), self.CONCURRENT):
                batch = alphas[batch_start:batch_start + self.CONCURRENT]
                batch_num = batch_start // self.CONCURRENT + 1

                # step 1: submit all sims in batch
                in_flight = []  # (alpha, sim_id)
                for a in batch:
                    expr = a.get("expression", "")
                    settings_raw = a.get("settings_json", "{}")

                    if not expr:
                        total_unknown += 1
                        continue

                    if isinstance(settings_raw, str):
                        try:
                            settings = json.loads(settings_raw)
                        except (json.JSONDecodeError, TypeError):
                            settings = {}
                    else:
                        settings = settings_raw or {}

                    if not settings:
                        total_unknown += 1
                        continue

                    try:
                        sim_id = self.client.submit_simulation(expr, settings)
                        in_flight.append((a, sim_id))
                    except Exception as exc:
                        if "429" in str(exc) or "CONCURRENT" in str(exc).upper():
                            # wait and retry once
                            time.sleep(10)
                            try:
                                sim_id = self.client.submit_simulation(expr, settings)
                                in_flight.append((a, sim_id))
                            except Exception:
                                total_unknown += 1
                        else:
                            total_unknown += 1

                if not in_flight:
                    continue

                # step 2: poll all sims until complete
                results = {}  # sim_id -> result
                deadline = time.time() + self.SIM_TIMEOUT
                while len(results) < len(in_flight) and time.time() < deadline:
                    for a, sid in in_flight:
                        if sid in results:
                            continue
                        try:
                            r = self.client.poll_simulation(sid)
                            if r.get("status") in ("completed", "failed", "timed_out"):
                                results[sid] = r
                        except Exception:
                            pass
                    if len(results) < len(in_flight):
                        time.sleep(5)

                # step 3: extract alpha_ids and check scores
                for flight_idx, (a, sid) in enumerate(in_flight):
                    idx = batch_start + flight_idx + 1
                    family = a.get("family", "")
                    sharpe = a.get("sharpe", 0)

                    if sid not in results or results[sid].get("status") != "completed":
                        print(f"    [{idx}/{len(alphas)}] ~ {family} S={sharpe:.2f} - sim timeout")
                        total_unknown += 1
                        continue

                    # extract alpha_id from our simulation
                    alpha_id = None
                    try:
                        # poll_simulation stores as "alpha_id" (URL or bare ID)
                        alpha_raw = results[sid].get("alpha_id", "")
                        if alpha_raw:
                            alpha_id = str(alpha_raw).rstrip("/").split("/")[-1]
                    except Exception:
                        pass

                    if not alpha_id:
                        print(f"    [{idx}/{len(alphas)}] ~ {family} S={sharpe:.2f} - no alpha_id")
                        total_unknown += 1
                        continue

                    # check before-after score
                    score = None
                    for attempt in range(2):
                        try:
                            perf = self.client.check_before_after_performance(
                                alpha_id, competition_id=self.config.IQC_COMPETITION_ID,
                            )
                            score = perf.get("_score_change")
                            if score is not None:
                                break
                        except Exception:
                            pass
                        if attempt < 1:
                            time.sleep(3)

                    if score is not None:
                        direction = "+" if score > 0 else "-" if score < 0 else "="
                        print(f"    [{idx}/{len(alphas)}] {direction} {family} S={sharpe:.2f} -> {score:+.0f}")

                        # update score in Supabase (keeps original owner)
                        try:
                            self.storage._patch("ready_alphas", {"id": a["id"]}, {
                                "score_change": score,
                                "status": "ready" if score >= 0 else "rejected",
                            })
                        except Exception:
                            pass

                        if score > 0:
                            total_positive += 1
                        elif score < 0:
                            total_negative += 1
                        total_checked += 1
                    else:
                        print(f"    [{idx}/{len(alphas)}] ? {family} S={sharpe:.2f} -> score unavailable")
                        total_unknown += 1

            # summary for this teammate
            pos_alphas = [a for a in alphas if a.get("score_change") is not None and a.get("score_change", 0) > 0]
            if pos_alphas:
                print(f"\n  + POSITIVE ALPHAS FOR {owner}:")
                for a in sorted(pos_alphas, key=lambda x: x.get("score_change", 0), reverse=True):
                    print(f"    score={a.get('score_change', '?'):+.0f} "
                          f"S={a.get('sharpe', 0):.2f} {a.get('family', '')}")

        print(f"\n{'='*60}")
        print(f"  TEAMMATE CHECK COMPLETE")
        print(f"  Checked: {total_checked}  Positive: {total_positive}  "
              f"Negative: {total_negative}  Unknown: {total_unknown}")
        print(f"{'='*60}\n")

        return {
            "checked": total_checked,
            "positive": total_positive,
            "negative": total_negative,
            "unknown": total_unknown,
        }

    def _load_teammate_alphas(self, owner: str) -> list[dict]:
        """Load ready + unverified alphas for a teammate."""
        try:
            rows = self.storage._get("ready_alphas", {
                "owner": f"eq.{owner}",
                "status": "in.(ready,unverified)",
                "select": "*",
                "order": "sharpe.desc",
            })
            return rows or []
        except Exception as e:
            print(f"  ERROR loading alphas for {owner}: {e}")
            return []
