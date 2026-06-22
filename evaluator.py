from __future__ import annotations

from models import Metrics, SubmissionDecision
import config


def _safe_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def extract_failed_check_name(result: dict) -> str | None:
    alpha_data = result.get("alpha_data")
    if not isinstance(alpha_data, dict):
        return None

    is_block = alpha_data.get("is")
    if not isinstance(is_block, dict):
        return None

    checks = is_block.get("checks")
    if not isinstance(checks, list):
        return None

    for check in checks:
        if not isinstance(check, dict):
            continue

        name = str(check.get("name", "")).upper()
        status = str(check.get("result", "")).upper()

        if status == "FAIL":
            return name

        if status == "PENDING" and name != "SELF_CORRELATION":
            return f"PENDING_{name}"

    return None


def parse_metrics(run_id: str, result: dict) -> Metrics:
    sharpe = _safe_float(result.get("sharpe"))
    fitness = _safe_float(result.get("fitness"))
    turnover = _safe_float(result.get("turnover"))
    returns = _safe_float(result.get("returns"))
    margin = _safe_float(result.get("margin"))
    drawdown = _safe_float(result.get("drawdown"))

    checks_passed = result.get("checks_passed")
    if checks_passed is None:
        checks_passed = result.get("is_stats_pass")

    fail_reason = None

    failed_check_name = extract_failed_check_name(result)

    # Do not silently promote unknown check state when the alpha/metrics fetch
    # failed. If metrics exist and no failed check is visible, we can still use
    # the numeric gates below; if metrics are missing, this becomes
    # missing_metrics rather than eligible.
    if checks_passed is None:
        checks_passed = failed_check_name is None

    if checks_passed is False:
        fail_reason = f"checks_failed:{failed_check_name}" if failed_check_name else "checks_failed"
    elif sharpe is None or fitness is None:
        fail_reason = "missing_metrics"
    elif sharpe < config.MIN_SHARPE:
        fail_reason = "low_sharpe"
    elif fitness < config.MIN_FITNESS:
        fail_reason = "low_fitness"
    elif turnover is not None and turnover > config.MAX_TURNOVER:
        fail_reason = "high_turnover"

    submit_eligible = fail_reason is None

    return Metrics(
        run_id=run_id,
        sharpe=sharpe,
        fitness=fitness,
        turnover=turnover,
        returns=returns,
        margin=margin,
        drawdown=drawdown,
        checks_passed=bool(checks_passed),
        submit_eligible=submit_eligible,
        fail_reason=fail_reason,
    )


def evaluate_submission(candidate_id: str, metrics: Metrics) -> SubmissionDecision:
    if not metrics.checks_passed:
        return SubmissionDecision(
            run_id=metrics.run_id,
            candidate_id=candidate_id,
            should_submit=False,
            reason=metrics.fail_reason or "checks_failed",
        )

    if metrics.submit_eligible is not True:
        return SubmissionDecision(
            run_id=metrics.run_id,
            candidate_id=candidate_id,
            should_submit=False,
            reason=metrics.fail_reason or "not_eligible",
        )

    return SubmissionDecision(
        run_id=metrics.run_id,
        candidate_id=candidate_id,
        should_submit=True,
        reason="eligible",
    )
