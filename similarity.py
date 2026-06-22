from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


def _safe_json(value, default=None):
    """Parse JSON that might already be a Python object (Supabase JSONB) or a string (SQLite)."""
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return default
    return default


FIELD_TOKENS = {
    "close",
    "returns",
    "volume",
    "cap",
    "assets",
    "sales",
    "income",
    "cash",
    "high",
    "low",
    "open",
    "vwap",
}

IGNORED_TOKENS = {
    "rank",
    "group_rank",
    "zscore",
    "scale",
    "ts_mean",
    "ts_delta",
    "ts_std_dev",
    "ts_rank",
    "trade_when",
    "abs",
    "min",
    "max",
    "log",
    "sign",
}


@dataclass
class CandidateSignature:
    candidate_id: str | None
    expression_hash: str
    canonical_expression: str
    family: str
    template_id: str
    fields: list[str]
    params: dict[str, Any]
    settings: dict[str, Any]
    expr_tokens: set[str]
    structure_tokens: set[str]
    bucket_key: str


@dataclass
class SimilarityResult:
    score: float
    reason: str
    ref_candidate_id: str | None = None
    ref_template_id: str | None = None
    ref_family: str | None = None
    ref_bucket_key: str | None = None


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _bucket_number(value: Any) -> str:
    x = _safe_float(value)
    if x is None:
        return "na"

    if x <= 3:
        return "3"
    if x <= 5:
        return "5"
    if x <= 10:
        return "10"
    if x <= 20:
        return "20"
    if x <= 40:
        return "40"
    return "60+"


def _tokenize_expression(expr: str) -> set[str]:
    raw = re.findall(r"[A-Za-z_]+", expr or "")
    return {tok for tok in raw if tok and tok not in IGNORED_TOKENS}


def _field_tokens(expr_tokens: set[str], fields: list[str]) -> set[str]:
    out = set(fields or [])
    for tok in expr_tokens:
        if tok in FIELD_TOKENS:
            out.add(tok)
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    denom = len(a | b)
    if denom == 0:
        return 0.0
    return len(a & b) / denom


def _relative_closeness(a: Any, b: Any) -> float:
    fa = _safe_float(a)
    fb = _safe_float(b)
    if fa is None or fb is None:
        return 0.0
    denom = max(abs(fa), abs(fb), 1.0)
    return max(0.0, 1.0 - abs(fa - fb) / denom)


class SimilarityEngine:
    """
    Phase-2 structural similarity engine.

    This is intentionally a first-stage proxy:
    - no fake behavioural correlation
    - no invented return-series correlation
    - uses canonical expression + params + settings + field/template structure

    Tuned version:
    - less punitive on compact template families
    - still hard-blocks exact duplicates
    - better suited for discrete parameter grids like 3/5/10/20/40/60
    """

    def signature_from_candidate(self, candidate) -> CandidateSignature:
        settings = candidate.settings.to_dict()
        expr_tokens = _tokenize_expression(candidate.canonical_expression)
        fields = _field_tokens(expr_tokens, candidate.fields)

        bucket_key = self._build_bucket_key(
            family=candidate.family,
            template_id=candidate.template_id,
            fields=sorted(fields),
            params=candidate.params,
            settings=settings,
        )

        return CandidateSignature(
            candidate_id=candidate.candidate_id,
            expression_hash=candidate.expression_hash,
            canonical_expression=candidate.canonical_expression,
            family=candidate.family,
            template_id=candidate.template_id,
            fields=sorted(fields),
            params=dict(candidate.params),
            settings=settings,
            expr_tokens=expr_tokens,
            structure_tokens=fields | {candidate.family, candidate.template_id},
            bucket_key=bucket_key,
        )

    def signature_from_row(self, row) -> CandidateSignature:
        fields = _safe_json(row["fields_json"], [])
        params = _safe_json(row["params_json"], {})
        settings = _safe_json(row["settings_json"], {})

        canonical_expression = row["canonical_expression"]
        expr_tokens = _tokenize_expression(canonical_expression)
        field_set = _field_tokens(expr_tokens, fields)

        bucket_key = self._build_bucket_key(
            family=row["family"],
            template_id=row["template_id"],
            fields=sorted(field_set),
            params=params,
            settings=settings,
        )

        return CandidateSignature(
            candidate_id=row["candidate_id"],
            expression_hash=row["expression_hash"],
            canonical_expression=canonical_expression,
            family=row["family"],
            template_id=row["template_id"],
            fields=sorted(field_set),
            params=params,
            settings=settings,
            expr_tokens=expr_tokens,
            structure_tokens=field_set | {row["family"], row["template_id"]},
            bucket_key=bucket_key,
        )

    def pair_similarity(self, a: CandidateSignature, b: CandidateSignature) -> float:
        if a.expression_hash == b.expression_hash:
            return 1.0

        score = 0.0

        expr_token_sim = _jaccard(a.expr_tokens, b.expr_tokens)
        field_sim = _jaccard(set(a.fields), set(b.fields))

        score += 0.22 * expr_token_sim
        score += 0.08 * field_sim

        if a.family == b.family:
            score += 0.06

        if a.template_id == b.template_id:
            score += 0.14

        score += 0.08 * _relative_closeness(a.params.get("n"), b.params.get("n"))
        score += 0.05 * _relative_closeness(a.params.get("m"), b.params.get("m"))

        if a.settings.get("neutralization") == b.settings.get("neutralization"):
            score += 0.02
        if a.settings.get("universe") == b.settings.get("universe"):
            score += 0.015
        if a.settings.get("delay") == b.settings.get("delay"):
            score += 0.015
        if a.settings.get("decay") == b.settings.get("decay"):
            score += 0.02

        trunc_a = _safe_float(a.settings.get("truncation"))
        trunc_b = _safe_float(b.settings.get("truncation"))
        if trunc_a is not None and trunc_b is not None:
            score += 0.015 * _relative_closeness(trunc_a, trunc_b)

        if a.bucket_key == b.bucket_key:
            score += 0.06

        return max(0.0, min(1.0, score))

    def max_similarity_against_rows(self, candidate, reference_rows: list[Any]) -> SimilarityResult:
        cand_sig = self.signature_from_candidate(candidate)

        best_score = 0.0
        best_row = None
        best_sig = None

        for row in reference_rows:
            ref_sig = self.signature_from_row(row)
            score = self.pair_similarity(cand_sig, ref_sig)
            if score > best_score:
                best_score = score
                best_row = row
                best_sig = ref_sig

        if best_row is None or best_sig is None:
            return SimilarityResult(score=0.0, reason="no_reference_set")

        reason = (
            "exact_duplicate"
            if best_score >= 0.999
            else "same_bucket"
            if cand_sig.bucket_key == best_sig.bucket_key
            else "high_structural_similarity"
        )

        return SimilarityResult(
            score=best_score,
            reason=reason,
            ref_candidate_id=best_row["candidate_id"],
            ref_template_id=best_row["template_id"],
            ref_family=best_row["family"],
            ref_bucket_key=best_sig.bucket_key,
        )

    def build_bucket_key_from_row(self, row) -> str:
        return self.signature_from_row(row).bucket_key

    def _build_bucket_key(
        self,
        *,
        family: str,
        template_id: str,
        fields: list[str],
        params: dict[str, Any],
        settings: dict[str, Any],
    ) -> str:
        field_key = "+".join(sorted(fields)) if fields else "none"
        n_key = _bucket_number(params.get("n"))
        m_key = _bucket_number(params.get("m"))
        neutralization = settings.get("neutralization", "na")
        decay = settings.get("decay", "na")
        universe = settings.get("universe", "na")

        return "|".join(
            [
                family,
                template_id,
                field_key,
                f"n={n_key}",
                f"m={m_key}",
                f"neu={neutralization}",
                f"decay={decay}",
                f"uni={universe}",
            ]
        )


def portfolio_quality_score(row) -> float:
    sharpe = _safe_float(row["sharpe"]) or 0.0
    fitness = _safe_float(row["fitness"]) or 0.0
    turnover = _safe_float(row["turnover"])

    score = 1.00 * sharpe + 0.80 * fitness

    if turnover is not None:
        if turnover > 0.70:
            score -= 0.45
        elif turnover > 0.55:
            score -= 0.20
        elif turnover < 0.08:
            score -= 0.05

    return score


class SubmissionPortfolioSelector:
    def __init__(self, similarity_engine: SimilarityEngine):
        self.similarity_engine = similarity_engine

    def select_rows(
        self,
        candidate_rows: list[Any],
        already_submitted_rows: list[Any],
        max_selected: int,
        max_pairwise_similarity: float,
    ) -> list[Any]:
        sorted_rows = sorted(candidate_rows, key=portfolio_quality_score, reverse=True)

        selected: list[Any] = []
        locked = list(already_submitted_rows)

        for row in sorted_rows:
            row_sig = self.similarity_engine.signature_from_row(row)

            blocked = False

            for ref in locked + selected:
                ref_sig = self.similarity_engine.signature_from_row(ref)
                sim = self.similarity_engine.pair_similarity(row_sig, ref_sig)
                if sim >= max_pairwise_similarity:
                    blocked = True
                    break

            if blocked:
                continue

            selected.append(row)
            if len(selected) >= max_selected:
                break

        return selected
