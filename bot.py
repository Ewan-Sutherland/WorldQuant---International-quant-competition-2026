from __future__ import annotations

from datetime import timedelta
import json
import re

import config
from evaluator import evaluate_submission, parse_metrics
from generator import AlphaGenerator
from llm_generator import LLMAlphaGenerator
from models import Run, new_id, utc_now
from scheduler import Scheduler
from storage import Storage
from similarity import SimilarityEngine
from universe_sweeper import UniverseSweeper
from brain_client import BrainClient, BrainAPIError

try:
    from settings_optimizer import SettingsOptimizer
    _HAS_OPTUNA = True
except ImportError:
    _HAS_OPTUNA = False


class AlphaBot:
    """
    End-of-Phase-1.5 bot:
    - keeps your current orchestration
    - keeps refinement / pruning / diversity
    - adds adaptive family weighting
    - adds adaptive template weighting
    - stays compatible with your current storage/evaluator/scheduler
    """

    def __init__(
        self,
        storage: Storage,
        client: BrainClient,
        generator: AlphaGenerator,
        scheduler: Scheduler,
    ):
        self.storage = storage
        self.client = client
        self.generator = generator
        self.scheduler = scheduler

        self.completed_runs = 0
        self.refinement_attempts_by_base: dict[str, int] = {}
        self.refinement_local_history: dict[str, list[str]] = {}
        self.core_signal_exhausted: dict[str, int] = {}  # core_signal -> exhaustion count
        self.family_template_exhausted: dict[str, int] = {}  # "family:template_id" -> exhaustion count
        self.concentrated_weight_exprs: set[str] = set()  # v5.5: canonical expressions that fail CONCENTRATED_WEIGHT
        # v5.8: Track FIELDS that cause CW when unweighted - prevents fscore waste
        self.concentrated_weight_fields: set[str] = set()
        # v6.0.1: Core signals that already passed - track COUNT, allow up to N variants
        # WQ self-correlation accepts different post-processing of same core (e.g. ts_rank vs ts_mean)
        self.passed_cores: dict[str, int] = {}  # core_signal -> number of times passed
        # v6.1: Cores that WQ has rejected for self-correlation - skip submission, not simulation
        self.rejected_cores: set[str] = set()
        # v6.2: Cores that produce negative score changes - skip further refinement
        self._score_negative_cores: set[str] = set()
        # v6.2: Track consecutive diversity skips per base to fast-exhaust
        self._diversity_skip_count: dict[str, int] = {}
        # v6.2.1: DNS circuit breaker - track consecutive poll errors per sim
        self._poll_error_count: dict[str, int] = {}
        # v6.2.1: Stall detection - track time since last eligible alpha
        self._last_eligible_time = None
        self._stall_level = 0  # escalation level 0-4
        self._sims_since_last_eligible = 0
        # v7.2.1: Idle detection - consecutive ticks with zero sim activity
        self._idle_ticks = 0
        self._last_submit_tick = 0
        # v7.2.1: LLM exhaustion cooldown timestamp
        self._llm_exhausted_until = 0.0
        # v6.0: Track refinement attempts per CORE SIGNAL to prevent same expression via different candidates
        self.refinement_attempts_by_core: dict[str, int] = {}
        # v7.2.11: Persistent dead-cores cache - skips refinement on cores that
        # already exhausted MAX_REFINEMENT_PER_CORE attempts in a prior session
        # without producing any positive score_change variant. TTL=48h.
        try:
            from dead_cores import get_cache as _get_dead_cores_cache
            self._dead_cores = _get_dead_cores_cache()
        except Exception as _exc:
            # If cache fails to load, fall back to a no-op shim so bot keeps running
            print(f"[DEAD_CORES] Init failed ({_exc!r}) - using no-op shim")
            class _NoopCache:
                def is_dead(self, core): return False
                def mark_dead(self, core): pass
                def stats(self): return {}
            self._dead_cores = _NoopCache()
        # v6.0: Track recently simulated LLM expressions to prevent duplicates
        self.llm_simulated_expressions: set[str] = set()
        self.similarity_engine = SimilarityEngine()
        # v7.2: Queue for rate-limited submissions - retry next tick instead of losing them
        self._rate_limited_queue: list[tuple] = []  # [(candidate, run), ...]
        # v7.2: Rate limit cooldown - prevent fill loop from spinning after 429
        self._rate_limit_until: float = 0.0  # timestamp until which we skip submissions
        # v7.2: Prevent duplicate completion processing (sweep + poll overlap)
        self._processed_run_ids: set[str] = set()
        # v7.2: Lock to prevent re-entrant optimization during Optuna variant testing
        self._optimizing: bool = False

        # v6.0: Optuna-based settings optimizer for near-passers
        if _HAS_OPTUNA:
            self.settings_optimizer = SettingsOptimizer(storage)
            print("[OPTUNA] Settings optimizer available")
        else:
            self.settings_optimizer = None
            print("[OPTUNA] optuna not installed - using random settings sweep")

        # v5.6: LLM-guided generation
        self.llm_generator = LLMAlphaGenerator()
        if self.llm_generator.available:
            print("[LLM] LLM generator available - will mix LLM candidates with templates")
        else:
            print("[LLM] No API keys found (GEMINI_API_KEY / GROQ_API_KEY) - template-only mode")

        # v6.1: Signal combination engine - auto-combines near-passers
        try:
            from signal_combiner import SignalCombiner
            self.signal_combiner = SignalCombiner(storage)
            self.signal_combiner.refresh_near_passers()
            self._combo_refresh_interval = 50  # refresh every 50 sims
        except Exception as exc:
            self.signal_combiner = None
            print(f"[COMBINER] Not available: {exc}")

        # v7.0: Team shared weights - blends own learning with teammates' data
        try:
            from team_weights import TeamWeights
            self.team_weights = TeamWeights(storage, owner=storage.owner)
            print(f"[TEAM] Team weights enabled for {storage.owner}")
        except Exception as exc:
            self.team_weights = None
            print(f"[TEAM] Not available: {exc}")

        # v7.0: Track active refinement IDs for graceful shutdown resume
        self._active_refinement_ids: set[str] = set()
        self.total_completions = 0
        self._total_eligible = 0
        self._total_submitted = 0
        # v7.0: Track parent->child for refinement queue consumption
        self._refinement_lineage: dict[str, str] = {}  # child_candidate_id -> parent_candidate_id

        # v6.1: Evolutionary LLM mutation - evolves top performers
        try:
            from alpha_evolver import AlphaEvolver
            self.evolver = AlphaEvolver(self.llm_generator, storage)
            self.evolver.refresh_population()
            self._evolver_refresh_interval = 50
        except Exception as exc:
            self.evolver = None
            print(f"[EVOLVER] Not available: {exc}")

        # v6.2.1: Universe sweeper - test eligible alphas on all universes
        self.universe_sweeper = UniverseSweeper(storage, client)

        # v7.2.6: Field gap miner is available but disabled by default.
        # We keep it off to refocus sims on broad template exploration instead of unused-field mining.
        if getattr(config, "ENABLE_GAP_MINER", False):
            try:
                from field_gap_miner import FieldGapMiner
                self.gap_miner = FieldGapMiner(storage, rng=self.generator.rng)
                self.gap_miner.refresh()
                self._gap_refresh_interval = 100  # Re-scan portfolio every 100 completions
            except Exception as exc:
                self.gap_miner = None
                print(f"[GAP_MINER] Not available: {exc}")
        else:
            self.gap_miner = None
            self._gap_refresh_interval = 0
            print("[GAP_MINER] Disabled - exploration mode")

        # v6.0.1: Warm-start session state from database - persists across restarts & team members
        self._warm_start_from_history()

    # Warm-start from persistent history

    def _warm_start_from_history(self):
        """
        v6.0.1: Load session state from database so knowledge persists across
        restarts and across team members sharing the same Supabase backend.
        """
        # 1. Load passed cores from ALL TEAM submitted alphas (count per core)
        # v7.0: Uses team-wide submissions so we don't duplicate teammates' alphas
        try:
            try:
                submitted_rows = self.storage.get_all_team_submissions(limit=500)
            except Exception:
                submitted_rows = self.storage.get_submitted_candidate_rows(limit=500)
            for row in submitted_rows:
                core = self._extract_core_signal(row.get("canonical_expression", ""))
                if core:
                    self.passed_cores[core] = self.passed_cores.get(core, 0) + 1
            if self.passed_cores:
                print(f"[WARM_START] Loaded {len(self.passed_cores)} passed cores from team submissions")
        except Exception as exc:
            print(f"[WARM_START] Failed to load passed cores: {exc}")

        # 2. Load concentrated weight blacklist from historical failures
        try:
            cw_exprs = self.storage.get_concentrated_weight_failures(limit=500)
            known_cw_fields = {
                "short_interest", "days_to_cover", "utilization_rate",
                "institutional_ownership", "put_call_ratio",
                "insider_", "lending_fee",
            }
            for expr in cw_exprs:
                self.concentrated_weight_exprs.add(expr)
                expr_lower = expr.lower()
                for field in known_cw_fields:
                    if field in expr_lower:
                        self.concentrated_weight_fields.add(field)
            if self.concentrated_weight_exprs:
                print(
                    f"[WARM_START] Loaded {len(self.concentrated_weight_exprs)} CW-blacklisted expressions, "
                    f"{len(self.concentrated_weight_fields)} CW-blacklisted fields"
                )
        except Exception as exc:
            print(f"[WARM_START] Failed to load CW blacklist: {exc}")

        # 3. Load cores rejected by WQ for self-correlation - skip future submissions
        try:
            rejected_rows = self.storage.get_self_correlation_rejections(limit=500)
            for row in rejected_rows:
                core = self._extract_core_signal(row.get("canonical_expression", ""))
                if core:
                    self.rejected_cores.add(core)
            if self.rejected_cores:
                print(f"[WARM_START] Loaded {len(self.rejected_cores)} self-corr rejected cores")
        except Exception as exc:
            print(f"[WARM_START] Failed to load rejected cores: {exc}")

        # 4. Restore refinement counters + swept keys from last shutdown
        #    MUST happen before sweep queue loading so _swept is complete
        try:
            bot_state = self.storage.get_bot_state()
            if bot_state:
                snapshot = bot_state.get("config_snapshot")
                if snapshot:
                    import json as _json
                    counters = _json.loads(snapshot) if isinstance(snapshot, str) else (snapshot or {})
                    if counters.get("refinement_attempts_by_base"):
                        self.refinement_attempts_by_base = counters["refinement_attempts_by_base"]
                    if counters.get("refinement_attempts_by_core"):
                        self.refinement_attempts_by_core = counters["refinement_attempts_by_core"]
                    if counters.get("core_signal_exhausted"):
                        self.core_signal_exhausted = counters["core_signal_exhausted"]
                    if counters.get("family_template_exhausted"):
                        self.family_template_exhausted = counters["family_template_exhausted"]
                    # v7.2.1: Do NOT restore score_negative_cores.
                    # Portfolio shifts with each submission, so blocks from
                    # previous sessions are stale. A core that scored -30 last
                    # week might score +40 now. Let them accumulate fresh
                    # during this session only.
                    if counters.get("score_negative_cores"):
                        stale_count = len(counters["score_negative_cores"])
                        print(f"[WARM_START] Skipped {stale_count} stale score-blocked cores (portfolio has shifted)")
                    if counters.get("swept_keys") and hasattr(self, "universe_sweeper"):
                        prev_swept = len(self.universe_sweeper._swept)
                        self.universe_sweeper._swept.update(counters["swept_keys"])
                        new_swept = len(self.universe_sweeper._swept) - prev_swept
                        if new_swept:
                            print(f"[WARM_START] Restored {new_swept} swept pairs from last session")
                    # v7.2: Restore category rotation state so bot doesn't re-explore same categories
                    if counters.get("category_usage") and hasattr(self, "generator"):
                        saved_usage = counters["category_usage"]
                        for cat, count in saved_usage.items():
                            if cat in self.generator._category_usage:
                                self.generator._category_usage[cat] = count
                        self.generator._generation_count = counters.get("generation_count", 0)
                        print(f"[WARM_START] Restored category rotation: {sum(saved_usage.values())} total picks across {len(saved_usage)} categories")
                    # v7.2: Restore epoch engine state
                    if counters.get("epoch_state") and hasattr(self.generator, "restore_epoch_state"):
                        self.generator.restore_epoch_state(counters["epoch_state"])
                    # v7.2: Restore cached stats to avoid querying 28K rows on restart
                    if counters.get("family_stats_cache"):
                        self._family_stats_cache = counters["family_stats_cache"]
                        import time as _t; self._family_stats_cache_time = _t.time()
                        print(f"[WARM_START] Restored cached family stats ({len(self._family_stats_cache)} families)")
                    if counters.get("template_stats_cache"):
                        self._template_stats_cache = counters["template_stats_cache"]
                        import time as _t; self._template_stats_cache_time = _t.time()
                        print(f"[WARM_START] Restored cached template stats ({len(self._template_stats_cache)} templates)")
                    total_restored = sum(len(v) for v in counters.values() if isinstance(v, dict))
                    n_blocked = len(counters.get("score_negative_cores", []))
                    if total_restored or n_blocked:
                        print(f"[WARM_START] Restored {total_restored} refinement counter entries"
                              f"{f', {n_blocked} blocked cores' if n_blocked else ''} from last session")
        except Exception as exc:
            print(f"[WARM_START] Failed to restore refinement counters: {exc}")

        # 5. Load already-swept expression:universe pairs + queue new sweeps
        #    Now _swept has both submitted keys AND auto-saved keys, so queue_sweep
        #    won't re-queue previously swept (but not submitted) combos
        try:
            submitted_rows = self.storage.get_submitted_candidate_rows(limit=500)
            self.universe_sweeper.load_already_swept(submitted_rows)
            # Also queue sweeps for any submitted alphas that haven't been swept yet
            for row in submitted_rows:
                # RPC returns canonical_expression, not expression
                expr = row.get("canonical_expression", "") or row.get("expression", "")
                settings_json = row.get("settings_json", "{}")
                if isinstance(settings_json, str):
                    import json as _json
                    try:
                        settings = _json.loads(settings_json)
                    except (ValueError, TypeError):
                        settings = {}
                else:
                    settings = settings_json or {}
                if expr and settings:
                    self.universe_sweeper.queue_sweep(
                        expression=expr,
                        settings=settings,
                        family=row.get("family", ""),
                        template_id=row.get("template_id", ""),
                        alpha_id=row.get("alpha_id", ""),
                    )
        except Exception as exc:
            print(f"[WARM_START] Failed to init universe sweeper: {exc}")

    # Main loop

    def tick(self) -> None:
        self.client.ensure_session()
        self._poll_running()
        self._check_stall()   # v6.2.1: stall detection
        self._check_idle()    # v7.2.1: idle detection (no work submitted for N ticks)
        self._maybe_run_submit_pipeline()  # v7.0: scheduled auto-submission
        self._fill_capacity()

        # v7.2.1: Periodic stale-sim timeout sweep - every 20 ticks (~5 min)
        # Prevents one stuck sim from holding a scheduler slot indefinitely.
        if getattr(self, "_tick_count", 0) % 20 == 19:
            try:
                self.mark_stale_runs_timed_out()
            except Exception as exc:
                print(f"[STALE_SWEEP_ERROR] {exc}")

        # v7.2: Periodic tick confirmation (every 20 ticks)
        self._tick_count = getattr(self, "_tick_count", 0) + 1
        if self._tick_count % 20 == 0:
            from datetime import datetime, timezone
            print(f"[TICK] #{self._tick_count} at {datetime.now(timezone.utc).strftime('%H:%M UTC')}")

    def _maybe_run_submit_pipeline(self) -> None:
        """v7.0: Run submission pipeline if it's this bot's scheduled window."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)

        # Only run once per window - guard uses "hour:ran" key so we keep
        # checking within the scheduled hour until minute threshold is met
        submit_key = f"{now.hour}:done"
        if hasattr(self, "_last_submit_key") and self._last_submit_key == submit_key:
            return

        try:
            from submit_pipeline import should_submit_now, SubmitPipeline

            if should_submit_now(self.storage.owner):
                self._last_submit_key = submit_key  # Lock out rest of this hour

                # v7.2: Use coordinated pipeline if this bot participates
                coordinated_owners = getattr(config, "COORDINATED_SUBMIT_OWNERS", [])
                if self.storage.owner in coordinated_owners:
                    print(f"\n[SUBMIT_PIPELINE] Coordinated submission window - starting...")
                    from coordinated_submit import CoordinatedSubmitPipeline
                    pipeline = CoordinatedSubmitPipeline(self.storage, self.client, config)
                    result = pipeline.run()
                    print(f"[SUBMIT_PIPELINE] Coordinated done: {result}")
                else:
                    # Non-coordinated bot (Tom/Luca) - use old pipeline
                    print(f"\n[SUBMIT_PIPELINE] Scheduled submission window - starting pipeline...")
                    pipeline = SubmitPipeline(self.storage, self.client, config)
                    result = pipeline.run()
                    print(f"[SUBMIT_PIPELINE] Done: {result}")

                # v7.2: Coordinator checks teammate scores (Tom/Luca) after coordinated submission
                if getattr(config, "CHECK_TEAMMATE_SCORES", False):
                    teammates = getattr(config, "TEAMMATE_OWNERS", [])
                    if teammates:
                        try:
                            from submit_pipeline import TeammateScoreChecker
                            checker = TeammateScoreChecker(self.storage, self.client, config)
                            tm_result = checker.run(teammates)
                            print(f"[TEAMMATE_CHECK] Done: {tm_result}")
                        except Exception as tm_exc:
                            print(f"[TEAMMATE_CHECK_ERROR] {tm_exc}")
            else:
                pass  # Not yet time - keep checking each tick until minute threshold
        except Exception as exc:
            self._last_submit_key = submit_key  # Lock out to prevent crash loop
            print(f"[SUBMIT_PIPELINE_ERROR] {exc}")
            import traceback
            traceback.print_exc()

    # v6.2.1: Stall detection + escalating recovery

    def _check_stall(self) -> None:
        """
        Detect when the bot is stalled (no eligible alphas for too long)
        and apply escalating recovery actions.

        Level 0: Normal operation
        Level 1: After 100 sims with no eligible -> boost LLM temperature, log warning
        Level 2: After 200 sims -> force template rotation to least-explored families
        Level 3: After 400 sims -> reset to exploration-heavy mode
        """
        if self._sims_since_last_eligible < 100:
            return

        new_level = 0
        if self._sims_since_last_eligible >= 400:
            new_level = 3
        elif self._sims_since_last_eligible >= 200:
            new_level = 2
        elif self._sims_since_last_eligible >= 100:
            new_level = 1

        if new_level > self._stall_level:
            self._stall_level = new_level
            print(f"[STALL_DETECTED] level={new_level} sims_since_eligible={self._sims_since_last_eligible}")

            if new_level == 1:
                # Boost LLM generation probability
                if self.llm_generator and self.llm_generator.available:
                    print("[STALL_RECOVERY_L1] Boosting LLM temperature for exploration")

            elif new_level == 2:
                # Force refresh of combiners and evolver to find new material
                if self.signal_combiner:
                    try:
                        self.signal_combiner.refresh_near_passers()
                        print("[STALL_RECOVERY_L2] Refreshed signal combiner near-passers")
                    except Exception:
                        pass
                if self.evolver:
                    try:
                        self.evolver.refresh_population()
                        print("[STALL_RECOVERY_L2] Refreshed evolver population")
                    except Exception:
                        pass

            elif new_level == 3:
                # Nuclear option - reset stall counter to avoid infinite escalation
                print("[STALL_RECOVERY_L3] Full exploration reset - clearing template exhaustion")
                self.family_template_exhausted.clear()
                self.core_signal_exhausted.clear()

    # v7.2.1: Idle detection - handles the case where the main loop is
    # ticking but nothing is being submitted (LLM exhausted + refinement
    # queue empty + combo gen producing nothing). Different from stall
    # detection which is keyed on sims_since_last_eligible (that counter
    # doesn't advance when no sims are being run at all).

    def _check_idle(self) -> None:
        import time as _time
        # If scheduler has active sims, not idle
        if self.scheduler.active_count() > 0:
            self._idle_ticks = 0
            return
        # If we're in a rate-limit cooldown, not considered idle
        if _time.time() < self._rate_limit_until:
            self._idle_ticks = 0
            return

        self._idle_ticks += 1

        # Fire recovery every 5 idle ticks (~ 5xPOLL_INTERVAL, ~75s-5min depending on config)
        if self._idle_ticks > 0 and self._idle_ticks % 5 == 0:
            print(f"[IDLE_DETECTED] {self._idle_ticks} ticks with no active sims - forcing template generation")
            try:
                # Force a capacity fill pass that bypasses LLM (if exhausted)
                # _fill_capacity will already be called after this in the tick,
                # but we also nudge the generator to cycle families.
                if hasattr(self.generator, "_category_usage"):
                    # Reset category rotation to encourage fresh picks
                    self.generator._generation_count = 0
                # Also un-exhaust the template pool so we can re-try stuff
                if self._idle_ticks >= 15:
                    self.family_template_exhausted.clear()
                    print("[IDLE_RECOVERY] Cleared family_template_exhausted")
                if self._idle_ticks >= 30:
                    # Nuclear - clear core_signal_exhausted too
                    self.core_signal_exhausted.clear()
                    print("[IDLE_RECOVERY] Cleared core_signal_exhausted (deep idle)")
            except Exception as exc:
                print(f"[IDLE_RECOVERY_ERROR] {exc}")

    # Polling

    def _poll_running(self) -> None:
        for sim_id, run_id in list(self.scheduler.active_items()):
            try:
                result = self.client.poll_simulation(sim_id)
                # v6.2.1: Reset error counter on successful poll
                self._poll_error_count.pop(sim_id, None)
            except BrainAPIError as exc:
                # v6.2.1: DNS circuit breaker - mark timed_out after 20 consecutive failures
                self._poll_error_count[sim_id] = self._poll_error_count.get(sim_id, 0) + 1
                if self._poll_error_count[sim_id] >= 20:
                    self.scheduler.remove(sim_id)
                    self.storage.update_run(
                        run_id, status="timed_out", completed_at=utc_now(),
                        error_message=f"DNS circuit breaker: {self._poll_error_count[sim_id]} consecutive poll failures",
                    )
                    print(f"[DNS_CIRCUIT_BREAK] run_id={run_id} sim_id={sim_id} after {self._poll_error_count[sim_id]} failures")
                    self._poll_error_count.pop(sim_id, None)
                else:
                    print(f"[POLL_ERROR] sim_id={sim_id} run_id={run_id} error={exc}")
                continue
            except Exception as exc:
                self._poll_error_count[sim_id] = self._poll_error_count.get(sim_id, 0) + 1
                if self._poll_error_count[sim_id] >= 20:
                    self.scheduler.remove(sim_id)
                    self.storage.update_run(
                        run_id, status="timed_out", completed_at=utc_now(),
                        error_message=f"DNS circuit breaker: {self._poll_error_count[sim_id]} consecutive errors",
                    )
                    print(f"[DNS_CIRCUIT_BREAK] run_id={run_id} sim_id={sim_id} after {self._poll_error_count[sim_id]} failures")
                    self._poll_error_count.pop(sim_id, None)
                else:
                    print(f"[POLL_UNEXPECTED] sim_id={sim_id} run_id={run_id} error={exc}")
                continue

            status = result.get("status", "running")

            if status in {"submitted", "running"}:
                # v7.0: Removed update_run(status="running") here - was writing to
                # Supabase every tick for every active sim just to confirm "still running".
                # Status is already "running" from when the sim was submitted.
                continue

            self.scheduler.remove(sim_id)
            self._rate_limit_until = 0.0  # v7.2: clear cooldown - slot freed

            # v7.2: Skip if already processed (prevents duplicate optimize from sweep+poll overlap)
            if run_id in self._processed_run_ids:
                continue
            self._processed_run_ids.add(run_id)

            if status == "completed":
                self._handle_completed(run_id, result)

            elif status in {"failed", "fail", "error"}:
                error_message = result.get("error_message", f"Simulation failed with status={status}")
                self.storage.update_run(
                    run_id,
                    status="failed",
                    completed_at=utc_now(),
                    error_message=error_message,
                    raw_result=result,
                )
                print(f"[FAILED] run_id={run_id} sim_id={sim_id} error={error_message}")

            elif status == "timed_out":
                self.storage.update_run(
                    run_id,
                    status="timed_out",
                    completed_at=utc_now(),
                    error_message=result.get("error_message", "Timed out"),
                    raw_result=result,
                )
                print(f"[TIMED_OUT] run_id={run_id} sim_id={sim_id}")

            else:
                self.storage.update_run(
                    run_id,
                    status=status,
                    completed_at=utc_now(),
                    raw_result=result,
                )
                print(f"[UNKNOWN_TERMINAL_STATUS] run_id={run_id} sim_id={sim_id} status={status}")

    # Completion / refinement / submission

    def _handle_completed(self, run_id: str, result: dict) -> None:
        # v5.9.1: Extract alpha_id and store it - needed for submission flow
        alpha_id = (
            result.get("alpha_id")
            or result.get("raw", {}).get("alpha_id")
            or result.get("raw", {}).get("id")
            or result.get("raw", {}).get("alpha")
        )

        update_kwargs = {
            "status": "completed",
            "completed_at": utc_now(),
            "raw_result": result,
        }
        if alpha_id:
            update_kwargs["alpha_id"] = alpha_id

        self.storage.update_run(run_id, **update_kwargs)

        run_row = self.storage.get_run_by_id(run_id)
        if run_row is None:
            print(f"[WARN] completed run not found in DB: run_id={run_id}")
            return

        candidate_id = run_row["candidate_id"]

        metrics = parse_metrics(run_id, result)

        # v7.2.10/v7.2.11: Per-family eligibility override for untapped_* families.
        # parse_metrics uses global config.MIN_SHARPE (1.40) which is too strict
        # for untapped families whose fields are inherently noisier.
        #
        # v7.2.11: Bug fix - original code only matched bot-side fail_reasons
        # (lowercase: "low_sharpe", "low_fitness"), but most untapped sims fail
        # at WQ-side checks instead and produce uppercase prefixed reasons like
        # "checks_failed:LOW_SHARPE". Yesterday's logs showed 2,261 of those vs
        # only 4 bot-side failures, which is why FAMILY_ELIGIBILITY_OVERRIDE
        # fired 0 times. Now we accept both variants.
        #
        # We deliberately do NOT override these gates which represent real
        # quality issues:
        #   - LOW_SUB_UNIVERSE_SHARPE (alpha doesn't work in sub-universes)
        #   - CONCENTRATED_WEIGHT (alpha takes huge positions in few stocks)
        #   - HIGH_DRAWDOWN, HIGH_LEVERAGE, etc.
        try:
            cand_row_for_family = self.storage.get_candidate_by_id(candidate_id)
            cand_family = (cand_row_for_family or {}).get("family", "") if cand_row_for_family else ""
        except Exception:
            cand_family = ""
        fam_min_sharpe = getattr(config, "MIN_SHARPE_BY_FAMILY", {}).get(cand_family)
        fam_min_fitness = getattr(config, "MIN_FITNESS_BY_FAMILY", {}).get(cand_family)

        # v7.2.11: Match both lowercase (bot-side) and uppercase-prefixed (WQ-side) variants
        OVERRIDABLE_FAIL_REASONS = (
            "low_sharpe", "low_fitness", "high_turnover",                      # bot-side
            "checks_failed:LOW_SHARPE",                                         # WQ-side: Sharpe < 1.25
            "checks_failed:LOW_FITNESS",                                        # WQ-side: Fitness < 1.0
            "checks_failed:HIGH_TURNOVER",                                      # WQ-side: Turnover > 0.7
        )
        # NOTE: when fail_reason is "checks_failed:LOW_SHARPE", metrics.checks_passed
        # is False - so the original `metrics.checks_passed` requirement would block
        # the override. We DROP that requirement when fail_reason is one of the
        # overridable WQ-side variants, but only for those specific failures.
        is_overridable_failure = (
            metrics.fail_reason is not None
            and metrics.fail_reason in OVERRIDABLE_FAIL_REASONS
        )
        # checks_passed must be True OR the only thing that failed was an
        # overridable metric gate (not a fundamental issue like CONCENTRATED_WEIGHT)
        checks_ok_for_override = metrics.checks_passed or is_overridable_failure

        if (
            fam_min_sharpe is not None
            and metrics.sharpe is not None
            and metrics.sharpe >= fam_min_sharpe
            and metrics.fitness is not None
            and (fam_min_fitness is None or metrics.fitness >= fam_min_fitness)
            and checks_ok_for_override
            and is_overridable_failure
        ):
            print(
                f"[FAMILY_ELIGIBILITY_OVERRIDE] family={cand_family} "
                f"S={metrics.sharpe:.2f} F={metrics.fitness:.2f} "
                f"(was: {metrics.fail_reason}; now eligible via family threshold "
                f"S>={fam_min_sharpe}/F>={fam_min_fitness})"
            )
            metrics.fail_reason = None
            metrics.submit_eligible = True

        self.storage.insert_metrics(metrics)

        # v5.5: Track expressions that fail CONCENTRATED_WEIGHT
        # This is an expression-level failure (data coverage), not settings-level.
        # Blacklisting prevents the 34x identical sim waste from v5.4.
        if metrics.fail_reason and "CONCENTRATED_WEIGHT" in metrics.fail_reason.upper():
            candidate_row = self.storage.get_candidate_by_id(candidate_id)
            if candidate_row:
                cw_expr = candidate_row["canonical_expression"]
                if cw_expr not in self.concentrated_weight_exprs:
                    self.concentrated_weight_exprs.add(cw_expr)
                    print(
                        f"[CW_BLACKLIST] expr={cw_expr} "
                        f"total_blacklisted={len(self.concentrated_weight_exprs)}"
                    )
                # v5.8: Extract fields that cause CW when unweighted
                # If expression uses fscore/derivative fields WITHOUT rank(cap)/rank(adv20), flag the field
                cw_expr_lower = cw_expr.lower()
                _CW_RISK_FIELDS = [
                    "fscore_bfl_value", "fscore_bfl_momentum", "fscore_bfl_quality",
                    "fscore_bfl_growth", "fscore_bfl_profitability", "fscore_bfl_total",
                    "fscore_bfl_surface", "fscore_bfl_surface_accel",
                    "fscore_value", "fscore_momentum", "fscore_quality", "fscore_growth",
                    "cashflow_efficiency_rank_derivative", "composite_factor_score_derivative",
                    "earnings_certainty_rank_derivative", "growth_potential_rank_derivative",
                    "analyst_revision_rank_derivative", "relative_valuation_rank_derivative",
                ]
                has_liquidity_weight = "rank(cap)" in cw_expr_lower or "rank(adv20)" in cw_expr_lower or "rank(adv" in cw_expr_lower
                if not has_liquidity_weight:
                    for field in _CW_RISK_FIELDS:
                        if field in cw_expr_lower and field not in self.concentrated_weight_fields:
                            self.concentrated_weight_fields.add(field)
                            print(
                                f"[CW_FIELD_BLACKLIST] field={field} - unweighted use causes CW "
                                f"total_fields_blocked={len(self.concentrated_weight_fields)}"
                            )

        # v5.6.1: Record LLM expression failures for feedback
        if self.llm_generator.available and metrics.sharpe is not None and metrics.sharpe < 0.5:
            candidate_row = self.storage.get_candidate_by_id(candidate_id)
            if candidate_row and str(candidate_row.get("template_id", "")).startswith("llm_"):
                error_desc = metrics.fail_reason or f"low_sharpe_{metrics.sharpe:.2f}"
                self.llm_generator.record_failure(
                    expression=candidate_row.get("canonical_expression", ""),
                    error=error_desc,
                )

        decision = evaluate_submission(candidate_id, metrics)
        try:
            self._maybe_queue_refinement(candidate_id, run_id, metrics)
        except Exception as exc:
            print(f"[REFINEMENT_QUEUE_ERROR] {exc}")

        self.completed_runs += 1
        self.total_completions += 1
        # v6.2.1: Stall detection tracking
        self._sims_since_last_eligible += 1
        if decision.should_submit:
            self._total_eligible += 1
            self._last_eligible_time = utc_now()
            self._sims_since_last_eligible = 0
            if self._stall_level > 0:
                print(f"[STALL_RECOVERED] level was {self._stall_level}, resetting")
                self._stall_level = 0
            # v7.2: Notify epoch engine of eligible alpha
            try:
                fam = candidate_row.get("family", "")
                self.generator.notify_eligible(fam)
            except Exception:
                pass
        elif metrics.sharpe is not None and metrics.sharpe >= 1.0:
            # v7.2.1: Near-passer - not eligible but promising enough to prevent
            # premature epoch skip. These are refinement-worthy candidates.
            try:
                fam = candidate_row.get("family", "")
                if hasattr(self.generator, "notify_near_passer"):
                    self.generator.notify_near_passer(fam, metrics.sharpe)
            except Exception:
                pass

        sharpe_str = "None" if metrics.sharpe is None else f"{metrics.sharpe:.3f}"
        fitness_str = "None" if metrics.fitness is None else f"{metrics.fitness:.3f}"
        turnover_str = "None" if metrics.turnover is None else f"{metrics.turnover:.3f}"

        print(
            f"[COMPLETED] run_id={run_id} "
            f"sharpe={sharpe_str} fitness={fitness_str} turnover={turnover_str} "
            f"eligible={decision.should_submit} reason={decision.reason}"
        )

        # v7.0: Log to bot_activity for team monitoring
        try:
            cand_row = self.storage.get_candidate_by_id(candidate_id)
            if cand_row:
                self.storage.log_activity(
                    family=cand_row.get("family", ""),
                    template_id=cand_row.get("template_id", ""),
                    expression_short=cand_row.get("canonical_expression", "")[:80],
                    sharpe=metrics.sharpe,
                    fitness=metrics.fitness,
                    turnover=metrics.turnover,
                    eligible=decision.should_submit,
                    fail_reason=decision.reason if not decision.should_submit else None,
                )
        except Exception:
            pass  # Never crash over logging

        # When eligible, submit immediately - let WQ's server-side self-correlation
        # check be the judge. v5.4 blocked 6 eligible alphas that may have passed.
        # The data-category proxy was wrong - cost us real submissions.
        if decision.should_submit:
            if self._optimizing:
                print(f"[OPTIMIZE_DEFER] run_id={run_id} - already optimizing, will be swept later")
            else:
                try:
                    self._optimize_and_submit(candidate_id, run_id, result, metrics)
                except Exception as exc:
                    print(f"[OPTIMIZE_ERROR] run_id={run_id} error={exc}")
                    import traceback
                    traceback.print_exc()

        if self.completed_runs % config.REPORT_EVERY_N_COMPLETIONS == 0:
            self._print_progress_report()
            # v7.0: Publish own stats to team_stats table for teammate learning
            if self.team_weights:
                try:
                    self.team_weights.publish_own_stats()
                    self.team_weights.invalidate_cache()
                except Exception as exc:
                    print(f"[TEAM_PUBLISH_ERROR] {exc}")
            # v7.0: Update dashboard + prune old activity rows
            try:
                self.storage.update_dashboard(
                    total_sims=self.total_completions,
                    total_eligible=getattr(self, '_total_eligible', 0),
                    total_submitted=getattr(self, '_total_submitted', 0),
                    sims_since_eligible=self._sims_since_last_eligible,
                    stall_level=self._stall_level,
                )
            except Exception:
                pass
            # Prune activity log every 10 report cycles (~500 completions)
            if self.completed_runs % (config.REPORT_EVERY_N_COMPLETIONS * 10) == 0:
                try:
                    self.storage.prune_activity_log()
                except Exception:
                    pass

            # v7.1: Auto-save state every report cycle to survive hard kills
            try:
                counters = {
                    "refinement_attempts_by_base": getattr(self, "refinement_attempts_by_base", {}),
                    "refinement_attempts_by_core": getattr(self, "refinement_attempts_by_core", {}),
                    "core_signal_exhausted": getattr(self, "core_signal_exhausted", {}),
                    "family_template_exhausted": getattr(self, "family_template_exhausted", {}),
                    "score_negative_cores": list(getattr(self, "_score_negative_cores", set())),
                    "swept_keys": list(getattr(self.universe_sweeper, "_swept", set())) if hasattr(self, "universe_sweeper") else [],
                    # v7.2: Persist category rotation state across restarts
                    "category_usage": dict(getattr(self.generator, "_category_usage", {})),
                    "generation_count": getattr(self.generator, "_generation_count", 0),
                    # v7.2: Persist epoch engine state
                    "epoch_state": self.generator.get_epoch_state() if hasattr(self.generator, "get_epoch_state") else {},
                    # v7.2: Cache stats to avoid querying 28K rows on restart
                    "family_stats_cache": getattr(self, "_family_stats_cache", {}),
                    "template_stats_cache": getattr(self, "_template_stats_cache", {}),
                }
                self.storage.save_bot_state(
                    status="running",
                    completion_count=self.total_completions,
                    interrupted_refinement_ids=[],
                    refinement_counters=counters,
                )
            except Exception:
                pass  # Non-critical - don't crash the bot for a save failure

    def _maybe_queue_refinement(self, candidate_id: str, run_id: str, metrics) -> None:
        sharpe = metrics.sharpe
        fitness = metrics.fitness
        turnover = metrics.turnover

        if sharpe is None or fitness is None:
            return

        # v6.2: Don't queue refinement for cores already rejected by WQ self-correlation
        # or cores that produce negative score changes
        # v6.2.1: EXCEPT sweep candidates - different universes have different correlations
        candidate_row_check = self.storage.get_candidate_by_id(candidate_id)
        if candidate_row_check:
            is_sweep = str(candidate_row_check.get("template_id", "")).startswith("sweep_")
            core = self._extract_core_signal(candidate_row_check.get("canonical_expression", ""))
            # v7.2.7: Don't block d=0 candidates based on d=1 historical rejections.
            # rejected_cores/score_negative_cores are populated from team submissions
            # which are predominantly d=1, and d=0 lives in a separate self-corr space
            # with a smaller portfolio. Letting d=0 candidates through means we might
            # waste 1 sim if it also fails - but missing a potential d=0 alpha that
            # would have passed costs much more.
            try:
                _settings_str = candidate_row_check.get("settings_json", "{}")
                _settings = _json.loads(_settings_str) if isinstance(_settings_str, str) else (_settings_str or {})
                _is_d0 = int(_settings.get("delay", 1)) == 0
            except Exception:
                _is_d0 = False
            if core and core in self.rejected_cores and not is_sweep and not _is_d0:
                return
            if core and core in self._score_negative_cores and not is_sweep and not _is_d0:
                return

        # v6.1: Eligible alphas get settings-only refinement to find optimal version
        # for merged performance (lower turnover, higher Sharpe, better drawdown ratio)
        if metrics.submit_eligible:
            priority = sharpe + fitness
            self.storage.add_refinement_candidate(
                candidate_id=candidate_id,
                run_id=run_id,
                priority=priority,
                reason="eligible_optimize",
                created_at=utc_now(),
                source_stage="optimize",
                base_sharpe=sharpe,
                base_fitness=fitness,
                base_turnover=turnover,
            )
            print(
                f"[QUEUED_OPTIMIZE] run_id={run_id} candidate_id={candidate_id} "
                f"S={sharpe:.2f} F={fitness:.2f} - refining settings for merged performance"
            )
            return

        min_refinement_sharpe = getattr(config, "MIN_REFINEMENT_SHARPE", 1.20)
        if sharpe < min_refinement_sharpe:
            return

        # v7.2.6: d=0 alphas need S>=2.0 to actually submit on WQ. The refinement
        # queue itself does settings sweeps that can lift Sharpe by 0.3-0.5, so
        # accept d=0 candidates from S>=1.50 - they have a real chance to refine
        # up into the submittable range. Below 1.50 the gap is too big.
        # IMPORTANT: this only affects d=0 candidates. d=1 still uses the standard
        # MIN_REFINEMENT_SHARPE (1.15).
        try:
            settings_for_d0 = result.get("settings", {})
            if isinstance(settings_for_d0, str):
                import json as _json_d0
                settings_for_d0 = _json_d0.loads(settings_for_d0)
            cand_is_d0 = int(settings_for_d0.get("delay", 1)) == 0
        except Exception:
            cand_is_d0 = False

        if cand_is_d0 and sharpe < 1.50:
            print(f"[D0_REFINE_SKIP] S={sharpe:.2f} < 1.50 (d0 refinement floor) - too far from d0 submission threshold 2.0")
            return

        # v7.1: Block extreme-turnover expressions from refinement queue
        # Combos with turnover=1.0 produce inflated Sharpe (S=23+) but collapse
        # when any holding period is forced. Refining them wastes ~12 sims each.
        if turnover is not None and turnover >= 0.95:
            print(f"[TURNOVER_BLOCK] S={sharpe:.1f} T={turnover:.3f} - skipping refinement (turnover too high)")
            return

        # v7.2: Block CW-blacklisted expressions from refinement queue
        # CW is expression-level - changing settings won't fix it, wastes 3 sim slots
        candidate_row_cw = self.storage.get_candidate_by_id(candidate_id)
        if candidate_row_cw:
            canon = candidate_row_cw.get("canonical_expression", "")
            if canon and canon in self.concentrated_weight_exprs:
                return  # Silently skip - CW is unfixable via settings

        # Check if this core signal has been exhausted too many times
        # Prevents the opt_01 problem: 33 different candidates for the same core signal
        # each getting 7 refinement attempts = 231 wasted sims
        max_core_exhaustions = getattr(config, "MAX_CORE_SIGNAL_EXHAUSTIONS", 3)
        max_ft_exhaustions = getattr(config, "MAX_FAMILY_TEMPLATE_EXHAUSTIONS", 5)
        candidate_row = self.storage.get_candidate_by_id(candidate_id)
        if candidate_row:
            core = self._extract_core_signal(candidate_row.get("canonical_expression", ""))
            if core and self.core_signal_exhausted.get(core, 0) >= max_core_exhaustions:
                return  # Silently skip - this core signal has been tried enough

            # Check family+template exhaustion (catches cs_02 problem)
            ft_key = f"{candidate_row.get('family', '')}:{candidate_row.get('template_id', '')}"
            if self.family_template_exhausted.get(ft_key, 0) >= max_ft_exhaustions:
                return  # This family+template combo has been exhausted too many times

        source_stage = None
        priority = None

        if sharpe >= config.NEAR_PASSER_MIN_SHARPE and fitness >= config.NEAR_PASSER_MIN_FITNESS:
            priority = float(sharpe) + float(fitness)
            if turnover is not None:
                priority -= max(0.0, turnover - config.NEAR_PASSER_MAX_TURNOVER)
            source_stage = "near_passer"

        elif sharpe >= config.FRONTIER_MIN_SHARPE and fitness >= config.FRONTIER_MIN_FITNESS:
            priority = float(sharpe) + float(fitness)
            if turnover is not None:
                priority -= 0.50 * max(0.0, float(turnover) - config.NEAR_PASSER_MAX_TURNOVER)
            source_stage = "frontier"

        elif sharpe >= config.FRONTIER_ALT_MIN_SHARPE and fitness >= config.FRONTIER_ALT_MIN_FITNESS:
            priority = float(sharpe) + float(fitness)
            if turnover is not None:
                priority -= 0.70 * max(0.0, float(turnover) - config.NEAR_PASSER_MAX_TURNOVER)
            source_stage = "frontier_alt"

        if source_stage is not None:
            self.storage.add_refinement_candidate(
                candidate_id=candidate_id,
                run_id=run_id,
                priority=priority,
                reason=metrics.fail_reason or source_stage,
                created_at=utc_now(),
                source_stage=source_stage,
                base_sharpe=sharpe,
                base_fitness=fitness,
                base_turnover=turnover,
            )
            print(
                f"[QUEUED_REFINEMENT] run_id={run_id} candidate_id={candidate_id} "
                f"priority={priority:.3f} reason={metrics.fail_reason} stage={source_stage}"
            )
            # v7.0: If this candidate was a refinement child, consume the parent
            # This breaks the feedback loop where parent + child both sit in queue
            parent_id = self._refinement_lineage.pop(candidate_id, None)
            if parent_id:
                try:
                    self.storage.mark_refinement_consumed(parent_id)
                    self._active_refinement_ids.discard(parent_id)
                    print(f"[PARENT_CONSUMED] child={candidate_id[:20]} replaced parent={parent_id[:20]} in queue")
                except Exception:
                    pass

    def _attempt_submission(self, candidate_id: str, run_id: str, result: dict) -> None:
        """
        v5.9.1: Submit alpha using the verified API flow.

        POST /alphas/{id}/submit -> poll GET -> parse 200 (pass) or 403 (fail).
        Failed submissions don't count against daily cap.
        """
        alpha_id = (
            result.get("alpha_id")
            or result.get("raw", {}).get("alpha_id")
            or result.get("raw", {}).get("id")
            or result.get("raw", {}).get("alpha")
        )

        if not alpha_id:
            print(f"[SUBMIT_SKIP] run_id={run_id} reason=no_alpha_id_found raw_keys={list(result.get('raw', {}).keys())}")
            return

        print(f"[SUBMIT_STARTING] run_id={run_id} alpha_id={alpha_id}")

        try:
            sub_result = self.client.submit_alpha(alpha_id)
            accepted = sub_result.get("_accepted")
            self_corr = sub_result.get("_self_correlation")
            corr_with = sub_result.get("_correlated_with")
            fail_reason = sub_result.get("_fail_reason")

            if accepted is True:
                self.storage.insert_submission(
                    submission_id=new_id("sub"),
                    candidate_id=candidate_id,
                    run_id=run_id,
                    submitted_at=utc_now(),
                    submission_status="confirmed",
                    message=f"accepted: self_corr={self_corr}",
                )
                print(
                    f"[SUBMIT_CONFIRMED] run_id={run_id} alpha_id={alpha_id} "
                    f"self_correlation={self_corr} + ACCEPTED INTO OS"
                )
            elif accepted is False:
                # Rejected - record but don't count as submitted
                self.storage.insert_submission(
                    submission_id=new_id("sub"),
                    candidate_id=candidate_id,
                    run_id=run_id,
                    submitted_at=utc_now(),
                    submission_status="rejected",
                    message=f"rejected: {fail_reason} self_corr={self_corr} correlated_with={corr_with}",
                )
                print(
                    f"[SUBMIT_REJECTED] run_id={run_id} alpha_id={alpha_id} "
                    f"reason={fail_reason} self_corr={self_corr} "
                    f"correlated_with={corr_with} x NOT ACCEPTED"
                )
                # v6.1: Track rejected cores to skip future submissions of same core
                if fail_reason and "SELF_CORRELATION" in str(fail_reason).upper():
                    cand_row = self.storage.get_candidate_by_id(candidate_id)
                    if cand_row:
                        rej_core = self._extract_core_signal(cand_row.get("canonical_expression", ""))
                        if rej_core and rej_core not in self.rejected_cores:
                            self.rejected_cores.add(rej_core)
                            print(
                                f"[CORE_REJECTED] core='{rej_core[:60]}' "
                                f"self_corr={self_corr} - future variants will skip submission"
                            )
            else:
                # Timeout or unknown
                self.storage.insert_submission(
                    submission_id=new_id("sub"),
                    candidate_id=candidate_id,
                    run_id=run_id,
                    submitted_at=utc_now(),
                    submission_status="unknown",
                    message=f"timeout_or_unknown: {fail_reason}",
                )
                print(
                    f"[SUBMIT_UNKNOWN] run_id={run_id} alpha_id={alpha_id} "
                    f"reason={fail_reason} ! CHECK MANUALLY"
                )
        except Exception as exc:
            self.storage.insert_submission(
                submission_id=new_id("sub"),
                candidate_id=candidate_id,
                run_id=run_id,
                submitted_at=utc_now(),
                submission_status="failed",
                message=str(exc)[:500],
            )
            print(f"[SUBMIT_ERROR] run_id={run_id} alpha_id={alpha_id} error={exc}")

    def _extract_alpha_id(self, result: dict) -> str | None:
        """Extract alpha_id from simulation result."""
        return (
            result.get("alpha_id")
            or result.get("raw", {}).get("alpha_id")
            or result.get("raw", {}).get("id")
            or result.get("raw", {}).get("alpha")
        )

    def _extract_fields_from_expr(self, expression: str) -> list[str]:
        """v7.1: Extract data field names from an expression for correlation hurdle."""
        import re
        # Match word tokens that look like data fields (not operators/numbers/keywords)
        operators = {
            "rank", "ts_rank", "ts_zscore", "ts_delta", "ts_mean", "ts_std_dev",
            "ts_decay_linear", "ts_corr", "ts_regression", "ts_sum", "ts_backfill",
            "ts_delay", "ts_av_diff", "ts_arg_max", "ts_arg_min", "ts_step",
            "ts_product", "ts_min", "ts_max",
            "group_rank", "group_zscore", "group_neutralize", "group_vector_neut",
            "zscore", "winsorize", "trade_when", "hump", "scale", "log", "abs",
            "max", "min", "power", "vec_avg", "vec_sum", "vec_count",
            "bucket", "quantile", "range", "subindustry", "industry", "sector",
            "market", "rank", "returns", "close", "open", "high", "low",
            "volume", "vwap", "cap", "adv20",
        }
        tokens = re.findall(r'[a-z][a-z0-9_]+', expression.lower())
        return [t for t in tokens if t not in operators and len(t) > 3 and not t.isdigit()]

    def _optimize_and_submit(self, candidate_id: str, run_id: str, result: dict, metrics) -> None:
        """
        v6.2: Smart submission pipeline.

        1. Check self-correlation via API (only gate - no before-after yet)
        2. If passes -> generate Optuna settings variants
        3. Simulate each variant (blocking)
        4. For each passing variant -> check self-corr + before-after
        5. Also check before-after for original
        6. Pick variant with highest positive score change
        7. AUTO_SUBMIT=True -> submit to WQ
           AUTO_SUBMIT=False -> insert into ready_alphas table for manual submission
        """
        import json as _json
        self._optimizing = True
        try:
            self._optimize_and_submit_inner(candidate_id, run_id, result, metrics)
        finally:
            self._optimizing = False

    def _optimize_and_submit_inner(self, candidate_id: str, run_id: str, result: dict, metrics) -> None:
        import json as _json

        candidate_row = self.storage.get_candidate_by_id(candidate_id)
        if not candidate_row:
            print(f"[OPTIMIZE_SKIP] candidate {candidate_id} not found in storage")
            return

        expression = candidate_row.get("canonical_expression", "")
        core = self._extract_core_signal(expression)
        family = candidate_row.get("family", "")

        # v7.2.7: Parse delay early so we can skip d=1 core blocklists for d=0
        # candidates (d=0 lives in a separate self-correlation space).
        try:
            settings_json = candidate_row.get("settings_json", "{}")
            if isinstance(settings_json, str):
                settings_dict = _json.loads(settings_json) if settings_json else {}
            else:
                settings_dict = settings_json or {}
            is_delay0 = int(settings_dict.get("delay", 1)) == 0
        except Exception:
            is_delay0 = False

        # Skip if core already rejected by self-correlation
        # v7.2: Sweeps also skip - same core = same correlation regardless of settings
        # v7.2.7: d=0 candidates skip this block - d=0 self-corr space is separate.
        is_sweep = str(candidate_row.get("template_id", "")).startswith("sweep_")
        if core and core in self.rejected_cores and not is_delay0:
            print(
                f"[OPTIMIZE_SKIP_CORR] run_id={run_id} "
                f"core='{core[:60]}' - already rejected by WQ"
            )
            return

        # v7.2.6: For delay=0 alphas, WQ requires Sharpe >= 2.0 to submit (vs 1.25 for d=1).
        # OPTIMIZE generates 8 settings variants - historically Optuna can lift Sharpe
        # by 0.3-0.5 through better neutralization/decay/truncation. So accept d=0
        # candidates from S>=1.65 - they have a realistic shot at hitting the 2.0 bar
        # via a sibling variant. Below 1.65, the gap is too big to bridge.
        # IMPORTANT: d=1 candidates pass through unchanged (their bar is still 1.25).
        if is_delay0 and metrics.sharpe < 1.65:
            print(
                f"[OPTIMIZE_SKIP_D0_LOW_SHARPE] run_id={run_id} "
                f"S={metrics.sharpe:.2f} < 1.65 (d0 needs S>=2.0 to submit, refinement headroom too small)"
            )
            return

        #  Step 1: Check self-correlation ONLY (the only gate)
        alpha_id = self._extract_alpha_id(result)
        if not alpha_id:
            print(f"[OPTIMIZE_SKIP] run_id={run_id} - no alpha_id found")
            return

        print(
            f"\n{'='*60}\n"
            f"[OPTIMIZE_START] S={metrics.sharpe:.2f} F={metrics.fitness:.2f} "
            f"family={family}\n"
            f"  expr={expression[:100]}\n"
            f"  Checking self-correlation..."
        )

        check = None
        for attempt in range(3):
            try:
                check = self.client.check_alpha(alpha_id)
                break
            except Exception as exc:
                if attempt < 2:
                    print(f"  ! Check timed out (attempt {attempt+1}/3), retrying...")
                    import time; time.sleep(5)
                else:
                    print(f"[OPTIMIZE_TIMEOUT] Check failed after 3 attempts: {exc}")

        # v7.1: If check failed or self-corr still PENDING, stage as unverified
        # instead of silently dropping. The submit pipeline retry will re-check.
        if check is None or check.get("_passed") is None:
            reason = "api_timeout" if check is None else "self_corr_pending"
            self.storage.insert_ready_alpha(
                candidate_id=candidate_id,
                run_id=run_id,
                alpha_id=alpha_id,
                expression=expression,
                core_signal=core or "",
                family=family,
                template_id=candidate_row.get("template_id", ""),
                sharpe=metrics.sharpe,
                fitness=metrics.fitness,
                turnover=metrics.turnover,
                score_before=None, score_after=None, score_change=None,
                settings_json=candidate_row.get("settings_json", "{}"),
                variant_desc=f"original (unverified: {reason})",
                status="unverified",
            )
            print(
                f"  ! Self-corr {reason} - staged as unverified for retry\n"
                f"{'='*60}\n"
            )
            return

        if check["_passed"] is False:
            corr_val = check.get("_self_correlation") or 1.0
            if core and corr_val >= 0.75:
                # v7.2.1: Only hard-block strong correlations. Cores at 0.70-0.75
                # might pass with different settings (universe/neutralization shift
                # the PnL curve enough to drop correlation below 0.70). The epoch
                # saturation penalty already handles the family-level dampening.
                self.rejected_cores.add(core)
            # v7.2.1: Tell the generator this family just bounced off the
            # saturation wall - it'll down-weight the family for the rest
            # of the current epoch so we stop wasting sims on the same space.
            try:
                if hasattr(self.generator, "record_corr_fail"):
                    self.generator.record_corr_fail(family)
            except Exception:
                pass
            print(
                f"[OPTIMIZE_CORR_FAIL] x Self-correlation failed "
                f"(corr={check['_self_correlation']}, with={check['_correlated_with']})\n"
                f"{'='*60}\n"
            )
            return

        print(f"  + Self-correlation PASSED - expression is viable, optimising settings...")

        #  Step 2: Generate settings variants + simulate
        # Track all viable variants for comparison at the end
        variants = []

        # Include original as a candidate
        variants.append({
            "alpha_id": alpha_id,
            "change": None,  # Will check before-after later
            "sharpe": metrics.sharpe,
            "fitness": metrics.fitness,
            "desc": "original",
            "candidate_id": candidate_id,
            "run_id": run_id,
            "settings_json": candidate_row.get("settings_json", "{}"),
        })

        n_variants = getattr(config, "OPTIMIZE_VARIANTS", 5)

        if _HAS_OPTUNA and self.settings_optimizer:
            print(f"  Generating {n_variants} Optuna settings variants...")

            base_settings_raw = candidate_row.get("settings_json", "{}")
            if isinstance(base_settings_raw, str):
                try:
                    base_settings = _json.loads(base_settings_raw)
                except:
                    base_settings = {}
            else:
                base_settings = base_settings_raw or {}

            tried_combos = set()
            generated = 0

            # v6.2.1: Collect all variant settings first, then simulate in parallel batches of 3
            # v7.2.7: Use suggest_batch (single Optuna study generating N variants)
            # instead of looping suggest() - old approach created N independent studies
            # that all converged to the same TPE recommendation when warm-start data
            # was clustered, producing duplicates.
            pending_variants = []
            skipped_variants = []

            optuna_suggestions = self.settings_optimizer.suggest_batch(
                expression=expression,
                n=n_variants,
                core_signal=core or "",
                family=family,
            )

            if not optuna_suggestions:
                print(f"  ! No Optuna suggestions returned - skipping variant generation")

            for suggestion in optuna_suggestions:
                combo_key = (
                    suggestion.get("universe"),
                    suggestion.get("neutralization"),
                    suggestion.get("decay"),
                    suggestion.get("truncation"),
                    suggestion.get("delay", 1),
                )
                if combo_key in tried_combos:
                    continue
                tried_combos.add(combo_key)

                variant_settings = {**base_settings, **suggestion}
                variant_settings.setdefault("region", "USA")
                variant_settings.setdefault("delay", 1)
                variant_settings.setdefault("pasteurization", "ON")
                variant_settings.setdefault("unit_handling", "VERIFY")
                variant_settings.setdefault("nan_handling", "OFF")
                variant_settings.setdefault("language", "FASTEXPR")

                desc = (
                    f"{suggestion.get('universe','?')}/"
                    f"{suggestion.get('neutralization','?')}/"
                    f"decay{suggestion.get('decay','?')}/"
                    f"delay{suggestion.get('delay',1)}/"
                    f"t{suggestion.get('truncation','?')}"
                )
                pending_variants.append((desc, variant_settings))

            # v7.2.6: Force-inject a d=0 variant if expression is safe and Optuna
            # didn't suggest one. d=0 alphas live in a separate self-correlation
            # space - even at 1/3 score multiplier they often land when d=1 doesn't
            # because the saturated portfolio is mostly d=1.
            try:
                from settings_optimizer import _delay_choices_for_expression
                d0_safe = 0 in _delay_choices_for_expression(expression)
            except Exception:
                d0_safe = False

            has_d0 = any(s.get("delay") == 0 for _, s in pending_variants)
            if d0_safe and not has_d0 and pending_variants:
                # Take the best-looking variant and clone it with delay=0
                _, base_v = pending_variants[0]
                d0_variant = {**base_v, "delay": 0}
                d0_desc = (
                    f"{d0_variant.get('universe','?')}/"
                    f"{d0_variant.get('neutralization','?')}/"
                    f"decay{d0_variant.get('decay','?')}/"
                    f"delay0/"
                    f"t{d0_variant.get('truncation','?')} (forced d0)"
                )
                pending_variants.append((d0_desc, d0_variant))
                print(f"  [FORCED_D0] Injected delay=0 variant for portfolio diversity")

            # Drain in-flight sims first so we have full concurrent capacity
            import time as _time
            if self.scheduler.running:
                print(f"  [OPTIMIZE] Draining {len(self.scheduler.running)} in-flight sims before variant testing...")
                drain_deadline = _time.time() + 3 * 60
                while self.scheduler.running and _time.time() < drain_deadline:
                    self._poll_running()
                    if self.scheduler.running:
                        _time.sleep(5)

            # Submit sequentially with retry on 429 (WQ concurrent limit = 2-3)
            # Poll completions during backoff so concurrent slots free up
            batch_sims = []
            for vi, (desc, vsettings) in enumerate(pending_variants):
                # Wait between submissions so earlier sims complete & free concurrent slots
                if vi > 0:
                    for _wait in range(2):
                        self._poll_running()
                        for _bd, _bvs, _bsid in batch_sims:
                            try:
                                self.client.poll_simulation(_bsid)
                            except Exception:
                                pass
                        _time.sleep(3)
                submitted = False
                last_exc = None
                for retry in range(6):  # up to 6 retries
                    try:
                        sim_id_v = self.client.submit_simulation(expression, vsettings)
                        batch_sims.append((desc, vsettings, sim_id_v))
                        print(f"  [Variant] {desc} - submitted")
                        submitted = True
                        break
                    except Exception as exc:
                        last_exc = exc
                        if "429" in str(exc) or "CONCURRENT" in str(exc).upper():
                            # Poll completions to free up concurrent slots
                            for _poll in range(3):
                                self._poll_running()
                                for _bd, _bvs, _bsid in batch_sims:
                                    try:
                                        self.client.poll_simulation(_bsid)
                                    except Exception:
                                        pass
                                _time.sleep(5)
                        else:
                            print(f"  [Variant] {desc} - submit failed: {exc}")
                            break
                if not submitted:
                    print(f"  [Variant] {desc} - deferred (concurrent limit)")
                    skipped_variants.append((desc, vsettings))
            pending_variants = []  # clear, now tracked in batch_sims

            # v7.2: Retry deferred variants after some batch sims complete (frees slots)
            if skipped_variants and batch_sims:
                # Wait for at least 1 batch sim to complete
                _retry_deadline = _time.time() + 60
                while _time.time() < _retry_deadline:
                    for _bd, _bvs, _bsid in batch_sims:
                        try:
                            self.client.poll_simulation(_bsid)
                        except Exception:
                            pass
                    self._poll_running()
                    _time.sleep(5)
                    # Try submitting deferred variants
                    still_skipped = []
                    for desc, vsettings in skipped_variants:
                        try:
                            sim_id_v = self.client.submit_simulation(expression, vsettings)
                            batch_sims.append((desc, vsettings, sim_id_v))
                            print(f"  [Variant] {desc} - submitted (retry)")
                        except Exception:
                            still_skipped.append((desc, vsettings))
                    skipped_variants = still_skipped
                    if not skipped_variants:
                        break

                for desc, vsettings in skipped_variants:
                    print(f"  [Variant] {desc} - skipped (concurrent limit)")
            skipped_variants = []

            # Poll all submitted variants until done
            batch_results = {}
            deadline = _time.time() + 8 * 60  # 8 min timeout
            _poll_count = 0
            while len(batch_results) < len(batch_sims) and _time.time() < deadline:
                for desc, vsettings, sid in batch_sims:
                    if sid in batch_results:
                        continue
                    try:
                        result_v = self.client.poll_simulation(sid)
                        if result_v["status"] in ("completed", "failed", "timed_out"):
                            batch_results[sid] = (desc, vsettings, result_v)
                            print(f"  [Variant] {len(batch_results)}/{len(batch_sims)} results received...")
                    except Exception:
                        pass
                if len(batch_results) < len(batch_sims):
                    _poll_count += 1
                    if _poll_count % 6 == 0:  # ~30s
                        print(f"  [Polling] {len(batch_results)}/{len(batch_sims)} complete, waiting...")
                    _time.sleep(5)

            # Process batch results
            for desc, vsettings, sid in batch_sims:
                if sid not in batch_results:
                    print(f"    ! {desc} - timed out")
                    continue
                _, _, variant_result = batch_results[sid]

                if variant_result["status"] != "completed":
                    print(f"    ! {desc} - status: {variant_result['status']}")
                    continue

                v_metrics = parse_metrics(f"opt_{generated}", variant_result)
                if not v_metrics.submit_eligible:
                    print(
                        f"    ! Not eligible: S={v_metrics.sharpe:.2f} F={v_metrics.fitness:.2f} "
                        f"({v_metrics.fail_reason})"
                    )
                    continue

                # v7.2.6: d=0 variants need S>=2.0 to actually submit on WQ.
                # If a d=0 variant is eligible at the d=1 bar (S>=1.25) but below
                # the d=0 bar, it'll fail at submission. Skip early.
                v_is_d0 = int(vsettings.get("delay", 1)) == 0
                if v_is_d0 and v_metrics.sharpe < 2.0:
                    print(
                        f"    ! {desc} - d=0 variant S={v_metrics.sharpe:.2f} "
                        f"below d0 submission threshold 2.0 - skipping"
                    )
                    continue

                v_alpha_id = self._extract_alpha_id(variant_result)
                if not v_alpha_id:
                    print(f"    ! No alpha_id in result")
                    continue

                print(
                    f"    + Eligible: S={v_metrics.sharpe:.2f} F={v_metrics.fitness:.2f} "
                    f"T={v_metrics.turnover:.3f}"
                )

                # Check self-correlation for variant
                try:
                    v_check = self.client.check_alpha(v_alpha_id)
                except Exception as exc:
                    print(f"    ! Self-corr check timed out: {exc}")
                    continue
                if v_check["_passed"] is not True:
                    print(f"    x Self-corr failed (corr={v_check['_self_correlation']})")
                    continue

                print(f"    + Self-corr passed (corr={v_check['_self_correlation']})")

                variants.append({
                    "alpha_id": v_alpha_id,
                    "change": None,
                    "sharpe": v_metrics.sharpe,
                    "fitness": v_metrics.fitness,
                    "desc": desc,
                    "candidate_id": candidate_id,
                    "run_id": run_id,
                    "settings_json": _json.dumps(vsettings),
                })
                generated += 1

        #  Step 3: Check before-after for ALL viable variants
        # v7.0: Retry up to 3 times per variant - timeouts are common on WQ API
        print(f"\n  Checking merged performance for {len(variants)} viable variant(s)...")

        for v in variants:
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    perf = self.client.check_before_after_performance(
                        v["alpha_id"], competition_id=config.IQC_COMPETITION_ID,
                    )
                    if perf.get("_score_change") is not None:
                        break  # Got a real result
                    if attempt < max_retries - 1:
                        import time
                        time.sleep(5)
                except Exception as exc:
                    if attempt < max_retries - 1:
                        import time
                        time.sleep(5)
                    else:
                        print(f"  ! Before-after failed after {max_retries} attempts for {v['desc']}: {exc}")
                        perf = {"_score_change": None, "_score_before": None, "_score_after": None}
            v["change"] = perf.get("_score_change")
            v["before"] = perf.get("_score_before")
            v["after"] = perf.get("_score_after")

            if v["change"] is not None:
                direction = "+" if v["change"] > 0 else "-" if v["change"] < 0 else "="
                print(
                    f"  {direction} {v['desc']}: Score {v['before']:.0f} -> {v['after']:.0f} "
                    f"(change: {v['change']:+.0f}) S={v['sharpe']:.2f} F={v['fitness']:.2f}"
                )
            else:
                print(
                    f"  ! {v['desc']}: before-after unavailable "
                    f"S={v['sharpe']:.2f} F={v['fitness']:.2f}"
                )

        #  Step 4: Pick best and submit or stage
        positive = [v for v in variants if v["change"] is not None and v["change"] >= 0]

        if positive:
            best = max(positive, key=lambda v: (v["change"], v["sharpe"]))
            print(
                f"\n  * BEST: {best['desc']} - score change={best['change']:+.0f} "
                f"S={best['sharpe']:.2f} F={best['fitness']:.2f}"
            )

            # v7.2.7: Belt-and-braces score floor at the boundary even though
            # `positive` already filters change >= 0 and AUTO_SUBMIT defaults
            # to False. Never submit anything below SUBMIT_MIN_SCORE.
            _min_score = getattr(config, "SUBMIT_MIN_SCORE", 15)
            should_auto_submit = (
                config.AUTO_SUBMIT
                and (best.get("change") or 0) >= _min_score
            )
            if config.AUTO_SUBMIT and not should_auto_submit:
                print(
                    f"  x [SCORE_GUARD] Refusing to auto-submit "
                    f"score={best.get('change')} < min_score={_min_score}"
                )

            if should_auto_submit:
                # Submit directly to WQ
                print(f"  Submitting alpha_id={best['alpha_id']}...")
                sub_result = self.client.submit_alpha(best["alpha_id"])
                accepted = sub_result.get("_accepted")

                if accepted is True:
                    self.storage.insert_submission(
                        submission_id=new_id("sub"),
                        candidate_id=best["candidate_id"],
                        run_id=best["run_id"],
                        submitted_at=utc_now(),
                        submission_status="confirmed",
                        message=(
                            f"auto-optimized: {best['desc']} score change={best['change']:+.0f} "
                            f"S={best['sharpe']:.2f} F={best['fitness']:.2f}"
                        ),
                    )
                    if core:
                        self.passed_cores[core] = self.passed_cores.get(core, 0) + 1
                    print(
                        f"  + SUBMITTED - score change: {best['change']:+.0f}\n"
                        f"{'='*60}\n"
                    )
                    # v6.2.1: Queue universe sweep for this alpha
                    self.universe_sweeper.queue_sweep(
                        expression=expression,
                        settings=json.loads(best.get("settings_json", "{}")) if isinstance(best.get("settings_json"), str) else best.get("settings_json", {}),
                        family=family,
                        template_id=candidate_row.get("template_id", ""),
                        alpha_id=best.get("alpha_id", ""),
                    )
                elif accepted is False:
                    fail_reason = sub_result.get("_fail_reason", "unknown")
                    self.storage.insert_submission(
                        submission_id=new_id("sub"),
                        candidate_id=best["candidate_id"],
                        run_id=best["run_id"],
                        submitted_at=utc_now(),
                        submission_status="rejected",
                        message=f"rejected at submit: {fail_reason}",
                    )
                    if "SELF_CORRELATION" in str(fail_reason).upper() and core:
                        self.rejected_cores.add(core)
                    print(
                        f"  x Rejected at submit: {fail_reason}\n"
                        f"{'='*60}\n"
                    )
                else:
                    print(f"  ! Submit timeout/unknown\n{'='*60}\n")
            else:
                # AUTO_SUBMIT=False -> stage ALL positive variants in ready_alphas.
                # v7.2.1: Don't just stage the best - after it gets submitted,
                # the portfolio shifts and a +4 variant might become +30.
                # Stage all of them so they can be re-checked at submission time.
                for pv in positive:
                    try:
                        self.storage.insert_ready_alpha(
                            candidate_id=pv["candidate_id"],
                            run_id=pv["run_id"],
                            alpha_id=pv["alpha_id"],
                            expression=expression,
                            core_signal=core or "",
                            family=family,
                            template_id=candidate_row.get("template_id", ""),
                            sharpe=pv["sharpe"],
                            fitness=pv["fitness"],
                            turnover=metrics.turnover,
                            score_before=pv.get("before"),
                            score_after=pv.get("after"),
                            score_change=pv["change"],
                            settings_json=pv.get("settings_json", "{}"),
                            variant_desc=pv["desc"],
                        )
                    except Exception:
                        pass  # Duplicate alpha_id
                print(
                    f"   STAGED {len(positive)} variant(s) in ready_alphas - best score change={best['change']:+.0f} "
                    f"(submit manually on BRAIN website)\n"
                    f"{'='*60}\n"
                )
                # v6.2.1: Queue universe sweep for best alpha
                self.universe_sweeper.queue_sweep(
                    expression=expression,
                    settings=json.loads(best.get("settings_json", "{}")) if isinstance(best.get("settings_json"), str) else best.get("settings_json", {}),
                    family=family,
                    template_id=candidate_row.get("template_id", ""),
                    alpha_id=best.get("alpha_id", ""),
                )

        else:
            # No positive change found
            unknown = [v for v in variants if v["change"] is None]
            # v7.2.6: Loosened thresholds. Was: marginal=-10..0, truly_negative=<-10.
            # New: marginal=-25..0 plus any alpha with Sharpe>=1.6 regardless of score
            # (high-Sharpe alphas score change can flip positive after a few portfolio
            # shifts). truly_negative cutoff at -25 means we trade fewer SCORE_NEG_BLOCKs
            # for more flexibility - many alphas at -15 to -25 today recover to +5..+30
            # after the portfolio rotates.
            # v7.2.7: Now read from config so all threshold sites stay in sync.
            STAGING_FLOOR = getattr(config, "STAGING_FLOOR", -25)
            HIGH_SHARPE_RESCUE = getattr(config, "HIGH_SHARPE_RESCUE", 1.6)
            marginal = [
                v for v in variants
                if v["change"] is not None
                and (
                    (STAGING_FLOOR <= v["change"] < 0)
                    or (v["change"] < STAGING_FLOOR and v.get("sharpe", 0) >= HIGH_SHARPE_RESCUE)
                )
            ]
            truly_negative = [
                v for v in variants
                if v["change"] is not None
                and v["change"] < STAGING_FLOOR
                and v.get("sharpe", 0) < HIGH_SHARPE_RESCUE
            ]

            if unknown:
                # v7.2.1: Stage ALL unknown variants, not just the best.
                # Different settings produce different PnL curves with different
                # portfolio correlations. S=2.25 might score -50 while S=1.88
                # on a different universe scores +30. The TeammateScoreChecker
                # will check each one and find the actual portfolio-positive variant.
                staged_count = 0
                for unk in unknown:
                    try:
                        self.storage.insert_ready_alpha(
                            candidate_id=unk["candidate_id"],
                            run_id=unk["run_id"],
                            alpha_id=unk["alpha_id"],
                            expression=expression,
                            core_signal=core or "",
                            family=family,
                            template_id=candidate_row.get("template_id", ""),
                            sharpe=unk["sharpe"],
                            fitness=unk["fitness"],
                            turnover=metrics.turnover,
                            score_before=None,
                            score_after=None,
                            score_change=None,
                            settings_json=unk.get("settings_json", "{}"),
                            variant_desc=unk["desc"] + " (unverified)",
                            status="unverified",
                        )
                        staged_count += 1
                    except Exception:
                        pass  # Duplicate alpha_id - already staged from a previous run
                best_unk = max(unknown, key=lambda v: v["sharpe"])
                print(
                    f"\n  ! Before-after unavailable - staged {staged_count} of {len(unknown)} variant(s) "
                    f"as 'unverified' (best S={best_unk['sharpe']:.2f} F={best_unk['fitness']:.2f}).\n"
                    f"{'='*60}\n"
                )
            elif marginal:
                # Stage marginal negatives - they might flip positive after portfolio shifts
                staged_count = 0
                for mv in marginal:
                    try:
                        self.storage.insert_ready_alpha(
                            candidate_id=mv["candidate_id"],
                            run_id=mv["run_id"],
                            alpha_id=mv["alpha_id"],
                            expression=expression,
                            core_signal=core or "",
                            family=family,
                            template_id=candidate_row.get("template_id", ""),
                            sharpe=mv["sharpe"],
                            fitness=mv["fitness"],
                            turnover=metrics.turnover,
                            score_before=mv.get("before"),
                            score_after=mv.get("after"),
                            score_change=mv["change"],
                            settings_json=mv.get("settings_json", "{}"),
                            variant_desc=mv["desc"] + " (marginal)",
                        )
                        staged_count += 1
                    except Exception:
                        pass
                print(
                    f"\n  - {len(marginal)} marginal variant(s) ({marginal[0]['change']:+.0f} to "
                    f"{marginal[-1]['change']:+.0f}) - staged {staged_count} for recheck.\n"
                    f"{'='*60}\n"
                )
            elif truly_negative:
                print(
                    f"\n  - ALL {len(truly_negative)} variants scored < -25 (and S<1.6) - skipping.\n"
                    f"{'='*60}\n"
                )
                # v6.2: Block further refinement of this core - it hurts the portfolio
                if core:
                    self._score_negative_cores.add(core)
                    print(f"[SCORE_NEG_BLOCK] core='{core[:60]}' - blocking further refinement")

    def _check_submission_portfolio_fit(
        self,
        candidate_id: str,
        run_id: str,
        sharpe: float | None,
    ) -> dict:
        """
        Predict whether a candidate will pass WQ's self-correlation test.

        WQ computes Pearson correlation between daily PnL streams.
        Rule: correlation < 0.7, OR Sharpe >= 10% better than correlated alpha.

        We can't compute PnL correlation directly (no daily PnL data from API),
        so we use a data-source-category proxy based on WQ's own documentation:
        "The most effective way to reduce correlation is to use unique datasets."

        Tiers (checked in order, stop at first match):
          1. Same core signal -> BLOCK (guaranteed PnL correlation > 0.7)
          2. Same data source category -> BLOCK unless Sharpe 10%+ better
          3. Different data source category -> ALLOW (near-zero PnL correlation)
        """
        # v7.0: Check against ALL team submissions - if a teammate already submitted
        # this core signal, duplicating it on our account adds zero portfolio value.
        try:
            submitted_rows = self.storage.get_all_team_submissions(limit=500)
        except Exception:
            submitted_rows = self.storage.get_submitted_candidate_rows(limit=100)

        if not submitted_rows:
            return {"fits": True, "max_similarity": 0.0, "reason": "no_prior_submissions"}

        candidate_row = self.storage.get_candidate_by_id(candidate_id)
        if candidate_row is None:
            return {"fits": True, "max_similarity": 0.0, "reason": "candidate_not_found"}

        cand_expr = candidate_row["canonical_expression"]
        cand_core = self._extract_core_signal(cand_expr)
        cand_data_cat = self._classify_data_source(cand_expr)

        for ref_row in submitted_rows:
            ref_expr = ref_row["canonical_expression"]
            ref_sharpe = ref_row["sharpe"]
            ref_core = self._extract_core_signal(ref_expr)
            ref_data_cat = self._classify_data_source(ref_expr)
            ref_cid = ref_row["candidate_id"]
            ref_family = ref_row["family"]
            ref_tid = ref_row["template_id"]

            #  Tier 1: Same core signal -> guaranteed high PnL correlation
            if cand_core and ref_core and cand_core == ref_core:
                if sharpe is not None and ref_sharpe is not None and sharpe >= float(ref_sharpe) * 1.10:
                    continue
                return {
                    "fits": False,
                    "max_similarity": 0.95,
                    "reason": f"same_core_signal '{cand_core}' vs submitted {ref_cid}",
                    "ref_candidate_id": ref_cid,
                    "ref_family": ref_family,
                    "ref_template_id": ref_tid,
                }

            #  Tier 2: Same data source category -> high PnL correlation risk
            # Alphas using the same primary data source (e.g., both use price
            # returns) tend to correlate 0.5-0.8 even with different expressions.
            # Block unless Sharpe is 10%+ better.
            if cand_data_cat == ref_data_cat:
                if sharpe is not None and ref_sharpe is not None and sharpe >= float(ref_sharpe) * 1.10:
                    continue
                return {
                    "fits": False,
                    "max_similarity": 0.70,
                    "reason": (
                        f"same_data_category '{cand_data_cat}' as submitted {ref_cid} "
                        f"(family={ref_family}) - needs Sharpe >= {float(ref_sharpe) * 1.10:.2f}"
                    ),
                    "ref_candidate_id": ref_cid,
                    "ref_family": ref_family,
                    "ref_template_id": ref_tid,
                }

        #  Tier 3: Different data source from all submitted -> very likely uncorrelated
        return {
            "fits": True,
            "max_similarity": 0.10,
            "reason": f"different_data_category (candidate='{cand_data_cat}')",
        }

    @staticmethod
    def _classify_data_source(expression: str) -> str:
        """
        Classify an expression by its PRIMARY data source.

        v5.9: Added model77, relationship, risk_beta, analyst_estimates categories.
        """
        expr_lower = expression.lower()

        # v5.9: New data source categories (check first - most specific)
        has_model77 = any(f in expr_lower for f in [
            "standardized_unexpected_earnings", "earnings_momentum_composite",
            "earnings_revision_magnitude", "asset_growth_rate", "gross_profit_to_assets",
            "tobins_q_ratio", "distress_risk_measure", "trailing_twelve_month_accruals",
            "forward_median_earnings_yield", "cash_flow_return_on_invested",
            "twelve_month_short_interest", "financial_statement_value_score",
            "fcf_yield_times_forward", "value_momentum_analyst",
            "momentum_analyst_composite", "normalized_earnings_yield",
            "ttm_operating_cash_flow", "ttm_operating_income_to_ev",
            "industry_relative_return", "industry_relative_book",
            "sales_surprise_score", "price_momentum_module",
            "fundamental_growth_module", "cash_burn_rate",
        ])
        # v6.2.1: Vector datasets (vec_* operators on multi-value fields)
        has_vector = any(f in expr_lower for f in [
            "vec_avg", "vec_sum", "vec_count", "vec_max", "vec_min",
            "vec_stddev", "vec_range", "vec_ir",
            "scl12_alltype_buzzvec", "scl12_alltype_sentvec",
            "nws12_", "scl15_",
        ])
        # v6.2.1: Model data (mdf_*, mdl175_*)
        has_model_data = any(f in expr_lower for f in [
            "mdf_nps", "mdf_oey", "mdf_rds", "mdf_pbk", "mdf_eg3", "mdf_sg3",
            "mdl175_",
        ])
        # v6.2.1: Event-driven (fnd6_*, fam_*, days_from_last_change, last_diff_value)
        has_event = any(f in expr_lower for f in [
            "fnd6_", "fam_earn_surp", "fam_roe_rank",
            "days_from_last_change", "last_diff_value",
        ])
        has_relationship = any(f in expr_lower for f in [
            "rel_ret_", "rel_num_", "pv13_",
        ])
        has_risk_beta = any(f in expr_lower for f in [
            "beta_last_", "correlation_last_", "unsystematic_risk", "systematic_risk",
        ])
        has_analyst_est = any(f in expr_lower for f in [
            "est_eps", "est_fcf", "est_ptp", "est_cashflow_op", "est_capex",
            "est_ebit", "est_ebitda", "est_sales",
        ])
        has_expanded_fund = any(f in expr_lower for f in [
            "retained_earnings", "working_capital", "inventory_turnover",
            "rd_expense", "operating_income", "return_assets", "return_equity",
            "fn_liab_fair_val", "sharesout",
        ])

        # v6.2.1: Check untapped data categories first (most different from portfolio)
        if has_vector:
            return "vector_data"
        if has_model_data:
            return "model_data"
        if has_event:
            return "event_driven"
        if has_model77:
            return "model77"
        if has_relationship:
            return "relationship"
        if has_risk_beta:
            return "risk_beta"
        if has_analyst_est:
            return "analyst_estimates"
        if has_expanded_fund:
            return "expanded_fundamental"

        has_options = any(f in expr_lower for f in [
            "implied_volatility", "historical_volatility",
            "call_breakeven", "forward_price", "put_breakeven",
            "parkinson_volatility", "pcr_oi", "pcr_vol",
        ])
        has_sentiment = any(f in expr_lower for f in [
            "scl12_", "snt_", "snt1_",
        ])
        # v6.2.1: Add news category (was missing - rp_ess/rp_css/news_* were "unknown")
        has_news = any(f in expr_lower for f in [
            "rp_ess_", "rp_css_", "news_pct", "news_max", "news_ls",
        ])
        has_fundamental = any(f in expr_lower for f in [
            "cashflow_op", "ebitda", "ebit", "eps", "debt", "equity",
            "enterprise_value", "bookvalue_ps", "capex", "cogs",
            "current_ratio", "cash_st", "assets", "income", "sales",
        ])
        has_factor_model = any(f in expr_lower for f in [
            "fscore_", "consensus_analyst_rating",
        ])
        has_price = any(f in expr_lower for f in [
            "returns", "close", "open", "high", "low", "vwap",
        ])
        has_volume = any(f in expr_lower for f in [
            "volume", "adv20",
        ])
        # v6.2.1: Intraday patterns (open/close/high/low without returns)
        has_intraday = (
            any(f in expr_lower for f in ["open", "high", "low"])
            and "close" in expr_lower
            and "returns" not in expr_lower
        )

        if has_options and not has_price:
            return "options_vol"
        if has_options and has_price:
            return "options_vol"
        if has_news:
            return "news"
        if has_sentiment:
            return "sentiment"
        if has_intraday:
            return "intraday"
        if has_fundamental and not has_price:
            return "fundamental"
        if has_factor_model:
            return "factor_model"
        if has_fundamental and has_price:
            return "fundamental"

        if has_price and has_volume:
            return "price_volume"
        if has_price:
            return "price_returns"
        if has_volume:
            return "volume_only"

        return "unknown"

    def _extract_core_signal(self, expression: str) -> str:
        """
        Extract the core inner signal from an expression, stripping wrappers.

        ts_decay_linear(rank(rank(-(returns - ts_mean(returns, 5)))), 10)
        ts_mean(rank(rank(-(returns - ts_mean(returns, 5)))), 5)
        rank(-(returns - ts_mean(returns, 5)))

        All have the same core: -(returns - ts_mean(returns, 5))

        Similarly for volume_flow:
        (volume / ts_mean(volume, N)) * -returns  is the core for vol_03
        """
        import re
        expr = expression.strip()

        # Strip outer wrappers iteratively: ts_mean(..., N), ts_decay_linear(..., N), rank(...)
        changed = True
        while changed:
            changed = False

            # Strip ts_mean(X, N) or ts_decay_linear(X, N)
            for func in ["ts_mean", "ts_decay_linear"]:
                pattern = f"^{func}\\((.+),\\s*\\d+\\)$"
                m = re.match(pattern, expr)
                if m:
                    expr = m.group(1).strip()
                    changed = True

            # Strip outer rank(X)
            if expr.startswith("rank(") and expr.endswith(")"):
                inner = expr[5:-1]
                # Verify balanced parens
                depth = 0
                balanced = True
                for ch in inner:
                    if ch == "(":
                        depth += 1
                    elif ch == ")":
                        depth -= 1
                    if depth < 0:
                        balanced = False
                        break
                if balanced and depth == 0:
                    expr = inner.strip()
                    changed = True

        return expr

    def _get_submitted_family_set(self) -> set[str]:
        """Return set of families that have been successfully submitted."""
        submitted_rows = self.storage.get_submitted_candidate_rows(limit=100)
        families = set()
        for row in submitted_rows:
            try:
                families.add(row["family"])
            except (KeyError, IndexError):
                pass
        return families

    def _get_submitted_family_counts(self) -> dict[str, int]:
        """v7.2.8: Return COUNT of submissions per family (saturation signal).

        A family with 10 submitted alphas is far more saturated than one with 1.
        Used by family bias map to strongly down-weight over-mined families
        that have already filled most of the portfolio's available self-corr
        space for their pattern.
        """
        submitted_rows = self.storage.get_submitted_candidate_rows(limit=200)
        counts: dict[str, int] = {}
        for row in submitted_rows:
            try:
                fam = row["family"]
                counts[fam] = counts.get(fam, 0) + 1
            except (KeyError, IndexError):
                pass
        return counts

    def _get_submitted_template_set(self) -> set[str]:
        """Return set of template_ids that have been successfully submitted."""
        submitted_rows = self.storage.get_submitted_candidate_rows(limit=100)
        templates = set()
        for row in submitted_rows:
            try:
                templates.add(row["template_id"])
            except (KeyError, IndexError):
                pass
        return templates

    # Stats / scoring maps

    def _template_stats_map(self) -> dict[str, dict]:
        # v7.0: Cache stats for 3 minutes to reduce Supabase egress
        import time
        now = time.time()
        if hasattr(self, '_template_stats_cache_time') and (now - self._template_stats_cache_time) < 1800:  # 30min cache
            return self._template_stats_cache
        rows = self.storage.get_recent_template_stats(limit=config.TEMPLATE_SCORE_LOOKBACK_RUNS)
        out: dict[str, dict] = {}
        for row in rows:
            out[row["template_id"]] = {
                "family": row["family"],
                "n_runs": row["n_runs"] or 0,
                "avg_sharpe": row["avg_sharpe"],
                "avg_fitness": row["avg_fitness"],
                "avg_turnover": row["avg_turnover"],
            }
        self._template_stats_cache = out
        self._template_stats_cache_time = now
        return out

    def _family_stats_map(self) -> dict[str, dict]:
        import time
        now = time.time()
        if hasattr(self, '_family_stats_cache_time') and (now - self._family_stats_cache_time) < 1800:  # 30min cache
            return self._family_stats_cache
        rows = self.storage.get_recent_family_stats(limit=config.TEMPLATE_SCORE_LOOKBACK_RUNS)
        out: dict[str, dict] = {}
        for row in rows:
            out[row["family"]] = {
                "n_runs": row["n_runs"] or 0,
                "avg_sharpe": row["avg_sharpe"],
                "avg_fitness": row["avg_fitness"],
                "avg_turnover": row["avg_turnover"],
                "submit_rate": row["submit_rate"] if "submit_rate" in row.keys() else None,
            }
        self._family_stats_cache = out
        self._family_stats_cache_time = now
        return out

    def _score_from_stats(
        self,
        avg_sharpe,
        avg_fitness,
        avg_turnover,
        n_runs: int,
    ) -> float:
        if n_runs <= 0:
            return 1.0

        if avg_sharpe is None or avg_fitness is None:
            return 1.0

        score = 1.0

        score += 0.55 * max(-1.5, min(2.5, float(avg_sharpe)))
        score += 0.35 * max(-1.5, min(2.0, float(avg_fitness)))

        if avg_turnover is not None:
            turnover = float(avg_turnover)
            if turnover > 0.75:
                score -= 0.45
            elif turnover > 0.55:
                score -= 0.20
            elif turnover < 0.08:
                score -= 0.05

        if n_runs < 6:
            score *= 0.90

        return max(0.15, min(3.00, score))

    def _family_bias_map(self) -> dict[str, float]:
        """
        v6.1: Thompson Sampling for family selection.

        Instead of deterministic weights, sample from each family's posterior
        distribution. Families with high mean sharpe usually win, but
        under-explored families have high variance and sometimes sample
        very high - driving automatic exploration.

        Prior: N(0.5, 1.0) for unknown families
        Posterior: N(mean_sharpe, 1.0/sqrt(n))
        """
        import random as _rng

        stats = self._family_stats_map()
        bias: dict[str, float] = {}
        min_explore = getattr(config, "MIN_EXPLORATION_PER_FAMILY", 25)

        # Submission diversity: get families already in portfolio
        submitted_families = self._get_submitted_family_set()
        # v7.2.8: also get COUNTS so we can progressively down-weight saturated families
        submitted_counts = self._get_submitted_family_counts()
        diversity_boost = getattr(config, "UNSUBMITTED_FAMILY_BOOST", 1.60)

        # v7.2.8: Per-family saturation penalty thresholds. Tuned from logs
        # showing 161 CORE_REFINE_CAP exhaustions, mostly on gap_mining
        # and signal_combo cores already correlated with submitted portfolio.
        # We crush these so the bot looks elsewhere.
        # v7.2.9: Softened the crush floor from 0.25->0.40 because saturated
        # families ARE still producing the only staged alphas (1 of 1 last
        # night was signal_combo). Keep them productive while exploration
        # is boosted.
        def _saturation_penalty(n_submitted: int) -> float:
            if n_submitted <= 1: return 1.00
            if n_submitted <= 2: return 0.85
            if n_submitted <= 4: return 0.70
            if n_submitted <= 7: return 0.55
            return 0.40  # 8+ submitted - heavily saturated but not zeroed

        # v7.2.8: also boost diversity_gap families that the bot keeps logging
        # as missing from the portfolio (vol_adjusted, volume_flow, etc.)
        diversity_gap_families = getattr(config, "DIVERSITY_GAP_FAMILIES", set())
        diversity_gap_boost = getattr(config, "DIVERSITY_GAP_BOOST", 2.0)

        all_families = set()
        if hasattr(config, "DEFAULT_FAMILY_ORDER"):
            all_families.update(config.DEFAULT_FAMILY_ORDER)
        all_families.update(stats.keys())
        # v7.2.9: Also include exploration targets even if they have no stats yet
        # and aren't in DEFAULT_FAMILY_ORDER, otherwise the boost can't apply
        # because the family doesn't get a bias map entry at all.
        all_families.update(getattr(config, "EXPLORATION_TARGETS", set()))

        for family in all_families:
            if family not in stats:
                # Unknown family - sample from wide prior N(0.5, 1.0)
                sampled = _rng.gauss(0.5, 1.0)
            else:
                row = stats[family]
                n_runs = row.get("n_runs", 0) or 0
                avg_sharpe = float(row.get("avg_sharpe", 0) or 0)

                if n_runs < 3:
                    # Too few observations - wide prior
                    sampled = _rng.gauss(0.5, 0.8)
                else:
                    # Posterior: N(mean_sharpe, exploration_std / sqrt(n))
                    exploration_std = 1.0
                    posterior_std = exploration_std / (n_runs ** 0.5)
                    # Floor to ensure some exploration even for well-known families
                    posterior_std = max(posterior_std, 0.05)
                    sampled = _rng.gauss(avg_sharpe, posterior_std)

            # Convert sampled value to weight (must be positive)
            # Shift so that sharpe=0 -> weight~1.0, sharpe=1.5 -> weight~3.0
            weight = max(0.15, 1.0 + sampled)

            # Boost families not yet in submission portfolio
            if submitted_families and family not in submitted_families:
                if family not in {"momentum", "fundamental"}:
                    weight *= diversity_boost

            # v7.2.8: Apply count-based saturation penalty for already-submitted
            # families. The more alphas of a family already submitted, the
            # less likely a new alpha from that family will pass self-correlation
            # against the existing portfolio. Crushing 0.85->0.60->0.40->0.25 forces
            # the bot to redirect compute to under-mined families.
            n_submitted = submitted_counts.get(family, 0)
            if n_submitted > 0:
                weight *= _saturation_penalty(n_submitted)

            # v7.2.8: Boost diversity-gap families that the portfolio is missing
            # - directly addresses the `diversity_gaps=[...]` lines the bot
            # reports each session but never acted on.
            if family in diversity_gap_families:
                weight *= diversity_gap_boost

            # v7.2.9: EXPLORATION EXPERIMENT - force compute into hand-picked
            # under-explored families until each has >=30 sims of empirical data.
            # Bypasses DEAD_FAMILIES crush below because the dead-family list
            # is based on stale data and we want fresh evidence.
            exploration_targets = getattr(config, "EXPLORATION_TARGETS", set())
            exploration_boost = getattr(config, "EXPLORATION_BOOST", 3.0)
            exploration_min_sims = getattr(config, "EXPLORATION_MIN_SIMS", 30)
            is_exploration_target = family in exploration_targets
            if is_exploration_target:
                # Check actual sim count from stats
                fam_stats = stats.get(family, {})
                n_runs_actual = fam_stats.get("n_runs", 0) or 0
                if n_runs_actual < exploration_min_sims:
                    weight *= exploration_boost

            # v7.2.1: Sprint mode - crush dead families to near-zero
            # v7.2.9: BUT bypass for exploration targets - we want fresh evidence
            if getattr(config, "SPRINT_MODE", False):
                dead_families = getattr(config, "DEAD_FAMILIES", set())
                bypass_dead = (
                    is_exploration_target
                    and getattr(config, "EXPLORATION_BYPASS_DEAD", True)
                )
                if family in dead_families and not bypass_dead:
                    weight = getattr(config, "DEAD_FAMILY_WEIGHT", 0.01)

            bias[family] = weight

        # v7.0: Blend with team weights (teammates' learned data)
        if self.team_weights:
            try:
                team_bias = self.team_weights.get_blended_family_weights()
                for family, team_w in team_bias.items():
                    if family in bias:
                        bias[family] *= team_w
                    else:
                        bias[family] = team_w
            except Exception as exc:
                print(f"[TEAM_BIAS_WARN] {exc}")

        return bias

    def _template_bias_map(self) -> dict[str, float]:
        stats = self._template_stats_map()
        bias: dict[str, float] = {}

        for template_id, row in stats.items():
            bias[template_id] = self._score_from_stats(
                avg_sharpe=row["avg_sharpe"],
                avg_fitness=row["avg_fitness"],
                avg_turnover=row["avg_turnover"],
                n_runs=row["n_runs"],
            )

        # v7.0: Blend with team template weights
        if self.team_weights:
            try:
                team_bias = self.team_weights.get_blended_template_weights()
                for tid, team_w in team_bias.items():
                    if tid in bias:
                        bias[tid] *= team_w
                    else:
                        bias[tid] = team_w
            except Exception as exc:
                print(f"[TEAM_TEMPLATE_BIAS_WARN] {exc}")

        return bias

    def _settings_bias_map(self) -> dict[str, dict[str, float]]:
        """
        v5.5: Compute adaptive weights for each settings dimension.

        Returns: {"universe": {"TOP1000": 1.4, "TOP3000": 0.8, ...},
                  "neutralization": {...}, "decay": {...}, "truncation": {...}}

        Guardrails against over-specialization:
        - MIN_OBS = 8: under 8 observations, weight = 1.0 (no opinion yet)
        - Score formula biased toward 1.0 center - even the best setting
          only gets ~2x weight, worst gets ~0.4x
        - submit_rate bonus: settings that produce eligible alphas get a boost
        """
        MIN_OBS = 8

        try:
            raw_stats = self.storage.get_recent_settings_stats(
                limit=config.TEMPLATE_SCORE_LOOKBACK_RUNS
            )
        except Exception as exc:
            print(f"[SETTINGS_BIAS_ERROR] {exc}")
            return {}

        bias: dict[str, dict[str, float]] = {}

        for dimension, rows in raw_stats.items():
            dim_bias: dict[str, float] = {}

            for row in rows:
                setting_value = str(row["setting_value"]) if row["setting_value"] is not None else None
                if setting_value is None:
                    continue

                n_runs = int(row["n_runs"] or 0)
                avg_sharpe = row["avg_sharpe"]
                avg_fitness = row["avg_fitness"]
                submit_rate = row.get("submit_rate")

                # Not enough data - stay neutral
                if n_runs < MIN_OBS or avg_sharpe is None or avg_fitness is None:
                    dim_bias[setting_value] = 1.0
                    continue

                # Score: centered at 1.0, range roughly [0.3, 2.5]
                # Lower coefficients than family scoring - settings have less
                # signal-to-noise than expression structure
                score = 1.0
                score += 0.35 * max(-1.0, min(1.5, float(avg_sharpe)))
                score += 0.20 * max(-1.0, min(1.5, float(avg_fitness)))

                # Bonus for settings that actually produce eligible alphas
                if submit_rate is not None and float(submit_rate) > 0:
                    score += 0.40 * min(1.0, float(submit_rate) * 10.0)

                # Confidence scaling: partial weight for small samples
                if n_runs < 20:
                    # Blend toward 1.0 for low sample counts
                    confidence = n_runs / 20.0
                    score = 1.0 + (score - 1.0) * confidence

                dim_bias[setting_value] = max(0.25, min(2.50, score))

            if dim_bias:
                bias[dimension] = dim_bias

        return bias

    # Quality / pruning / diversity

    def _template_quality_class(self, template_id: str) -> str:
        stats = self._template_stats_map().get(template_id)
        if stats is None:
            return "unknown"

        n_runs = stats["n_runs"] or 0
        avg_sharpe = stats["avg_sharpe"]
        avg_fitness = stats["avg_fitness"]

        if n_runs < config.MIN_TEMPLATE_OBS_FOR_PRUNE:
            return "young"

        if (
            avg_sharpe is not None
            and avg_fitness is not None
            and avg_sharpe <= config.HARD_PRUNE_MAX_AVG_SHARPE
            and avg_fitness <= config.HARD_PRUNE_MAX_AVG_FITNESS
        ):
            return "hard_prune"

        if (
            avg_sharpe is not None
            and avg_fitness is not None
            and avg_sharpe <= config.SOFT_PRUNE_MAX_AVG_SHARPE
            and avg_fitness <= config.SOFT_PRUNE_MAX_AVG_FITNESS
        ):
            return "soft_prune"

        return "healthy"

    def _candidate_allowed_by_template_quality(self, candidate, is_refinement: bool) -> bool:
        quality = self._template_quality_class(candidate.template_id)

        if quality in {"unknown", "young", "healthy"}:
            return True

        if quality == "hard_prune":
            return False

        if quality == "soft_prune":
            if is_refinement:
                return self.generator.rng.random() < config.SOFT_PRUNE_REFINEMENT_PROBABILITY
            return self.generator.rng.random() < config.TEMPLATE_EXPLORATION_PROBABILITY

        return True

    def _candidate_allowed_by_diversity(self, candidate, is_refinement: bool) -> bool:
        # Always allow strong templates for refinement
        if candidate.template_id in getattr(config, "STRONG_TEMPLATES", set()):
            if is_refinement:
                return True
            return self.generator.rng.random() < 0.92

        # Submission diversity override: if this candidate's family has no submissions yet,
        # be much more permissive - we NEED diverse family submissions
        submitted_families = self._get_submitted_family_set()
        if submitted_families and candidate.family not in submitted_families:
            # Family not yet submitted - relax diversity limits heavily
            if candidate.family not in {"momentum", "fundamental"}:
                return True

        stats = self.storage.get_recent_template_stats(limit=config.DIVERSITY_LOOKBACK_RUNS)
        template_stats = None
        for row in stats:
            if row["template_id"] == candidate.template_id:
                template_stats = row
                break

        if template_stats is None:
            return True

        n_runs = template_stats["n_runs"] or 0
        avg_sharpe = template_stats["avg_sharpe"]
        avg_fitness = template_stats["avg_fitness"]

        if n_runs < config.RELAXED_TEMPLATE_COUNT:
            return True

        strong_template = (
            avg_sharpe is not None
            and avg_fitness is not None
            and avg_sharpe >= config.RELAXED_TEMPLATE_MIN_AVG_SHARPE
            and avg_fitness >= config.RELAXED_TEMPLATE_MIN_AVG_FITNESS
        )

        if n_runs >= config.MAX_RECENT_TEMPLATE_COUNT:
            if strong_template and is_refinement:
                return self.generator.rng.random() < 0.30
            return self.generator.rng.random() < config.DIVERSITY_EXPLORATION_PROBABILITY

        if strong_template and is_refinement:
            return True

        penalty_prob = max(0.15, 1.0 - 0.08 * (n_runs - config.RELAXED_TEMPLATE_COUNT))
        return self.generator.rng.random() < penalty_prob

    def _passes_local_refinement_filter(self, base_candidate_id: str, candidate) -> bool:
        history = self.refinement_local_history.get(base_candidate_id, [])
        if candidate.expression_hash in history:
            return False

        base_row = self.storage.get_candidate_by_id(base_candidate_id)
        if base_row is not None:
            result = self.similarity_engine.max_similarity_against_rows(candidate, [base_row])
            if result.score >= config.LOCAL_REFINEMENT_MAX_SIMILARITY:
                return False

        if history:
            rows = []
            for expr_hash in history:
                row = self.storage.get_candidate_by_hash(expr_hash)
                if row is not None:
                    rows.append(row)
            if rows:
                result = self.similarity_engine.max_similarity_against_rows(candidate, rows)
                if result.score >= config.LOCAL_REFINEMENT_MAX_SIMILARITY:
                    return False

        return True

    def _remember_local_refinement(self, base_candidate_id: str, expression_hash: str) -> None:
        history = self.refinement_local_history.get(base_candidate_id, [])
        history.append(expression_hash)
        keep = getattr(config, "LOCAL_REFINEMENT_HISTORY", 6)
        self.refinement_local_history[base_candidate_id] = history[-keep:]

    # Candidate selection

    def _should_abandon_refinement_base(self, base_candidate_id: str) -> bool:
        attempts = self.refinement_attempts_by_base.get(base_candidate_id, 0)
        return attempts >= config.MAX_REFINEMENT_ATTEMPTS_PER_BASE

    def _fresh_candidate(self):
        family_bias = self._family_bias_map()
        template_bias = self._template_bias_map()
        settings_bias = self._settings_bias_map()

        # v6.1: Periodically refresh signal combiner and evolver data
        if (
            self.signal_combiner is not None
            and self.completed_runs > 0
            and self.completed_runs % self._combo_refresh_interval == 0
        ):
            self.signal_combiner.refresh_near_passers()
        if (
            self.evolver is not None
            and self.completed_runs > 0
            and self.completed_runs % self._evolver_refresh_interval == 0
        ):
            self.evolver.refresh_population()

        # v7.2.1: Periodically refresh gap miner (portfolio changes after submissions)
        if (
            self.gap_miner is not None
            and self.completed_runs > 0
            and self.completed_runs % self._gap_refresh_interval == 0
        ):
            self.gap_miner.refresh()


        # v7.2.4: Dedicated Delay-0 mini-universe. This runs before gap/combo/evolver
        # and uses only Delay-0 specialist templates. It avoids mixing delay regimes.
        if (
            getattr(config, "DELAY0_ENABLED", False)
            and self.generator.rng.random() < getattr(config, "DELAY0_TEMPLATE_PROBABILITY", 0.0)
        ):
            candidate = self.generator.generate_delay0_candidate(
                family_bias=family_bias,
                template_bias=template_bias,
                settings_bias=settings_bias,
            )
            if candidate is not None:
                print(
                    f"[DELAY0_CANDIDATE] family={candidate.family} template={candidate.template_id} "
                    f"univ={candidate.settings.universe} neut={candidate.settings.neutralization} "
                    f"decay={candidate.settings.decay} expr={candidate.expression[:90]}"
                )
                return candidate

        # v7.2.6: FIELD GAP MINING - currently disabled for exploration mode.
        # Can be re-enabled in config.py via ENABLE_GAP_MINER=True and GAP_MINING_PROBABILITY>0.
        gap_prob = getattr(config, "GAP_MINING_PROBABILITY", 0.0)
        if (
            self.gap_miner is not None
            and self.gap_miner.gap_count > 0
            and self.generator.rng.random() < gap_prob
        ):
            candidate = self._gap_candidate(settings_bias)
            if candidate is not None:
                return candidate

        # v6.1: Try signal combination some of the time (10%)
        combo_prob = getattr(config, "COMBO_GENERATION_PROBABILITY", 0.10)
        if (
            self.signal_combiner is not None
            and self.generator.rng.random() < combo_prob
        ):
            candidate = self._combo_candidate(settings_bias)
            if candidate is not None:
                return candidate

        # v6.1: Try evolutionary mutation some of the time (10%)
        evolve_prob = getattr(config, "EVOLVE_GENERATION_PROBABILITY", 0.10)
        if (
            self.evolver is not None
            and self.generator.rng.random() < evolve_prob
        ):
            candidate = self._evolve_candidate(settings_bias)
            if candidate is not None:
                return candidate

        # v5.6: Try LLM generation some of the time
        llm_prob = getattr(config, "LLM_GENERATION_PROBABILITY", 0.35)
        if (
            self.llm_generator.available
            and self.generator.rng.random() < llm_prob
        ):
            candidate = self._llm_candidate(settings_bias)
            if candidate is not None:
                return candidate

        # Template generation (original path)
        for _ in range(8):
            candidate = self.generator.generate_candidate(
                family_bias=family_bias,
                template_bias=template_bias,
                settings_bias=settings_bias,
            )

            if self.storage.candidate_exists(candidate.expression_hash):
                continue

            if not self._candidate_allowed_by_template_quality(candidate, is_refinement=False):
                print(
                    f"[TEMPLATE_PRUNE_SKIP] template={candidate.template_id} family={candidate.family} "
                    f"expr={candidate.expression}"
                )
                continue

            if not self._candidate_allowed_by_diversity(candidate, is_refinement=False):
                print(
                    f"[DIVERSITY_SKIP] template={candidate.template_id} family={candidate.family} "
                    f"expr={candidate.expression}"
                )
                continue

            return candidate

        return None

    def _llm_candidate(self, settings_bias=None):
        """
        v5.6: Generate a candidate using LLM-guided expression generation.
        Returns a Candidate or None if LLM fails or expression is a duplicate.
        """
        # Gather context for the LLM prompt
        submitted_rows = self.storage.get_submitted_candidate_rows(limit=50)
        submitted_exprs = [r["canonical_expression"] for r in submitted_rows]

        # Get near-passers for the LLM to learn from
        # v6.2.1: Prioritize showing portfolio-additive near-passers to the LLM
        near_passers = []
        try:
            ref_rows = self.storage.get_similarity_reference_candidates(
                limit=20, min_sharpe=1.15, min_fitness=0.60,
            )
            additive_keywords = {
                "implied_volatility", "parkinson_volatility", "pcr_",
                "rp_ess_", "rp_css_", "news_", "scl12_", "snt1_d1_",
                "rel_ret_", "beta_last", "unsystematic_risk",
                # v6.2.1: vector/model/event data
                "vec_sum", "vec_avg", "vec_count", "buzzvec", "sentvec",
                "nws12_", "scl15_", "mdf_", "mdl175_", "fnd6_", "fam_",
                "days_from_last_change", "last_diff_value",
            }
            additive_passers = []
            other_passers = []
            for r in ref_rows:
                entry = {
                    "expression": r.get("canonical_expression", ""),
                    "sharpe": float(r.get("sharpe", 0) or 0),
                    "fitness": float(r.get("fitness", 0) or 0),
                    "reason": r.get("fail_reason", "") or "",
                }
                expr_lower = entry["expression"].lower()
                if any(kw in expr_lower for kw in additive_keywords):
                    additive_passers.append(entry)
                else:
                    other_passers.append(entry)
            # Show additive near-passers first, then fill with others
            near_passers = additive_passers[:4] + other_passers[:2]
        except Exception:
            pass

        # Determine which data categories are underexplored
        submitted_categories = set()
        for expr in submitted_exprs:
            submitted_categories.add(self._classify_data_source(expr))

        all_categories = {
            "options_vol", "sentiment", "fundamental", "factor_model",
            "price_returns", "price_volume", "volume_only",
            # v5.9: New data source categories
            "model77", "relationship", "risk_beta",
            "expanded_fundamental", "analyst_estimates",
            # v6.2.1: Added missing categories
            "news", "intraday",
            "vector_data", "model_data", "event_driven",
        }
        underexplored = sorted(all_categories - submitted_categories)

        # v7.0: Remove dead/blocked families from LLM exploration targets
        dead_families = set()
        try:
            if self.team_weights:
                dead_families = self.team_weights.get_dead_families()
        except Exception:
            pass
        # Map dead family names to LLM category names
        dead_category_map = {
            "model77_anomaly": "model77", "model77_combo": "model77",
            "relationship": "relationship", "risk_beta": "risk_beta",
            "model_data": "model_data", "event_driven": "event_driven",
        }
        dead_categories = {dead_category_map.get(f, f) for f in dead_families}
        underexplored = [c for c in underexplored if c not in dead_categories]

        # Get expression from LLM
        expr = self.llm_generator.get_expression(
            submitted_exprs=submitted_exprs,
            best_near_passers=near_passers,
            underexplored_categories=underexplored,
            recent_eligible_count=len(submitted_rows),
        )

        if expr is None:
            return None

        # v6.0: Dedup against recently simulated LLM expressions
        expr_normalized = expr.strip().lower()
        if expr_normalized in self.llm_simulated_expressions:
            print(f"[LLM_REPEAT_SKIP] expr={expr[:80]} - already simulated this session")
            return None
        self.llm_simulated_expressions.add(expr_normalized)

        # Create candidate from the raw expression
        try:
            candidate = self.generator.create_from_expression(
                expr, settings_bias=settings_bias,
                allow_delay0=getattr(config, "LLM_ALLOW_DELAY0", False),
            )
        except Exception as exc:
            print(f"[LLM_CANDIDATE_ERROR] expr={expr[:80]} error={exc}")
            return None

        # Check for duplicates
        if self.storage.candidate_exists(candidate.expression_hash):
            print(f"[LLM_DUP] expr={expr[:80]} - already exists")
            return None

        # v7.2.6: Check saturation - reject if expression uses 2+ saturated fields.
        # These almost always score negative against the existing portfolio.
        if self.generator._is_oversaturated(candidate.expression, is_delay0=getattr(candidate.settings, "delay", 1) == 0):
            print(f"[LLM_SATURATED] expr={expr[:80]} - uses 2+ portfolio-saturated fields")
            return None

        # Check concentrated weight blacklist
        if candidate.canonical_expression in self.concentrated_weight_exprs:
            print(f"[LLM_CW_BLOCKED] expr={expr[:80]}")
            return None

        # v5.8: Check field-level CW blacklist
        if self.concentrated_weight_fields:
            expr_lower = candidate.canonical_expression.lower()
            has_liq_weight = "rank(cap)" in expr_lower or "rank(adv20)" in expr_lower or "rank(adv" in expr_lower
            if not has_liq_weight:
                for field in self.concentrated_weight_fields:
                    if field in expr_lower:
                        print(f"[LLM_CW_FIELD_BLOCKED] field={field} expr={expr[:80]}")
                        return None

        print(
            f"[LLM_CANDIDATE] family={candidate.family} template={candidate.template_id} "
            f"expr={candidate.expression}"
        )
        return candidate

    def _combo_candidate(self, settings_bias=None):
        """
        v6.1: Generate a candidate by combining near-passers from different data categories.
        Three uncorrelated S=1.0 signals combine to S~1.46.
        """
        n_signals = 3 if self.generator.rng.random() < 0.30 else 2

        expr = self.signal_combiner.generate_combo(n_signals=n_signals)
        if expr is None:
            return None

        try:
            candidate = self.generator.create_from_expression(
                expr, settings_bias=settings_bias,
                allow_delay0=getattr(config, "COMBINER_ALLOW_DELAY0", False),
            )
        except Exception as exc:
            print(f"[COMBO_CANDIDATE_ERROR] expr={expr[:80]} error={exc}")
            return None

        # Dedup check
        if self.storage.candidate_exists(candidate.expression_hash):
            print(f"[COMBO_DUP] expr={expr[:80]}")
            return None

        # v7.2.6: Saturation check
        if self.generator._is_oversaturated(candidate.expression, is_delay0=getattr(candidate.settings, "delay", 1) == 0):
            print(f"[COMBO_SATURATED] expr={expr[:80]}")
            return None

        # CW blacklist check
        if candidate.canonical_expression in self.concentrated_weight_exprs:
            print(f"[COMBO_CW_BLOCKED] expr={expr[:80]}")
            return None

        # Override family/template for tracking
        candidate.family = "signal_combo"
        candidate.template_id = f"combo_{n_signals}s"

        print(
            f"[COMBO_CANDIDATE] n_signals={n_signals} family={candidate.family} "
            f"template={candidate.template_id} expr={candidate.expression}"
        )
        return candidate

    def _evolve_candidate(self, settings_bias=None):
        """
        v6.1: Generate a candidate by mutating a top-performing expression.
        FunSearch-inspired: LLM makes targeted modifications to near-passers.
        """
        submitted_rows = self.storage.get_submitted_candidate_rows(limit=50)
        submitted_exprs = [r["canonical_expression"] for r in submitted_rows]

        expr = self.evolver.evolve(submitted_exprs=submitted_exprs)
        if expr is None:
            return None

        try:
            candidate = self.generator.create_from_expression(
                expr, settings_bias=settings_bias,
                allow_delay0=getattr(config, "EVOLVER_ALLOW_DELAY0", False),
            )
        except Exception as exc:
            print(f"[EVOLVE_CANDIDATE_ERROR] expr={expr[:80]} error={exc}")
            return None

        if self.storage.candidate_exists(candidate.expression_hash):
            print(f"[EVOLVE_DUP] expr={expr[:80]}")
            return None

        # v7.2.6: Saturation check
        if self.generator._is_oversaturated(candidate.expression, is_delay0=getattr(candidate.settings, "delay", 1) == 0):
            print(f"[EVOLVE_SATURATED] expr={expr[:80]}")
            return None

        if candidate.canonical_expression in self.concentrated_weight_exprs:
            print(f"[EVOLVE_CW_BLOCKED] expr={expr[:80]}")
            return None

        # Track as evolved
        candidate.family = "evolved"
        candidate.template_id = "evolve_mut"

        print(
            f"[EVOLVE_CANDIDATE] family={candidate.family} "
            f"template={candidate.template_id} expr={candidate.expression}"
        )
        return candidate

    def _gap_candidate(self, settings_bias=None):
        """
        v7.2.1: Generate a candidate using the field-gap miner.
        Picks an unused field and plugs it into a proven expression pattern.
        """
        result = self.gap_miner.generate()
        if result is None:
            return None

        expr = result["expression"]

        try:
            candidate = self.generator.create_from_expression(
                expr, settings_bias=settings_bias,
            )
        except Exception as exc:
            print(f"[GAP_CANDIDATE_ERROR] expr={expr[:80]} error={exc}")
            return None

        if self.storage.candidate_exists(candidate.expression_hash):
            return None  # Silent skip - gap miner will rotate to next field

        if candidate.canonical_expression in self.concentrated_weight_exprs:
            return None

        # v7.2.6: Saturation check - gap mining shouldn't combine new fields with
        # already-saturated ones (e.g. ts_backfill(novel_field, 60) * rank(operating_income))
        if self.generator._is_oversaturated(candidate.expression, is_delay0=getattr(candidate.settings, "delay", 1) == 0):
            return None  # Silent skip

        # Override family/template to track gap mining performance
        candidate.family = result["family"]
        candidate.template_id = result["template_id"]
        candidate.fields = result["fields"]

        print(
            f"[GAP_MINING] field={result['params'].get('gap_field', '?')} "
            f"pattern={result['params'].get('pattern', '?')} "
            f"expr={candidate.expression[:90]}"
        )
        return candidate

    def _get_candidate_with_refinement_priority(self):
        last_base_tried = None

        # v7.2.1: Adaptive refinement drain - when queue is large,
        # shift sim budget heavily toward refinement to process it.
        # Check queue size every 25 completions to avoid hammering Supabase.
        if self.completed_runs % 25 == 0:
            try:
                pending = self.storage._get("refinement_queue", {
                    "consumed": "eq.false",
                    "select": "candidate_id",
                }) or []
                self._cached_queue_size = len(pending)
            except Exception:
                pass

        queue_size = getattr(self, "_cached_queue_size", 0)
        if queue_size > 50:
            refine_prob = 0.85  # Drain mode: 85% refinement
        else:
            refine_prob = config.REFINEMENT_PROBABILITY  # Normal: 55%

        for _ in range(8):
            refinement_row = None

            if self.generator.rng.random() < refine_prob:
                refinement_row = self.storage.get_next_refinement_candidate()

            if refinement_row is not None:
                base_candidate_id = refinement_row["candidate_id"]

                # v7.0: Track for graceful shutdown resume
                self._active_refinement_ids.add(base_candidate_id)

                # Avoid hammering the same base in a single tick
                if base_candidate_id == last_base_tried:
                    fresh = self._fresh_candidate()
                    if fresh is not None:
                        return fresh
                    continue
                last_base_tried = base_candidate_id

                # v6.0: Check CORE SIGNAL level exhaustion - prevents same expression
                # from being refined 50+ times via different candidate_ids
                max_core_refine = getattr(config, "MAX_REFINEMENT_PER_CORE", 15)
                core = self._extract_core_signal(refinement_row.get("canonical_expression", ""))

                # v7.2.11: Persistent dead-cores cache check - skip refinement
                # entirely on cores that already exhausted their full Optuna
                # budget (in any prior session) without producing positives.
                # 48h TTL means cores can re-enter the pool if portfolio shifts.
                if core:
                    try:
                        if self._dead_cores.is_dead(core):
                            self.storage.mark_refinement_consumed(base_candidate_id)
                            self._active_refinement_ids.discard(base_candidate_id)
                            print(f"[DEAD_CORE_SKIP] core='{core[:60]}' - refined to exhaustion in last 48h, skipping")
                            continue
                    except Exception:
                        pass  # cache failures must never block bot operation

                if core and self.refinement_attempts_by_core.get(core, 0) >= max_core_refine:
                    self.storage.mark_refinement_consumed(base_candidate_id)
                    self._active_refinement_ids.discard(base_candidate_id)
                    # v7.2: Also mark core as exhausted so pre-check catches it
                    self.core_signal_exhausted[core] = self.core_signal_exhausted.get(core, 0) + 1
                    # v7.2.11: Persistent record - only mark dead if no positive
                    # variants produced (i.e. core is also in _score_negative_cores
                    # OR never produced any positive). Cores that produced positives
                    # at some point shouldn't be permanently skipped.
                    try:
                        is_known_negative = core in self._score_negative_cores
                        # If we've cycled through max_core_refine attempts without
                        # the core ever appearing in the positive-results path,
                        # treat as dead. The presence in _score_negative_cores is
                        # the strongest signal we have.
                        if is_known_negative:
                            self._dead_cores.mark_dead(core)
                            print(f"[DEAD_CORE_RECORD] core='{core[:60]}' - exhausted with all-negative variants, cached for 48h")
                    except Exception:
                        pass
                    print(f"[CORE_REFINE_CAP] core='{core[:60]}' attempts={self.refinement_attempts_by_core[core]} - skipping")
                    continue

                # v6.2: Skip if core already rejected by WQ self-correlation
                # v6.2.1: EXCEPT sweep candidates - different universes may pass
                # v7.2.7: ALSO skip the block for d=0 refinements - d=0 lives in
                # a separate self-corr space, so d=1 SC rejections don't apply.
                is_sweep_refine = str(refinement_row.get("template_id", "")).startswith("sweep_")
                try:
                    _refine_settings_str = refinement_row.get("settings_json", "{}")
                    _refine_settings = _json.loads(_refine_settings_str) if isinstance(_refine_settings_str, str) else (_refine_settings_str or {})
                    _refine_is_d0 = int(_refine_settings.get("delay", 1)) == 0
                except Exception:
                    _refine_is_d0 = False

                if core and core in self.rejected_cores and not is_sweep_refine and not _refine_is_d0:
                    self.storage.mark_refinement_consumed(base_candidate_id)
                    self._active_refinement_ids.discard(base_candidate_id)
                    print(f"[REFINE_SKIP_CORR] core='{core[:60]}' - already rejected by WQ, skipping refinement")
                    continue

                # v6.2: Skip if core already produced negative score changes
                # v6.2.1: EXCEPT sweep candidates - different universes may have positive score change
                # v7.2.7: ALSO skip the block for d=0 refinements (different scoring space)
                if core and core in self._score_negative_cores and not is_sweep_refine and not _refine_is_d0:
                    self.storage.mark_refinement_consumed(base_candidate_id)
                    self._active_refinement_ids.discard(base_candidate_id)
                    print(f"[REFINE_SKIP_SCORE] core='{core[:60]}' - negative score change, skipping refinement")
                    continue

                if self._should_abandon_refinement_base(base_candidate_id):
                    self.storage.mark_refinement_consumed(base_candidate_id)
                    self._active_refinement_ids.discard(base_candidate_id)
                    self.refinement_attempts_by_base.pop(base_candidate_id, None)

                    # Track core signal exhaustion to prevent infinite re-queuing
                    core = self._extract_core_signal(refinement_row.get("canonical_expression", ""))
                    if core:
                        self.core_signal_exhausted[core] = self.core_signal_exhausted.get(core, 0) + 1

                    # Track family+template exhaustion to cap entire template families
                    ft_key = f"{refinement_row['family']}:{refinement_row['template_id']}"
                    self.family_template_exhausted[ft_key] = self.family_template_exhausted.get(ft_key, 0) + 1
                    ft_count = self.family_template_exhausted[ft_key]

                    print(
                        f"[REFINEMENT_EXHAUSTED] base_candidate_id={base_candidate_id} "
                        f"template={refinement_row['template_id']} family={refinement_row['family']} "
                        f"ft_exhaustions={ft_count}"
                    )
                    continue

                metrics_hint = {
                    "sharpe": refinement_row["base_sharpe"],
                    "fitness": refinement_row["base_fitness"],
                    "turnover": refinement_row["base_turnover"],
                }

                # v6.0: Use Optuna for fitness near-passers (high Sharpe, low fitness)
                use_optuna = (
                    self.settings_optimizer is not None
                    and float(refinement_row.get("base_sharpe", 0) or 0) >= 1.25
                    and float(refinement_row.get("base_fitness", 0) or 0) < 1.0
                    and float(refinement_row.get("base_fitness", 0) or 0) >= 0.70
                    and self.generator.rng.random() < 0.60  # 60% Optuna, 40% normal mutation
                )

                if use_optuna:
                    suggested = self.settings_optimizer.suggest(
                        expression=refinement_row.get("canonical_expression", ""),
                        core_signal=core or "",
                        family=refinement_row.get("family", ""),
                    )
                    if suggested:
                        # Create candidate with same expression but Optuna-suggested settings
                        try:
                            candidate = self.generator.create_from_expression(
                                refinement_row["canonical_expression"],
                                settings_override=suggested,
                            )
                            # v6.0: Preserve original family/template for tracking
                            candidate.family = refinement_row.get("family", candidate.family)
                            candidate.template_id = refinement_row.get("template_id", candidate.template_id)
                            print(
                                f"[OPTUNA_REFINE] base={base_candidate_id[:30]} "
                                f"family={candidate.family} template={candidate.template_id} "
                                f"S={refinement_row['base_sharpe']:.2f} F={refinement_row['base_fitness']:.2f} "
                                f"-> univ={suggested['universe']} neut={suggested['neutralization']} "
                                f"decay={suggested['decay']} delay={suggested.get('delay', 1)} trunc={suggested['truncation']}"
                            )
                        except Exception as exc:
                            print(f"[OPTUNA_FAIL] {exc}")
                            candidate = self.generator.mutate_candidate(refinement_row, metrics_hint=metrics_hint)
                    else:
                        candidate = self.generator.mutate_candidate(refinement_row, metrics_hint=metrics_hint)
                else:
                    candidate = self.generator.mutate_candidate(refinement_row, metrics_hint=metrics_hint)

                self.refinement_attempts_by_base[base_candidate_id] = (
                    self.refinement_attempts_by_base.get(base_candidate_id, 0) + 1
                )
                # v6.0: Track core-level refinement attempts
                if core:
                    self.refinement_attempts_by_core[core] = (
                        self.refinement_attempts_by_core.get(core, 0) + 1
                    )

                print(
                    f"[REFINING] base_candidate_id={base_candidate_id} "
                    f"template={refinement_row['template_id']} family={refinement_row['family']} "
                    f"new_template={candidate.template_id} new_family={candidate.family} "
                    f"expr={candidate.expression}"
                )

                if self.storage.candidate_exists(candidate.expression_hash):
                    continue

                if not self._passes_local_refinement_filter(base_candidate_id, candidate):
                    continue

                if not self._candidate_allowed_by_template_quality(candidate, is_refinement=True):
                    print(
                        f"[TEMPLATE_PRUNE_SKIP] template={candidate.template_id} family={candidate.family} "
                        f"expr={candidate.expression}"
                    )
                    continue

                if not self._candidate_allowed_by_diversity(candidate, is_refinement=True):
                    # v6.2: Track consecutive diversity skips - fast-exhaust after 2
                    self._diversity_skip_count[base_candidate_id] = (
                        self._diversity_skip_count.get(base_candidate_id, 0) + 1
                    )
                    if self._diversity_skip_count[base_candidate_id] >= 2:
                        self.storage.mark_refinement_consumed(base_candidate_id)
                        self._active_refinement_ids.discard(base_candidate_id)
                        self.refinement_attempts_by_base.pop(base_candidate_id, None)
                        self._diversity_skip_count.pop(base_candidate_id, None)
                        print(
                            f"[DIVERSITY_EXHAUST] base={base_candidate_id[:30]} "
                            f"- 2+ diversity skips, consuming"
                        )
                    else:
                        print(
                            f"[DIVERSITY_SKIP] template={candidate.template_id} family={candidate.family} "
                            f"expr={candidate.expression}"
                        )
                    continue

                # v7.0: Record lineage - if child becomes a near-passer, parent gets consumed
                self._remember_local_refinement(base_candidate_id, candidate.expression_hash)
                self._refinement_lineage[candidate.candidate_id] = base_candidate_id
                return candidate

            fresh = self._fresh_candidate()
            if fresh is not None:
                return fresh

        return None

    # Submission loop

    def _fill_capacity(self) -> None:
        import time as _time
        # v7.2: Skip if in rate-limit cooldown (cleared when a completion frees a slot)
        if _time.time() < self._rate_limit_until:
            return

        attempts = 0
        max_attempts = 12

        # v7.2: Retry rate-limited submissions from previous ticks
        retry_queue = list(self._rate_limited_queue)
        self._rate_limited_queue.clear()
        for candidate, run in retry_queue:
            if not self.scheduler.has_capacity():
                self._rate_limited_queue.append((candidate, run))
                continue
            try:
                sim_id = self.client.submit_simulation(
                    candidate.expression, candidate.settings.to_dict(),
                )
                self.storage.update_run(
                    run.run_id, sim_id=sim_id, status="submitted",
                    submitted_at=utc_now(), error_message=None,
                )
                self.scheduler.add(sim_id, run.run_id)
                print(
                    f"[SIM_RETRY_OK] run_id={run.run_id} sim_id={sim_id} "
                    f"template={candidate.template_id} family={candidate.family}"
                )
            except Exception:
                # Still rate limited - re-queue
                self._rate_limited_queue.append((candidate, run))
                break

        # v6.2.1: Universe sweeps - max 1 per tick to leave capacity for exploration
        sweep_submitted = 0
        sweep_max_per_tick = 1
        while self.scheduler.has_capacity() and self.universe_sweeper.pending > 0 and sweep_submitted < sweep_max_per_tick:
            sweep = self.universe_sweeper.try_sweep()
            if sweep is None:
                break
            try:
                from canonicalize import canonicalize_expression, hash_candidate
                from models import Candidate, SimulationSettings

                settings = SimulationSettings(**sweep["settings"])
                canon = canonicalize_expression(sweep["expression"])
                expr_hash = hash_candidate(canon, settings.to_dict())

                # Skip if already tested with these exact settings
                if self.storage.candidate_exists(expr_hash):
                    continue

                cand = Candidate.create(
                    expression=sweep["expression"],
                    canonical_expression=canon,
                    expression_hash=expr_hash,
                    template_id=sweep.get("template_id", "sweep"),
                    family=sweep.get("family", "sweep"),
                    fields=[],
                    params={},
                    settings=settings,
                )
                self.storage.insert_candidate(cand)
                run = Run.create(candidate_id=cand.candidate_id, status="pending")
                self.storage.insert_run(run)

                sim_id = self.client.submit_simulation(
                    cand.expression, cand.settings.to_dict()
                )
                self.storage.update_run(
                    run.run_id, sim_id=sim_id, status="submitted", submitted_at=utc_now()
                )
                self.scheduler.add(sim_id, run.run_id)
                sweep_submitted += 1
                self.universe_sweeper.count_sweep()
                print(
                    f"[SWEEP_SUBMITTED] run_id={run.run_id} universe={sweep['settings']['universe']} "
                    f"neut={sweep['settings']['neutralization']} decay={sweep['settings']['decay']} "
                    f"family={sweep.get('family', '')} expr={sweep['expression'][:60]}..."
                )
            except Exception as exc:
                print(f"[SWEEP_ERROR] {exc}")
                break

        while self.scheduler.has_capacity() and attempts < max_attempts:
            attempts += 1

            candidate = self._get_candidate_with_refinement_priority()
            if candidate is None:
                continue

            if self.storage.candidate_exists(candidate.expression_hash):
                continue

            # v5.5: Block expressions known to fail CONCENTRATED_WEIGHT
            # CONCENTRATED_WEIGHT is expression-level (data coverage), not settings-level.
            # Changing decay/truncation/universe won't fix it - only expression changes will.
            if candidate.canonical_expression in self.concentrated_weight_exprs:
                print(
                    f"[CW_BLOCKED] template={candidate.template_id} family={candidate.family} "
                    f"expr={candidate.expression} - already failed CONCENTRATED_WEIGHT"
                )
                continue

            # v5.8: Block expressions using CW-flagged fields without liquidity weighting
            if self.concentrated_weight_fields:
                expr_lower = candidate.canonical_expression.lower()
                has_liq_weight = "rank(cap)" in expr_lower or "rank(adv20)" in expr_lower or "rank(adv" in expr_lower
                if not has_liq_weight:
                    blocked_field = None
                    for field in self.concentrated_weight_fields:
                        if field in expr_lower:
                            blocked_field = field
                            break
                    if blocked_field:
                        print(
                            f"[CW_FIELD_BLOCKED] template={candidate.template_id} family={candidate.family} "
                            f"field={blocked_field} - unweighted field known to cause CW"
                        )
                        continue

            # v6.2: Hard-block candidates sharing core with 2+ already-submitted alphas.
            # WQ's self-correlation check almost always rejects variants of well-covered cores.
            # Saves ~15-20 wasted sims per overnight run.
            # v7.2.7: d=0 candidates skip this block - passed_cores tracks team
            # submissions which are predominantly d=1, and d=0 lives in a separate
            # self-corr space. We'd be over-blocking valid d=0 alphas otherwise.
            _cand_is_d0 = getattr(candidate.settings, "delay", 1) == 0
            if self.passed_cores and not _cand_is_d0:
                core = self._extract_core_signal(candidate.canonical_expression)
                if core and self.passed_cores.get(core, 0) >= 2:
                    print(
                        f"[CORE_OVERLAP_BLOCK] template={candidate.template_id} family={candidate.family} "
                        f"core='{core[:60]}' - {self.passed_cores[core]} already submitted, BLOCKING"
                    )
                    continue
                elif core and self.passed_cores.get(core, 0) == 1:
                    print(
                        f"[CORE_OVERLAP] template={candidate.template_id} family={candidate.family} "
                        f"core='{core[:60]}' - 1 already submitted, allowing variant"
                    )

            # v7.2: Pre-submission field validation - catch snt1_d1_ on team, LLM hallucinations, etc.
            from datasets import expression_uses_valid_fields, get_all_valid_fields
            if not expression_uses_valid_fields(candidate.expression):
                # Extract which fields are missing for the log
                _valid = {f.lower() for f in get_all_valid_fields()}
                _tokens = set(re.findall(r'[a-z][a-z0-9_]+', candidate.expression.lower()))
                _ops = {'rank','group_rank','ts_mean','ts_std_dev','ts_zscore','ts_rank','ts_delta',
                        'ts_decay_linear','ts_corr','ts_sum','ts_backfill','ts_regression','ts_step',
                        'ts_delay','ts_scale','ts_arg_min','ts_arg_max','ts_covariance','ts_product',
                        'ts_count_nans','ts_quantile','ts_av_diff','trade_when','if_else','abs','log',
                        'sign','max','min','power','sqrt','is_nan','bucket','densify','winsorize',
                        'normalize','group_neutralize','group_zscore','group_scale','group_backfill',
                        'group_mean','scale','quantile','zscore','vec_avg','vec_sum','signed_power',
                        'inverse','reverse','hump','kth_element','range','true','false','rettype',
                        'industry','subindustry','sector','market','exchange','not','and','or',
                        'days_from_last_change','last_diff_value','lag','std'}
                _missing = [t for t in _tokens - _ops if t not in _valid and len(t) > 3]
                print(
                    f"[FIELD_BLOCK] template={candidate.template_id} family={candidate.family} "
                    f"missing={_missing[:3]} - skipping"
                )
                continue

            # v6.2.1: Pre-sim operator count - must match WQ's counting method
            # WQ counts: function calls + arithmetic (+,-,*,/) + comparisons (>,<,>=,<=,!=,==)
            _expr = candidate.expression
            op_count = (
                len(re.findall(r'\b[a-z_]+\s*\(', _expr))  # function calls
                + len(re.findall(r'(?<![!=<>])[+\-*/](?![!=])', _expr))  # arithmetic ops
                + len(re.findall(r'[<>]=?|[!=]=', _expr))  # comparison ops
            )
            if op_count > 60:  # WQ limit is 64, leave small margin
                print(
                    f"[OP_LIMIT_BLOCK] ops={op_count} template={candidate.template_id} "
                    f"family={candidate.family} expr={candidate.expression[:80]}"
                )
                continue

            try:
                self.storage.insert_candidate(candidate)
            except Exception as exc:
                print(f"[CANDIDATE_INSERT_ERROR] candidate_id={candidate.candidate_id} error={exc}")
                continue

            run = Run.create(candidate_id=candidate.candidate_id, status="pending")
            self.storage.insert_run(run)

            try:
                sim_id = self.client.submit_simulation(
                    candidate.expression,
                    candidate.settings.to_dict(),
                )

                now = utc_now()
                self.storage.update_run(
                    run.run_id,
                    sim_id=sim_id,
                    status="submitted",
                    submitted_at=now,
                )
                self.scheduler.add(sim_id, run.run_id)

                print(
                    f"[SUBMITTED_SIM] run_id={run.run_id} sim_id={sim_id} "
                    f"template={candidate.template_id} family={candidate.family} "
                    f"expr={candidate.expression}"
                )

            except BrainAPIError as exc:
                # v7.2: On rate limit, queue for retry and cooldown to prevent spin loop
                if "429" in str(exc) or "CONCURRENT" in str(exc).upper():
                    self.storage.update_run(
                        run.run_id,
                        status="pending",
                        error_message=f"rate_limited:{str(exc)[:100]}",
                    )
                    self._rate_limited_queue.append((candidate, run))
                    self._rate_limit_until = _time.time() + 30  # 30s cooldown
                    print(f"[SIM_RATE_LIMITED] run_id={run.run_id} - queued for retry, cooling down 30s")
                    break

                self.storage.update_run(
                    run.run_id,
                    status="failed",
                    completed_at=utc_now(),
                    error_message=str(exc),
                )
                print(f"[SIM_SUBMIT_ERROR] run_id={run.run_id} error={exc}")

                # v5.6.1: Record LLM failures for feedback
                if (self.llm_generator.available
                        and str(candidate.template_id).startswith("llm_")):
                    self.llm_generator.record_failure(
                        expression=candidate.expression,
                        error=f"WQ_API_ERROR: {str(exc)[:100]}",
                    )

            except Exception as exc:
                self.storage.update_run(
                    run.run_id,
                    status="failed",
                    completed_at=utc_now(),
                    error_message=str(exc),
                )
                print(f"[SIM_SUBMIT_UNEXPECTED] run_id={run.run_id} error={exc}")

    # Recovery / timeout

    def recover_running_from_storage(self) -> None:
        rows = self.storage.get_running_runs()
        recovered = 0

        for row in rows:
            sim_id = row["sim_id"]
            run_id = row["run_id"]

            if sim_id and not self.scheduler.is_running(sim_id):
                self.scheduler.add(sim_id, run_id)
                recovered += 1

        if recovered:
            print(f"[RECOVERED] restored {recovered} running simulations from storage")

    def mark_stale_runs_timed_out(self) -> None:
        """v7.2.1: Fixed to check BOTH 'running' and 'submitted' status in DB,
        AND also sweep the in-memory scheduler for sims that have been active
        longer than the timeout. The original only queried status=running,
        but stuck sims stay in status=submitted - so they were invisible."""
        cutoff = utc_now() - timedelta(minutes=config.SIM_TIMEOUT_MINUTES)
        stale_count = 0

        # Method 1: DB-based sweep (catches both statuses)
        for status_val in ("running", "submitted"):
            try:
                rows = self.storage._get("runs", {
                    "status": f"eq.{status_val}",
                    "owner": f"eq.{self.storage.owner}",
                    "select": "run_id,sim_id,submitted_at",
                }) or []
            except Exception:
                rows = []

            for row in rows:
                submitted_at = row.get("submitted_at")
                if not submitted_at:
                    continue
                try:
                    submitted_dt = self.storage.parse_dt(submitted_at)
                except Exception:
                    continue
                if submitted_dt < cutoff:
                    run_id = row["run_id"]
                    sim_id = row.get("sim_id")
                    self.storage.update_run(
                        run_id,
                        status="timed_out",
                        completed_at=utc_now(),
                        error_message=f"Marked stale by timeout sweep (was {status_val}).",
                    )
                    if sim_id:
                        self.scheduler.remove(sim_id)
                    stale_count += 1

        # Method 2: Scheduler-based sweep - catch anything the DB missed
        # (e.g. if DB update succeeded but scheduler.remove didn't)
        for sim_id, run_id in list(self.scheduler.active_items()):
            try:
                run_row = self.storage._get("runs", {
                    "run_id": f"eq.{run_id}",
                    "select": "status,submitted_at",
                })
                if run_row:
                    r = run_row[0]
                    if r.get("status") in ("timed_out", "completed", "failed"):
                        # DB says done but scheduler still has it - orphaned slot
                        self.scheduler.remove(sim_id)
                        stale_count += 1
                        continue
                    sa = r.get("submitted_at")
                    if sa:
                        try:
                            sa_dt = self.storage.parse_dt(sa)
                            if sa_dt < cutoff:
                                self.storage.update_run(
                                    run_id, status="timed_out",
                                    completed_at=utc_now(),
                                    error_message="Stale sweep: scheduler orphan.",
                                )
                                self.scheduler.remove(sim_id)
                                stale_count += 1
                        except Exception:
                            pass
            except Exception:
                pass

        if stale_count:
            print(f"[STALE_SWEEP] marked {stale_count} runs as timed_out")

    # Reporting

    def _print_progress_report(self) -> None:
        print("\n[REPORT] recent family stats")
        family_rows = self.storage.get_recent_family_stats(limit=500)

        if not family_rows:
            print("No completed family stats yet.\n")
            return

        for row in family_rows:
            family = row["family"]
            n_runs = row["n_runs"]
            avg_sharpe = row["avg_sharpe"]
            avg_fitness = row["avg_fitness"]
            avg_turnover = row["avg_turnover"]
            submit_rate = row["submit_rate"]

            def fmt(x):
                return "None" if x is None else f"{x:.3f}"

            print(
                f"family={family:<16} "
                f"n={n_runs:<4} "
                f"avg_sharpe={fmt(avg_sharpe):<8} "
                f"avg_fitness={fmt(avg_fitness):<8} "
                f"avg_turnover={fmt(avg_turnover):<8} "
                f"submit_rate={fmt(submit_rate):<8}"
            )

        print("\n[REPORT] recent template stats")
        template_rows = self.storage.get_recent_template_stats(limit=config.TEMPLATE_SCORE_LOOKBACK_RUNS)

        shown = 0
        for row in template_rows:
            template_id = row["template_id"]
            family = row["family"]
            n_runs = row["n_runs"]
            avg_sharpe = row["avg_sharpe"]
            avg_fitness = row["avg_fitness"]
            avg_turnover = row["avg_turnover"]
            quality = self._template_quality_class(template_id)

            def fmt(x):
                return "None" if x is None else f"{x:.3f}"

            print(
                f"template={template_id:<8} "
                f"family={family:<14} "
                f"n={n_runs:<4} "
                f"avg_sharpe={fmt(avg_sharpe):<8} "
                f"avg_fitness={fmt(avg_fitness):<8} "
                f"avg_turnover={fmt(avg_turnover):<8} "
                f"quality={quality}"
            )

            shown += 1
            if shown >= 12:
                break

        # Submission portfolio status
        submitted_families = self._get_submitted_family_set()
        submitted_templates = self._get_submitted_template_set()
        eligible_rows = self.storage.get_submission_eligible_candidates(limit=50)

        print(f"\n[REPORT] submission portfolio")
        print(f"  submitted_families={sorted(submitted_families) if submitted_families else 'none'}")
        print(f"  submitted_templates={sorted(submitted_templates) if submitted_templates else 'none'}")
        print(f"  eligible_not_yet_submitted={len(eligible_rows)}")

        # Show which families need eligible alphas for diversity
        all_productive = {"mean_reversion", "volume_flow", "conditional", "vol_adjusted"}
        missing = all_productive - submitted_families
        if missing:
            print(f"  diversity_gaps={sorted(missing)} - boost these for portfolio diversity")

        # v6.2.1: Universe sweep stats
        if self.universe_sweeper:
            print(f"  universe_sweeps_pending={self.universe_sweeper.pending} total_swept={self.universe_sweeper.total_sweeps}")

        # v5.5: Settings performance report
        settings_bias = self._settings_bias_map()
        if settings_bias:
            print(f"\n[REPORT] settings adaptive weights")
            for dim in ["universe", "neutralization", "decay", "truncation"]:
                dim_bias = settings_bias.get(dim, {})
                if dim_bias:
                    sorted_items = sorted(dim_bias.items(), key=lambda x: x[1], reverse=True)
                    parts = [f"{k}={v:.2f}" for k, v in sorted_items]
                    print(f"  {dim}: {', '.join(parts)}")

        # v5.6.1: LLM generation stats
        if self.llm_generator.available:
            llm_stats = self.llm_generator.stats()
            print(
                f"\n[REPORT] LLM generation"
                f"\n  api_calls={llm_stats['total_api_calls']} "
                f"generated={llm_stats['total_generated']} "
                f"valid={llm_stats['total_valid']} "
                f"failed_calls={llm_stats['total_failed_calls']} "
                f"cached={llm_stats['cache_size']} "
                f"tracked_failures={llm_stats['tracked_failures']}"
            )

        print()