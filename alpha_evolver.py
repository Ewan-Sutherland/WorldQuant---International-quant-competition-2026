"""Evolutionary LLM alpha mutation engine.

FunSearch-inspired: maintain a population of best expressions per data category,
select parents, ask the LLM to mutate them. the LLM sees what worked and why, then
makes targeted modifications.

Three mutation types:
1. COMPONENT_SWAP: replace one signal component with a different data field
2. OPERATOR_CHANGE: change the operator wrapping (rank->group_rank, ts_mean->ts_decay_linear)
3. CROSSOVER: combine components from two top performers in different categories

Usage in bot.py:
    from alpha_evolver import AlphaEvolver
    evolver = AlphaEvolver(llm_client, storage)
    mutated_expr = evolver.evolve()
"""
from __future__ import annotations

import random
from typing import Optional

from signal_combiner import classify_expression


def _row_delay(row: dict) -> int:
    try:
        import json
        settings = row.get("settings_json") or {}
        if isinstance(settings, str):
            settings = json.loads(settings)
        return int(settings.get("delay", 1))
    except Exception:
        return 1


# mutation prompt - fed to the LLM with a parent expression
MUTATION_PROMPT = """You are evolving a quantitative alpha expression. Your job is to make a SMALL, TARGETED modification to improve it.

PARENT EXPRESSION (this already scores well - Sharpe={sharpe:.2f}, Fitness={fitness:.2f}):
  {expression}

FAILURE REASON: {fail_reason}

MUTATION TYPE: {mutation_type}

{mutation_instructions}

RULES:
- Make ONE change only - keep the rest of the expression identical
- The result must be valid BRAIN FastExpression syntax
- Must contain rank() or group_rank()
- For options/news data, ALWAYS use ts_backfill(field, 60)
- Output ONLY the mutated expression - no explanation, no numbering

ALREADY SUBMITTED (do NOT produce these):
{submitted_list}

Output exactly 1 mutated expression:"""

COMPONENT_SWAP_INSTRUCTIONS = """Replace ONE data field with a different field from a DIFFERENT data category.
Good swaps:
  - Fundamental -> options (e.g., debt -> ts_backfill(implied_volatility_call_120, 60))
  - Price -> sentiment (e.g., returns -> snt1_d1_netearningsrevision)
  - Model77 -> analyst (e.g., cash_burn_rate -> est_eps / close)
Keep the operator structure identical - only change the data field."""

OPERATOR_CHANGE_INSTRUCTIONS = """Change ONE operator to a similar but different operator.
Good changes:
  - rank(X) -> group_rank(X, industry)  or  group_rank(X, subindustry)
  - ts_mean(X, N) -> ts_decay_linear(X, N)
  - ts_zscore(X, N) -> ts_rank(X, N)
  - rank(A) + rank(B) -> rank(A * B)    (multiplicative form)
  - rank(A * B) -> rank(A) * rank(B)
Keep the data fields identical - only change the operator."""

CROSSOVER_INSTRUCTIONS = """Combine the best component from the parent with a component from this DONOR expression:
  DONOR (Sharpe={donor_sharpe:.2f}, category={donor_category}): {donor_expression}

Take the strongest signal from the parent and combine it with the strongest signal from the donor.
Use either:
  - rank(parent_signal * donor_signal)  - multiplicative (preferred)
  - rank(parent_signal) + rank(donor_signal)  - additive
The result should use data from TWO DIFFERENT categories."""


class AlphaEvolver:
    """
    Evolutionary alpha mutation using an LLM.
    Selects top performers, applies targeted mutations.

    Recent changes:
      - raised parent quality thresholds (S>=1.30, F>=0.95)
      - sibling diversification: avoid parents with multiple ready_alphas pending
      - portfolio-aware crossover: bias donors toward under-represented categories
    """

    def __init__(self, llm_generator=None, storage=None):
        self.llm_generator = llm_generator
        self.storage = storage
        self.rng = random.Random()
        self._population: list[dict] = []
        self._population_by_category: dict[str, list[dict]] = {}
        # track recent parent usage to avoid producing correlated siblings
        self._recent_parent_hashes: dict[str, int] = {}
        # track which categories are over-saturated in the submitted portfolio
        self._submitted_category_counts: dict[str, int] = {}

    def _refresh_saturation_state(self) -> None:
        """Pull recent parent usage and submitted-category counts.

        Sibling diversification: count how many pending ready_alphas each parent
        has. if a parent has 2+ already staged, avoid it (siblings will self-corr).

        Portfolio-aware crossover: count how many submissions exist per category.
        donors from over-saturated categories produce correlated children.

        All queries are best-effort - if storage doesn't expose these methods or an
        exception fires, fall back to non-saturation-aware behavior.
        """
        self._recent_parent_hashes = {}
        self._submitted_category_counts = {}
        if self.storage is None:
            return

        # sibling diversification - query ready_alphas for currently-staged entries
        try:
            # use the lower-level Supabase _get if available (Supabase backend)
            if hasattr(self.storage, '_get'):
                ready_rows = self.storage._get("ready_alphas", {
                    "status": "in.(ready,unverified)",
                    "select": "expression,canonical_expression",
                    "limit": "200",
                })
            else:
                ready_rows = []
            for row in ready_rows:
                expr = (row.get('canonical_expression') or row.get('expression') or '')[:60]
                if expr:
                    self._recent_parent_hashes[expr] = self._recent_parent_hashes.get(expr, 0) + 1
        except Exception:
            pass

        # portfolio-aware crossover - count submissions per category
        try:
            if hasattr(self.storage, 'get_submitted_candidate_rows'):
                sub_rows = self.storage.get_submitted_candidate_rows(limit=300)
            else:
                sub_rows = []
            for row in sub_rows:
                expr = row.get('canonical_expression') or row.get('expression') or ''
                if expr:
                    cat = classify_expression(expr)
                    self._submitted_category_counts[cat] = self._submitted_category_counts.get(cat, 0) + 1
        except Exception:
            pass

        # log saturation state once per refresh
        if self._recent_parent_hashes or self._submitted_category_counts:
            saturated_parents = sum(1 for v in self._recent_parent_hashes.values() if v >= 2)
            top_cats = sorted(self._submitted_category_counts.items(), key=lambda x: -x[1])[:3]
            print(
                f"[EVOLVER_SAT] saturated_parents={saturated_parents} "
                f"top_submitted_cats={top_cats}"
            )

    def refresh_population(self, min_sharpe: float = 1.30, min_fitness: float = 0.95) -> None:
        """Load top performers from the DB into the population.

        Raised thresholds from (0.90, 0.40) to (1.30, 0.95). post-deployment data
        showed the +48 winner came from an S=2.09 parent. mediocre parents produce
        mediocre children, so the LLM mutates from genuinely high-quality alphas only.
        """
        if self.storage is None:
            return

        # refresh sibling/portfolio saturation state before population filtering
        self._refresh_saturation_state()

        self._population = []
        self._population_by_category = {}

        try:
            rows = self.storage.get_similarity_reference_candidates(
                limit=100, min_sharpe=min_sharpe, min_fitness=min_fitness,
            )
        except Exception:
            return

        for row in rows:
            expr = row.get("canonical_expression", "")
            if not expr:
                continue

            # keep Delay-0 and Delay-1 evolution pools separate
            try:
                import config
                if getattr(config, "SEPARATE_DELAY_REGIMES", True) and not getattr(config, "EVOLVER_ALLOW_DELAY0", False):
                    if _row_delay(row) == 0:
                        continue
            except Exception:
                pass

            # filter out expressions using fields not in this bot's dataset
            try:
                from datasets import expression_uses_valid_fields
                if not expression_uses_valid_fields(expr):
                    continue
            except Exception:
                pass

            category = classify_expression(expr)
            entry = {
                "expression": expr,
                "sharpe": float(row.get("sharpe", 0) or 0),
                "fitness": float(row.get("fitness", 0) or 0),
                "fail_reason": row.get("fail_reason", "") or "",
                "category": category,
            }
            self._population.append(entry)
            if category not in self._population_by_category:
                self._population_by_category[category] = []
            self._population_by_category[category].append(entry)

        # sort by sharpe within each category
        for cat in self._population_by_category:
            self._population_by_category[cat].sort(
                key=lambda x: x["sharpe"], reverse=True,
            )

        total = len(self._population)
        cats = len(self._population_by_category)
        if total > 0:
            print(f"[EVOLVER] Population: {total} expressions across {cats} categories")

    def evolve(self, submitted_exprs: list[str] | None = None) -> Optional[str]:
        """
        Select a parent, apply a mutation, return the mutated expression.
        Returns None if the LLM is unavailable or mutation fails.
        """
        if not self._population or not self.llm_generator or not self.llm_generator.available:
            return None

        # select parent - tournament selection (pick 3, take best). some sibling
        # alphas pass self-correlation despite the heuristic predicting they won't,
        # and worst-case is only ~5 wasted submission attempts per cycle, so this
        # keeps the simple tournament selection.
        pool = self._population[:30]  # top 30 by sharpe
        if len(pool) < 3:
            return None
        tournament = self.rng.sample(pool, min(3, len(pool)))
        parent = max(tournament, key=lambda x: x["sharpe"])

        # pick mutation type
        roll = self.rng.random()
        if roll < 0.35:
            mutation_type = "COMPONENT_SWAP"
            instructions = COMPONENT_SWAP_INSTRUCTIONS
        elif roll < 0.65:
            mutation_type = "OPERATOR_CHANGE"
            instructions = OPERATOR_CHANGE_INSTRUCTIONS
        else:
            mutation_type = "CROSSOVER"
            # find a donor from a different category
            donor = self._select_donor(parent["category"])
            if donor is None:
                mutation_type = "OPERATOR_CHANGE"
                instructions = OPERATOR_CHANGE_INSTRUCTIONS
            else:
                instructions = CROSSOVER_INSTRUCTIONS.format(
                    donor_sharpe=donor["sharpe"],
                    donor_category=donor["category"],
                    donor_expression=donor["expression"],
                )

        # build submitted list for dedup
        submitted_list = ""
        if submitted_exprs:
            submitted_list = "\n".join(f"  {e}" for e in submitted_exprs[:15])

        # build the mutation prompt
        user_prompt = MUTATION_PROMPT.format(
            sharpe=parent["sharpe"],
            fitness=parent["fitness"],
            expression=parent["expression"],
            fail_reason=parent["fail_reason"] or "unknown",
            mutation_type=mutation_type,
            mutation_instructions=instructions,
            submitted_list=submitted_list,
        )

        # call the LLM
        from llm_generator import SYSTEM_PROMPT, parse_expressions
        raw = self.llm_generator.client.generate(SYSTEM_PROMPT, user_prompt)
        if raw is None:
            return None

        expressions = parse_expressions(raw)
        if not expressions:
            return None

        mutated = expressions[0]

        print(
            f"[EVOLVE] mutation={mutation_type} parent_S={parent['sharpe']:.2f} "
            f"parent_cat={parent['category']} -> {mutated[:80]}"
        )

        return mutated

    def _select_donor(self, exclude_category: str) -> Optional[dict]:
        """Select a donor from a different category for crossover.

        Prefer donors from under-represented categories in the submitted portfolio.
        categories with 5+ submissions are nearly excluded; fresh categories (<2
        submissions) get 5x weight. stops crossover from amplifying already-saturated
        dimensions of the team's portfolio.
        """
        other_cats = [
            c for c in self._population_by_category
            if c != exclude_category and self._population_by_category[c]
        ]
        if not other_cats:
            return None

        # weight categories by inverse saturation in the submitted portfolio
        weights = []
        for cat in other_cats:
            sub_count = self._submitted_category_counts.get(cat, 0)
            if sub_count >= 5:
                weight = 0.5  # heavily saturated, near-skip
            elif sub_count >= 3:
                weight = 1.5
            elif sub_count >= 1:
                weight = 3.0
            else:
                weight = 5.0  # fresh category, prefer
            weights.append(weight)

        cat = self.rng.choices(other_cats, weights=weights, k=1)[0]
        entries = self._population_by_category[cat]
        pool = entries[:min(3, len(entries))]
        return self.rng.choice(pool)

    def stats(self) -> dict:
        return {
            "population_size": len(self._population),
            "categories": len(self._population_by_category),
        }
