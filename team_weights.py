"""Team-shared weight learning.

Each bot periodically publishes its own performance stats to the team_stats
table, then reads all teammates' stats and blends them into runtime weights.

Blending logic:
  - own data ramps up: weight = min(1.0, own_sims / RAMP_SIMS)
  - team data fills the gap: weight = 1.0 - own_weight
  - dead family consensus: if 2+ teammates independently find a family dead
    (avg sharpe < 0.20 over 30+ sims each), suppress it for everyone
  - floor: never fully zero (0.05 min) so any bot can still discover something

Called from bot.py on two triggers:
  1. publish_own_stats() - every REPORT_EVERY_N_COMPLETIONS
  2. get_blended_weights() - every time family/template bias is computed
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# how many own sims before fully trusting own data over team
RAMP_SIMS = 20

# floor weight - even consensus-dead families keep this minimum
FLOOR_WEIGHT = 0.03

# hardcoded fallback when get_family_stats RPC times out, based on observed
# family stats across all bots (avg_sharpe < 0.15, submit_rate=0)
DEAD_FAMILIES_FALLBACK = {
    "relationship", "cross_sectional", "sentiment",
    "volume_flow", "fundamental_scores", "intraday",
    "risk_beta", "expanded_fundamental", "volatility",
    "social_scalar", "intraday_pattern", "options_analytics",
}

# consensus dead threshold
CONSENSUS_DEAD_WEIGHT = 0.04

# cache TTL - don't re-query team stats more than once per 5 minutes
CACHE_TTL_SECONDS = 300


class TeamWeights:
    def __init__(self, storage, owner: str):
        self.storage = storage
        self.owner = owner
        self._cache: dict[str, Any] = {}
        self._cache_time: float = 0

    # publishing own stats

    def publish_own_stats(self) -> None:
        """Write this bot's aggregated stats to team_stats table."""
        try:
            self._publish_family_stats()
            self._publish_template_stats()
            logger.info(f"[TEAM] Published own stats for {self.owner}")
        except Exception as e:
            logger.warning(f"[TEAM] Failed to publish stats: {e}")

    def _publish_family_stats(self) -> None:
        try:
            rows = self.storage._rpc("get_family_stats", {
                "run_limit": 500,
                "owner_filter": self.owner,
            })
        except Exception:
            # fallback for pre-migration Supabase (RPC doesn't accept owner_filter yet)
            rows = self.storage._rpc("get_family_stats", {"run_limit": 500})

        now = datetime.now(timezone.utc).isoformat()
        for row in rows:
            self.storage._post("team_stats", {
                "owner": self.owner,
                "stat_type": "family",
                "stat_key": row["family"],
                "n_runs": int(row.get("n_runs", 0) or 0),
                "avg_sharpe": row.get("avg_sharpe"),
                "avg_fitness": row.get("avg_fitness"),
                "avg_turnover": row.get("avg_turnover"),
                "submit_rate": row.get("submit_rate"),
                "updated_at": now,
            }, upsert=True, on_conflict="owner,stat_type,stat_key")

    def _publish_template_stats(self) -> None:
        try:
            rows = self.storage._rpc("get_template_stats", {
                "run_limit": 300,
                "owner_filter": self.owner,
            })
        except Exception:
            rows = self.storage._rpc("get_template_stats", {"run_limit": 300})

        now = datetime.now(timezone.utc).isoformat()
        for row in rows:
            self.storage._post("team_stats", {
                "owner": self.owner,
                "stat_type": "template",
                "stat_key": row["template_id"],
                "n_runs": int(row.get("n_runs", 0) or 0),
                "avg_sharpe": row.get("avg_sharpe"),
                "avg_fitness": row.get("avg_fitness"),
                "avg_turnover": row.get("avg_turnover"),
                "updated_at": now,
            }, upsert=True, on_conflict="owner,stat_type,stat_key")

    # reading team aggregate

    def _fetch_team_aggregate(self, stat_type: str) -> list[dict]:
        """Get team aggregate stats, excluding own data (to avoid double-counting)."""
        try:
            return self.storage._rpc("get_team_aggregate_stats", {
                "p_stat_type": stat_type,
                "exclude_owner": self.owner,
            })
        except Exception as e:
            logger.warning(f"[TEAM] Failed to fetch team {stat_type} stats: {e}")
            return []

    def _get_own_total_sims(self) -> int:
        """How many completed sims does this bot have?"""
        try:
            rows = self.storage._rpc("get_family_stats", {
                "run_limit": 9999,
                "owner_filter": self.owner,
            })
            return sum(int(r.get("n_runs", 0) or 0) for r in rows)
        except Exception:
            return 0

    # blended weights

    def get_blended_family_weights(self) -> dict[str, float]:
        """
        Return blended family weights combining own experience + team knowledge.

        Returns dict[family_name] -> weight_multiplier (centered at 1.0)
        """
        now = time.time()
        cache_key = "family_weights"
        if cache_key in self._cache and (now - self._cache_time) < CACHE_TTL_SECONDS:
            return self._cache[cache_key]

        own_sims = self._get_own_total_sims()
        own_trust = min(1.0, own_sims / RAMP_SIMS)
        team_trust = 1.0 - own_trust

        team_rows = self._fetch_team_aggregate("family") if team_trust > 0.01 else []
        team_data = {r["stat_key"]: r for r in team_rows}

        weights: dict[str, float] = {}

        # all known families from team data
        all_families = set(team_data.keys())

        for family in all_families:
            team_row = team_data.get(family)

            weight = 1.0  # neutral starting point

            if team_row:
                team_sharpe = float(team_row.get("weighted_avg_sharpe") or 0)
                team_submit = float(team_row.get("weighted_submit_rate") or 0)
                is_dead = bool(team_row.get("consensus_dead", False))
                total_team_sims = int(team_row.get("total_runs") or 0)
                n_contributors = int(team_row.get("n_contributors") or 0)

                if is_dead and n_contributors >= 2:
                    # consensus dead - heavily suppress but don't zero
                    team_signal = CONSENSUS_DEAD_WEIGHT
                elif total_team_sims >= 10:
                    # enough team data to form an opinion.
                    # score: sharpe contribution + submit bonus
                    team_signal = 1.0 + 0.5 * max(-1.5, min(2.0, team_sharpe))
                    if team_submit > 0.05:
                        team_signal += 0.3
                    team_signal = max(FLOOR_WEIGHT, min(3.0, team_signal))
                else:
                    team_signal = 1.0  # not enough data, stay neutral

                # blend: own side is handled by Thompson sampling in bot.py;
                # this module only injects team knowledge as a multiplier.
                weight = own_trust * 1.0 + team_trust * team_signal

            weight = max(FLOOR_WEIGHT, weight)
            weights[family] = weight

        self._cache[cache_key] = weights
        self._cache_time = now

        if weights:
            logger.info(
                f"[TEAM] Blended family weights: own_trust={own_trust:.2f}, "
                f"team_trust={team_trust:.2f}, {len(weights)} families"
            )

        return weights

    def get_blended_template_weights(self) -> dict[str, float]:
        """Same as family weights but for templates."""
        now = time.time()
        cache_key = "template_weights"
        if cache_key in self._cache and (now - self._cache_time) < CACHE_TTL_SECONDS:
            return self._cache[cache_key]

        own_sims = self._get_own_total_sims()
        own_trust = min(1.0, own_sims / RAMP_SIMS)
        team_trust = 1.0 - own_trust

        team_rows = self._fetch_team_aggregate("template") if team_trust > 0.01 else []
        team_data = {r["stat_key"]: r for r in team_rows}

        weights: dict[str, float] = {}

        for tid, row in team_data.items():
            team_sharpe = float(row.get("weighted_avg_sharpe") or 0)
            is_dead = bool(row.get("consensus_dead", False))
            total_sims = int(row.get("total_runs") or 0)

            if is_dead:
                team_signal = CONSENSUS_DEAD_WEIGHT
            elif total_sims >= 6:
                team_signal = 1.0 + 0.45 * max(-1.5, min(2.0, team_sharpe))
                team_signal = max(FLOOR_WEIGHT, min(2.5, team_signal))
            else:
                team_signal = 1.0

            weight = own_trust * 1.0 + team_trust * team_signal
            weights[tid] = max(FLOOR_WEIGHT, weight)

        self._cache[cache_key] = weights
        self._cache_time = now
        return weights

    def invalidate_cache(self) -> None:
        """Force re-fetch on next call."""
        self._cache.clear()
        self._cache_time = 0

    def get_dead_families(self) -> set[str]:
        """Return families that the team has consensus-proven dead.

        Used by the LLM generator to avoid generating expressions in dead
        families. Also includes data-blocked families.
        """
        dead = set()
        try:
            from datasets import get_blocked_families
            dead.update(get_blocked_families())
        except Exception:
            pass

        rpc_succeeded = False
        try:
            team_rows = self._fetch_team_aggregate("family")
            rpc_succeeded = True
            for row in team_rows:
                if bool(row.get("consensus_dead", False)):
                    dead.add(row["stat_key"])
                # also flag families with very low sharpe across significant sims
                total = int(row.get("total_runs") or 0)
                avg_sharpe = float(row.get("weighted_avg_sharpe") or 0)
                if total >= 15 and avg_sharpe < 0.10:
                    dead.add(row["stat_key"])
        except Exception:
            pass

        # if the RPC failed (timeout), always merge the hardcoded fallback.
        # get_blocked_families() populates dead, so checking `not dead` would
        # never fire the fallback even when the RPC timed out.
        if not rpc_succeeded:
            dead.update(DEAD_FAMILIES_FALLBACK)
            logger.info(f"[TEAM] RPC failed - using dead families fallback ({len(DEAD_FAMILIES_FALLBACK)} families)")

        return dead
