from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional

from models import Candidate, Metrics, Run


def dt_to_str(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat()


class Storage:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self.init_db()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        existing = {row["name"] for row in rows}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS candidates (
                    candidate_id TEXT PRIMARY KEY,
                    expression TEXT NOT NULL,
                    canonical_expression TEXT NOT NULL,
                    expression_hash TEXT NOT NULL UNIQUE,
                    template_id TEXT NOT NULL,
                    family TEXT NOT NULL,
                    fields_json TEXT NOT NULL,
                    params_json TEXT NOT NULL,
                    settings_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL,
                    sim_id TEXT,
                    alpha_id TEXT,
                    status TEXT NOT NULL,
                    submitted_at TEXT,
                    completed_at TEXT,
                    error_message TEXT,
                    raw_result_json TEXT,
                    FOREIGN KEY(candidate_id) REFERENCES candidates(candidate_id)
                );
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS metrics (
                    run_id TEXT PRIMARY KEY,
                    sharpe REAL,
                    fitness REAL,
                    turnover REAL,
                    returns REAL,
                    margin REAL,
                    drawdown REAL,
                    checks_passed INTEGER,
                    submit_eligible INTEGER,
                    fail_reason TEXT,
                    FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS submissions (
                    submission_id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    submitted_at TEXT NOT NULL,
                    submission_status TEXT NOT NULL,
                    message TEXT,
                    FOREIGN KEY(candidate_id) REFERENCES candidates(candidate_id),
                    FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS refinement_queue (
                    candidate_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    priority REAL NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    consumed INTEGER NOT NULL DEFAULT 0,
                    source_stage TEXT DEFAULT 'unknown',
                    base_sharpe REAL,
                    base_fitness REAL,
                    base_turnover REAL,
                    FOREIGN KEY(candidate_id) REFERENCES candidates(candidate_id),
                    FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );
                """
            )

            self._ensure_column(conn, "runs", "alpha_id", "alpha_id TEXT")
            self._ensure_column(conn, "refinement_queue", "source_stage", "source_stage TEXT DEFAULT 'unknown'")
            self._ensure_column(conn, "refinement_queue", "base_sharpe", "base_sharpe REAL")
            self._ensure_column(conn, "refinement_queue", "base_fitness", "base_fitness REAL")
            self._ensure_column(conn, "refinement_queue", "base_turnover", "base_turnover REAL")

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_candidates_family
                ON candidates(family);
                """
            )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_runs_status
                ON runs(status);
                """
            )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_runs_candidate_id
                ON runs(candidate_id);
                """
            )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_metrics_submit_eligible
                ON metrics(submit_eligible);
                """
            )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_refinement_consumed
                ON refinement_queue(consumed, priority DESC);
                """
            )

    def parse_dt(self, value: str) -> datetime:
        return datetime.fromisoformat(value)

    def candidate_exists(self, expression_hash: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM candidates
                WHERE expression_hash = ?
                LIMIT 1
                """,
                (expression_hash,),
            ).fetchone()
            return row is not None

    def insert_candidate(self, candidate: Candidate) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO candidates (
                    candidate_id,
                    expression,
                    canonical_expression,
                    expression_hash,
                    template_id,
                    family,
                    fields_json,
                    params_json,
                    settings_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.candidate_id,
                    candidate.expression,
                    candidate.canonical_expression,
                    candidate.expression_hash,
                    candidate.template_id,
                    candidate.family,
                    json.dumps(candidate.fields, sort_keys=True),
                    json.dumps(candidate.params, sort_keys=True),
                    json.dumps(candidate.settings.to_dict(), sort_keys=True),
                    dt_to_str(candidate.created_at),
                ),
            )

    def insert_run(self, run: Run) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO runs (
                    run_id,
                    candidate_id,
                    sim_id,
                    alpha_id,
                    status,
                    submitted_at,
                    completed_at,
                    error_message,
                    raw_result_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.candidate_id,
                    run.sim_id,
                    run.alpha_id,
                    run.status,
                    dt_to_str(run.submitted_at),
                    dt_to_str(run.completed_at),
                    run.error_message,
                    json.dumps(run.raw_result, sort_keys=True) if run.raw_result is not None else None,
                ),
            )

    def update_run(
        self,
        run_id: str,
        *,
        sim_id: Optional[str] = None,
        alpha_id: Optional[str] = None,
        status: Optional[str] = None,
        submitted_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
        error_message: Optional[str] = None,
        raw_result: Optional[dict[str, Any]] = None,
    ) -> None:
        fields: list[str] = []
        values: list[Any] = []

        if sim_id is not None:
            fields.append("sim_id = ?")
            values.append(sim_id)

        if alpha_id is not None:
            fields.append("alpha_id = ?")
            values.append(alpha_id)

        if status is not None:
            fields.append("status = ?")
            values.append(status)

        if submitted_at is not None:
            fields.append("submitted_at = ?")
            values.append(dt_to_str(submitted_at))

        if completed_at is not None:
            fields.append("completed_at = ?")
            values.append(dt_to_str(completed_at))

        if error_message is not None:
            fields.append("error_message = ?")
            values.append(error_message)

        if raw_result is not None:
            fields.append("raw_result_json = ?")
            values.append(json.dumps(raw_result, sort_keys=True))

        if not fields:
            return

        values.append(run_id)

        with self.connect() as conn:
            conn.execute(
                f"""
                UPDATE runs
                SET {", ".join(fields)}
                WHERE run_id = ?
                """,
                values,
            )

    def insert_metrics(self, metrics: Metrics) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO metrics (
                    run_id,
                    sharpe,
                    fitness,
                    turnover,
                    returns,
                    margin,
                    drawdown,
                    checks_passed,
                    submit_eligible,
                    fail_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    metrics.run_id,
                    metrics.sharpe,
                    metrics.fitness,
                    metrics.turnover,
                    metrics.returns,
                    metrics.margin,
                    metrics.drawdown,
                    int(metrics.checks_passed) if metrics.checks_passed is not None else None,
                    int(metrics.submit_eligible) if metrics.submit_eligible is not None else None,
                    metrics.fail_reason,
                ),
            )

    def insert_submission(
        self,
        submission_id: str,
        candidate_id: str,
        run_id: str,
        submitted_at: datetime,
        submission_status: str,
        message: Optional[str] = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO submissions (
                    submission_id,
                    candidate_id,
                    run_id,
                    submitted_at,
                    submission_status,
                    message
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    submission_id,
                    candidate_id,
                    run_id,
                    dt_to_str(submitted_at),
                    submission_status,
                    message,
                ),
            )

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
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO refinement_queue (
                    candidate_id,
                    run_id,
                    priority,
                    reason,
                    created_at,
                    consumed,
                    source_stage,
                    base_sharpe,
                    base_fitness,
                    base_turnover
                ) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    run_id,
                    priority,
                    reason,
                    dt_to_str(created_at),
                    source_stage,
                    base_sharpe,
                    base_fitness,
                    base_turnover,
                ),
            )

    def get_next_refinement_candidate(self):
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    rq.candidate_id,
                    rq.run_id,
                    rq.priority,
                    rq.reason,
                    c.template_id,
                    c.family,
                    c.params_json,
                    c.settings_json,
                    c.expression,
                    c.canonical_expression,
                    c.expression_hash,
                    rq.source_stage,
                    rq.base_sharpe,
                    rq.base_fitness,
                    rq.base_turnover
                FROM refinement_queue rq
                JOIN candidates c
                    ON rq.candidate_id = c.candidate_id
                WHERE rq.consumed = 0
                ORDER BY rq.priority DESC, rq.created_at ASC
                LIMIT 1
                """
            ).fetchone()
            return row

    def mark_refinement_consumed(self, candidate_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE refinement_queue
                SET consumed = 1
                WHERE candidate_id = ?
                """,
                (candidate_id,),
            )

    def get_running_runs(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM runs
                WHERE status IN ('submitted', 'running')
                """
            ).fetchall()
            return rows

    def get_run_by_id(self, run_id: str) -> Optional[sqlite3.Row]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM runs
                WHERE run_id = ?
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
            return row

    def get_candidate_by_id(self, candidate_id: str) -> Optional[sqlite3.Row]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM candidates
                WHERE candidate_id = ?
                LIMIT 1
                """,
                (candidate_id,),
            ).fetchone()
            return row

    def get_candidate_by_hash(self, expression_hash: str) -> Optional[sqlite3.Row]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM candidates
                WHERE expression_hash = ?
                LIMIT 1
                """,
                (expression_hash,),
            ).fetchone()
            return row

    def get_recent_family_stats(self, limit: int = 500) -> list[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    c.family,
                    COUNT(*) AS n_runs,
                    AVG(m.sharpe) AS avg_sharpe,
                    AVG(m.fitness) AS avg_fitness,
                    AVG(m.turnover) AS avg_turnover,
                    AVG(CASE WHEN m.submit_eligible = 1 THEN 1.0 ELSE 0.0 END) AS submit_rate
                FROM metrics m
                JOIN runs r ON m.run_id = r.run_id
                JOIN candidates c ON r.candidate_id = c.candidate_id
                WHERE r.run_id IN (
                    SELECT run_id
                    FROM runs
                    WHERE status = 'completed'
                    ORDER BY completed_at DESC
                    LIMIT ?
                )
                GROUP BY c.family
                ORDER BY n_runs DESC
                """,
                (limit,),
            ).fetchall()
            return rows

    def get_recent_template_stats(self, limit: int = 180) -> list[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    c.template_id,
                    c.family,
                    COUNT(*) AS n_runs,
                    AVG(m.sharpe) AS avg_sharpe,
                    AVG(m.fitness) AS avg_fitness,
                    AVG(m.turnover) AS avg_turnover
                FROM metrics m
                JOIN runs r ON m.run_id = r.run_id
                JOIN candidates c ON r.candidate_id = c.candidate_id
                WHERE r.run_id IN (
                    SELECT run_id
                    FROM runs
                    WHERE status = 'completed'
                    ORDER BY completed_at DESC
                    LIMIT ?
                )
                GROUP BY c.template_id, c.family
                ORDER BY n_runs DESC
                """,
                (limit,),
            ).fetchall()
            return rows

    def get_recent_settings_stats(self, limit: int = 500) -> dict[str, list[sqlite3.Row]]:
        """
        Return performance stats grouped by each settings dimension.
        Returns dict with keys: 'universe', 'neutralization', 'decay', 'truncation'.
        Each value is a list of rows with: setting_value, n_runs, avg_sharpe, avg_fitness.
        """
        results = {}
        with self.connect() as conn:
            for dim, json_key in [
                ("universe", "universe"),
                ("neutralization", "neutralization"),
                ("decay", "decay"),
                ("truncation", "truncation"),
            ]:
                rows = conn.execute(
                    f"""
                    SELECT
                        json_extract(c.settings_json, '$.{json_key}') AS setting_value,
                        COUNT(*) AS n_runs,
                        AVG(m.sharpe) AS avg_sharpe,
                        AVG(m.fitness) AS avg_fitness,
                        AVG(CASE WHEN m.submit_eligible = 1 THEN 1.0 ELSE 0.0 END) AS submit_rate
                    FROM metrics m
                    JOIN runs r ON m.run_id = r.run_id
                    JOIN candidates c ON r.candidate_id = c.candidate_id
                    WHERE r.run_id IN (
                        SELECT run_id
                        FROM runs
                        WHERE status = 'completed'
                        ORDER BY completed_at DESC
                        LIMIT ?
                    )
                    AND json_extract(c.settings_json, '$.{json_key}') IS NOT NULL
                    GROUP BY setting_value
                    ORDER BY avg_sharpe DESC
                    """,
                    (limit,),
                ).fetchall()
                results[dim] = rows
        return results

    def get_similarity_reference_candidates(
        self,
        *,
        limit: int,
        min_sharpe: float,
        min_fitness: float,
    ) -> list[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    c.candidate_id,
                    c.expression_hash,
                    c.canonical_expression,
                    c.template_id,
                    c.family,
                    c.fields_json,
                    c.params_json,
                    c.settings_json,
                    r.run_id,
                    r.alpha_id,
                    r.completed_at,
                    m.sharpe,
                    m.fitness,
                    m.turnover,
                    m.submit_eligible
                FROM runs r
                JOIN candidates c
                    ON r.candidate_id = c.candidate_id
                JOIN metrics m
                    ON r.run_id = m.run_id
                WHERE r.status = 'completed'
                  AND m.sharpe IS NOT NULL
                  AND m.fitness IS NOT NULL
                  AND m.sharpe >= ?
                  AND m.fitness >= ?
                ORDER BY r.completed_at DESC
                LIMIT ?
                """,
                (min_sharpe, min_fitness, limit),
            ).fetchall()
            return rows

    def get_recent_bucket_reference_candidates(self, *, limit: int) -> list[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    c.candidate_id,
                    c.expression_hash,
                    c.canonical_expression,
                    c.template_id,
                    c.family,
                    c.fields_json,
                    c.params_json,
                    c.settings_json,
                    r.run_id,
                    r.alpha_id,
                    r.completed_at,
                    m.sharpe,
                    m.fitness,
                    m.turnover,
                    m.submit_eligible
                FROM runs r
                JOIN candidates c
                    ON r.candidate_id = c.candidate_id
                LEFT JOIN metrics m
                    ON r.run_id = m.run_id
                WHERE r.status = 'completed'
                ORDER BY r.completed_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return rows

    def get_submitted_candidate_rows(self, *, limit: int = 300) -> list[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    c.candidate_id,
                    c.expression_hash,
                    c.canonical_expression,
                    c.template_id,
                    c.family,
                    c.fields_json,
                    c.params_json,
                    c.settings_json,
                    r.run_id,
                    r.alpha_id,
                    s.submitted_at,
                    m.sharpe,
                    m.fitness,
                    m.turnover,
                    m.submit_eligible
                FROM submissions s
                JOIN runs r
                    ON s.run_id = r.run_id
                JOIN candidates c
                    ON s.candidate_id = c.candidate_id
                LEFT JOIN metrics m
                    ON r.run_id = m.run_id
                WHERE s.submission_status IN ('submitted', 'confirmed')
                ORDER BY s.submitted_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return rows

    def get_submission_eligible_candidates(self, *, limit: int) -> list[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    c.candidate_id,
                    c.expression_hash,
                    c.canonical_expression,
                    c.template_id,
                    c.family,
                    c.fields_json,
                    c.params_json,
                    c.settings_json,
                    r.run_id,
                    r.alpha_id,
                    r.completed_at,
                    m.sharpe,
                    m.fitness,
                    m.turnover,
                    m.submit_eligible
                FROM runs r
                JOIN candidates c
                    ON r.candidate_id = c.candidate_id
                JOIN metrics m
                    ON r.run_id = m.run_id
                WHERE r.status = 'completed'
                  AND m.submit_eligible = 1
                  AND r.alpha_id IS NOT NULL
                ORDER BY r.completed_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return rows


    def get_refinement_report(self, limit: int = 250) -> list[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    c.template_id AS base_template_id,
                    c.family AS family,
                    rq.source_stage AS source_stage,
                    COUNT(*) AS queued_count,
                    AVG(rq.base_sharpe) AS avg_base_sharpe,
                    AVG(rq.base_fitness) AS avg_base_fitness,
                    AVG(rq.base_turnover) AS avg_base_turnover
                FROM refinement_queue rq
                JOIN candidates c ON rq.candidate_id = c.candidate_id
                ORDER BY rq.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return rows

    def get_submitted_alphas(self, *, limit: int = 300) -> list[sqlite3.Row]:
        return self.get_submitted_candidate_rows(limit=limit)

    def register_manual_submission(self, expression_hash: str, alpha_id: str | None = None) -> bool:
        """
        Register a manually submitted alpha (submitted via WQ UI, not AUTO_SUBMIT).
        Looks up the candidate by expression hash and creates a submission record.
        Returns True if successful, False if candidate not found.
        """
        candidate_row = self.get_candidate_by_hash(expression_hash)
        if candidate_row is None:
            return False

        candidate_id = candidate_row["candidate_id"]

        # find the most recent completed run for this candidate
        with self.connect() as conn:
            run_row = conn.execute(
                """
                SELECT run_id
                FROM runs
                WHERE candidate_id = ? AND status = 'completed'
                ORDER BY completed_at DESC
                LIMIT 1
                """,
                (candidate_id,),
            ).fetchone()

        if run_row is None:
            return False

        from models import new_id, utc_now

        self.insert_submission(
            submission_id=new_id("sub"),
            candidate_id=candidate_id,
            run_id=run_row["run_id"],
            submitted_at=utc_now(),
            submission_status="submitted",
            message="manually_registered",
        )
        return True

    def register_manual_submission_by_candidate_id(self, candidate_id: str) -> bool:
        """Register a manual submission by candidate_id directly."""
        with self.connect() as conn:
            run_row = conn.execute(
                """
                SELECT run_id
                FROM runs
                WHERE candidate_id = ? AND status = 'completed'
                ORDER BY completed_at DESC
                LIMIT 1
                """,
                (candidate_id,),
            ).fetchone()

        if run_row is None:
            return False

        from models import new_id, utc_now

        self.insert_submission(
            submission_id=new_id("sub"),
            candidate_id=candidate_id,
            run_id=run_row["run_id"],
            submitted_at=utc_now(),
            submission_status="submitted",
            message="manually_registered",
        )
        return True

    # Optuna settings optimizer queries

    def get_runs_for_expression(self, expression: str) -> list[dict]:
        """Get all completed runs for a specific expression with settings and metrics."""
        import json as _json
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT r.run_id, c.settings_json, m.sharpe, m.fitness, m.turnover
                FROM candidates c
                JOIN runs r ON c.candidate_id = r.candidate_id
                LEFT JOIN metrics m ON r.run_id = m.run_id
                WHERE c.canonical_expression = ? AND r.status = 'completed'
                ORDER BY m.fitness DESC
                LIMIT 50
                """,
                (expression,),
            ).fetchall()
        return [
            {
                "run_id": row["run_id"],
                "settings_json": _json.loads(row["settings_json"]) if row["settings_json"] else {},
                "sharpe": row["sharpe"],
                "fitness": row["fitness"],
                "turnover": row["turnover"],
            }
            for row in rows
        ]

    def get_runs_for_core_signal(self, core_signal: str) -> list[dict]:
        """Get completed runs whose expression contains the core signal."""
        import json as _json
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT r.run_id, c.settings_json, m.sharpe, m.fitness, m.turnover
                FROM candidates c
                JOIN runs r ON c.candidate_id = r.candidate_id
                LEFT JOIN metrics m ON r.run_id = m.run_id
                WHERE c.canonical_expression LIKE ? AND r.status = 'completed'
                  AND m.fitness IS NOT NULL
                ORDER BY m.fitness DESC
                LIMIT 30
                """,
                (f"%{core_signal[:40]}%",),
            ).fetchall()
        return [
            {
                "run_id": row["run_id"],
                "settings_json": _json.loads(row["settings_json"]) if row["settings_json"] else {},
                "sharpe": row["sharpe"],
                "fitness": row["fitness"],
                "turnover": row["turnover"],
            }
            for row in rows
        ]

    def get_runs_for_family(self, family: str) -> list[dict]:
        """Get top completed runs from same family for cross-pollination."""
        import json as _json
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT r.run_id, c.settings_json, m.sharpe, m.fitness, m.turnover
                FROM candidates c
                JOIN runs r ON c.candidate_id = r.candidate_id
                LEFT JOIN metrics m ON r.run_id = m.run_id
                WHERE c.family = ? AND r.status = 'completed'
                  AND m.fitness > 0.5
                ORDER BY m.fitness DESC
                LIMIT 30
                """,
                (family,),
            ).fetchall()
        return [
            {
                "run_id": row["run_id"],
                "settings_json": _json.loads(row["settings_json"]) if row["settings_json"] else {},
                "sharpe": row["sharpe"],
                "fitness": row["fitness"],
                "turnover": row["turnover"],
            }
            for row in rows
        ]

    def get_concentrated_weight_failures(self, *, limit: int = 500) -> list[str]:
        """Get canonical expressions that failed the CONCENTRATED_WEIGHT check."""
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT c.canonical_expression
                FROM metrics m
                JOIN runs r ON m.run_id = r.run_id
                JOIN candidates c ON r.candidate_id = c.candidate_id
                WHERE m.fail_reason LIKE '%CONCENTRATED_WEIGHT%'
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [row["canonical_expression"] for row in rows]

    def get_self_correlation_rejections(self, *, limit: int = 500) -> list[dict]:
        """Get candidates that were rejected by WQ for self-correlation."""
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT c.canonical_expression, c.candidate_id
                FROM submissions s
                JOIN candidates c ON s.candidate_id = c.candidate_id
                WHERE s.submission_status = 'rejected'
                  AND s.message LIKE '%SELF_CORRELATION%'
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [{"canonical_expression": row["canonical_expression"], "candidate_id": row["candidate_id"]} for row in rows]

    def insert_review_queue(self, *, candidate_id, run_id, expression, core_signal,
                            family, template_id, sharpe, fitness, turnover, settings_json):
        """Add an eligible alpha to the review queue for a manual submission decision."""
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO review_queue
                (candidate_id, run_id, expression, core_signal, family, template_id,
                 sharpe, fitness, turnover, settings_json, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (candidate_id, run_id, expression, core_signal, family, template_id,
                 sharpe, fitness, turnover, settings_json),
            )

    # bot state stubs (no-op for SQLite - team features need Supabase)

    def save_bot_state(self, status="stopped", completion_count=0,
                       interrupted_refinement_ids=None, interrupted_optuna_ids=None,
                       refinement_counters=None):
        pass  # SQLite doesn't support team features

    def get_bot_state(self):
        return None

    def heartbeat(self):
        pass

    def get_own_unconsumed_refinement_count(self):
        return 0

    def un_consume_refinement(self, candidate_id):
        pass

    def mark_runs_interrupted(self, run_ids):
        pass

    def log_activity(self, **kwargs):
        pass

    def get_all_team_submissions(self, *, limit=500):
        return []

    def update_dashboard(self, **kwargs):
        pass

    def prune_activity_log(self, max_per_owner=2000):
        pass
