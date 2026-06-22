"""Warm-started Bayesian settings optimizer using Optuna TPE.

When a near-passer alpha (high sharpe, low fitness) is stuck, this module uses
historical sim data to intelligently suggest the next settings combo instead of
random sampling.

Usage in bot.py:
    from settings_optimizer import SettingsOptimizer
    optimizer = SettingsOptimizer(storage)
    suggested_settings = optimizer.suggest(expression, current_metrics)
"""
from __future__ import annotations

try:
    import optuna
    from optuna.samplers import TPESampler
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    OPTUNA_AVAILABLE = True
except ImportError:
    OPTUNA_AVAILABLE = False


# BRAIN settings search space
UNIVERSES = ["TOP200", "TOP500", "TOP1000", "TOP2000", "TOP3000", "TOPSP500"]
NEUTRALIZATIONS = ["NONE", "MARKET", "SECTOR", "INDUSTRY", "SUBINDUSTRY"]
DECAYS = [0, 2, 4, 6, 8, 10, 12]
TRUNCATIONS = [0.01, 0.03, 0.05, 0.08, 0.10]




def expression_delay0_safe(expression: str) -> bool:
    """Conservative delay-0 safety check.

    Delay-0 alphas should not use same-day price/return tokens directly. these
    tokens are allowed when inside explicit time-series wrappers such as
    ts_mean(...), ts_rank(...), ts_delta(...), ts_delay(...). intentionally
    conservative: false negatives cost a sim; false positives create useless d0 sweeps.

    When D0_ONLY_MODE is on the rule is relaxed for `open`, `high`, `low`,
    `close`, and `vwap` because WQ's official D=0 docs explicitly recommend
    using them (open price, for example, is a good source for potential
    signals). raw `returns` (end-of-day computed return) is still treated as
    risky and required to be inside a ts_* wrapper. this matches the templates
    from the D=0 research brief, which deliberately use bare `open`/`close`/`vwap`
    as same-day intraday-snapshot signals.
    """
    if not expression:
        return False
    import re
    expr_l = expression.lower()

    try:
        import config as _cfg
        _d0_only = getattr(_cfg, "D0_ONLY_MODE", False)
    except Exception:
        _d0_only = False

    if _d0_only:
        # in D0_ONLY_MODE we trust the curated research-brief D=0 templates, which
        # deliberately use bare `open`/`close`/`vwap`/`returns` as same-day
        # intraday-snapshot signals (per WQ docs, -rank(returns) * rank(volume) is
        # a published USA D=0 pattern). the user opted in via D0_ONLY_MODE; the
        # safety check would otherwise block 24 of the 44 hand-picked templates.
        return True

    def strip_ts_wrappers(s: str) -> str:
        prev = None
        for _ in range(12):
            if s == prev:
                break
            prev = s
            s = re.sub(r'ts_[a-z_]+\([^()]*\)', '', s)
        return s

    risky = {"returns", "close", "open", "high", "low", "vwap"}
    stripped = strip_ts_wrappers(expr_l)
    for tok in risky:
        if re.search(rf'\b{tok}\b', stripped):
            return False
    return True


def _delay_choices_for_expression(expression: str) -> list[int]:
    """Return [0, 1] for d0-safe expressions, else [1].

    When config.D0_ONLY_MODE is True, force [0] for d0-safe expressions, else
    return empty (the candidate will be skipped at the OPTIMIZE_SKIP_D0 gate).
    this guarantees the entire bot operates exclusively at delay=0 during
    overnight D0 hunting runs.
    """
    try:
        import config as _cfg
        _d0_only = getattr(_cfg, "D0_ONLY_MODE", False)
    except Exception:
        _d0_only = False

    if _d0_only:
        # strict: only delay=0 for safe exprs. d1-only exprs get [] which signals "skip".
        return [0] if expression_delay0_safe(expression) else []

    return [0, 1] if expression_delay0_safe(expression) else [1]


class SettingsOptimizer:
    """
    Bayesian optimizer for BRAIN simulation settings.
    Warm-starts from historical sim data to find optimal settings in 3-5 trials.
    """

    def __init__(self, storage=None):
        self.storage = storage

    def suggest(
        self,
        expression: str,
        core_signal: str = "",
        family: str = "",
        target_metric: str = "fitness",
    ) -> dict | None:
        """
        Suggest next settings to try for a given expression.
        Returns a settings dict or None if no suggestion available.
        """
        if not OPTUNA_AVAILABLE:
            return None

        # create study with TPE sampler, warm-started.
        # n_startup_trials=2 forces some random exploration before TPE takes over.
        # pure warm-start TPE was causing identical suggestions across multiple
        # suggest() calls when historical trials had converged.
        study = optuna.create_study(
            direction="maximize",
            sampler=TPESampler(
                multivariate=False,
                warn_independent_sampling=False,
                n_startup_trials=2,
                n_ei_candidates=32,
            ),
        )

        # warm-start from historical data
        n_warm = self._inject_historical_trials(study, expression, core_signal, family, target_metric)

        if n_warm < 3:
            # not enough history to guide optimization - fall back to None
            return None

        # ask Optuna for next suggestion
        trial = study.ask()
        settings = self._trial_to_settings(trial, expression)

        # robust dedup - collect all historical combos, retry up to 10 times.
        # include delay in the dedup key so d0 and d1 of the same combo are distinct.
        tried_combos = set()
        for t in study.trials:
            if t.state == optuna.trial.TrialState.COMPLETE:
                combo = (
                    t.params.get("universe"),
                    t.params.get("neutralization"),
                    t.params.get("decay"),
                    t.params.get("truncation"),
                    t.params.get("delay", 1),
                )
                tried_combos.add(combo)

        suggested_combo = (
            settings["universe"],
            settings["neutralization"],
            settings["decay"],
            settings["truncation"],
            settings.get("delay", 1),
        )

        # if duplicate, keep asking (up to 10 retries) before giving up
        max_dedup_retries = 10
        retries = 0
        while suggested_combo in tried_combos and retries < max_dedup_retries:
            study.tell(trial, 0.0)  # report dummy value
            trial = study.ask()
            settings = self._trial_to_settings(trial, expression)
            suggested_combo = (
                settings["universe"],
                settings["neutralization"],
                settings["decay"],
                settings["truncation"],
                settings.get("delay", 1),
            )
            retries += 1

        if suggested_combo in tried_combos:
            # exhausted search space - no novel suggestions left
            return None

        print(
            f"[OPTUNA] Suggested settings (warm={n_warm}): "
            f"univ={settings['universe']} neut={settings['neutralization']} "
            f"decay={settings['decay']} delay={settings.get('delay', 1)} "
            f"trunc={settings['truncation']}"
        )
        return settings

    def suggest_batch(
        self,
        expression: str,
        n: int,
        core_signal: str = "",
        family: str = "",
        target_metric: str = "fitness",
    ) -> list[dict]:
        """
        Suggest N distinct settings variants in a single study session.

        Why this exists: calling suggest() N times creates N independent studies,
        each warm-started identically. when historical trials are saturated, every
        fresh study converges to the same TPE recommendation, producing N identical
        suggestions and only 1-2 unique variants. by keeping one study across all N
        suggestions and using study.tell() with a dummy score after each ask(),
        Optuna's internal state remembers what's been tried and won't repeat itself.

        Returns: list of distinct settings dicts (may be shorter than n if the
        search space is exhausted).
        """
        if not OPTUNA_AVAILABLE:
            return []

        # short-circuit if D0_ONLY_MODE is on and the expression isn't D=0-safe.
        # the candidate should have been gated upstream, but defense-in-depth here.
        try:
            import config as _cfg
            if getattr(_cfg, "D0_ONLY_MODE", False) and not _delay_choices_for_expression(expression):
                print(f"[OPTUNA] D0_ONLY_MODE - expression is D=1-only, skipping suggest_batch entirely")
                return []
        except Exception:
            pass

        # single study for the whole batch - startup_trials=2 ensures some random
        # exploration even when warm-start data is heavily clustered
        study = optuna.create_study(
            direction="maximize",
            sampler=TPESampler(
                multivariate=False,
                warn_independent_sampling=False,
                n_startup_trials=2,
                n_ei_candidates=32,
            ),
        )

        n_warm = self._inject_historical_trials(study, expression, core_signal, family, target_metric)

        if n_warm < 3:
            # not enough warm-start - fall back to None so caller can use mutator
            return []

        suggestions: list[dict] = []
        seen_combos: set = set()
        # pre-populate seen_combos with all warm-start trials
        for t in study.trials:
            if t.state == optuna.trial.TrialState.COMPLETE:
                seen_combos.add((
                    t.params.get("universe"),
                    t.params.get("neutralization"),
                    t.params.get("decay"),
                    t.params.get("truncation"),
                    t.params.get("delay", 1),
                ))

        # ask for n variants. use a generous attempt budget so we can skip dupes.
        max_attempts = n * 5
        attempts = 0
        while len(suggestions) < n and attempts < max_attempts:
            attempts += 1
            trial = study.ask()
            settings = self._trial_to_settings(trial, expression)
            combo = (
                settings["universe"],
                settings["neutralization"],
                settings["decay"],
                settings["truncation"],
                settings.get("delay", 1),
            )
            if combo in seen_combos:
                # tell the study with a low value so TPE moves away from this combo
                study.tell(trial, 0.0)
                continue

            seen_combos.add(combo)
            suggestions.append(settings)
            # tell the study with a placeholder value - we don't have real results
            # yet (will only know after sims complete). the placeholder encourages
            # TPE to explore other regions on subsequent asks.
            study.tell(trial, 0.5)

            print(
                f"[OPTUNA] Variant {len(suggestions)}/{n} (warm={n_warm}): "
                f"univ={settings['universe']} neut={settings['neutralization']} "
                f"decay={settings['decay']} delay={settings.get('delay', 1)} "
                f"trunc={settings['truncation']}"
            )

        if len(suggestions) < n:
            print(f"[OPTUNA] Search space exhausted - got {len(suggestions)}/{n} unique variants")

        return suggestions

    def _trial_to_settings(self, trial, expression: str = "") -> dict:
        """Convert an Optuna trial to a BRAIN settings dict.

        delay is part of the search space. it explicitly chooses [0, 1] for
        expressions that are safe at delay=0 (no raw returns/close at top level) -
        d0 alphas score 1/3 the points but live in a separate self-corr space,
        valuable when the portfolio is saturated. for unsafe expressions, delay is
        locked at 1.
        """
        delay_choices = _delay_choices_for_expression(expression)

        # in D0_ONLY_MODE, restrict Optuna search to the D0-recommended ranges from
        # the research brief. otherwise historical D=1 trials inject decay=12 /
        # trunc=0.01 which contradict D0 best practice.
        try:
            import config as _cfg
            _d0_only = getattr(_cfg, "D0_ONLY_MODE", False)
        except Exception:
            _d0_only = False

        if _d0_only:
            d0_universes = getattr(_cfg, "DELAY0_UNIVERSES",
                                   ["TOP500", "TOP1000", "TOP200", "TOPSP500", "TOP2000", "TOP3000"])
            d0_neutralizations = getattr(_cfg, "DELAY0_NEUTRALIZATIONS",
                                         ["SUBINDUSTRY", "INDUSTRY", "SECTOR", "MARKET", "NONE"])
            d0_decays = getattr(_cfg, "DELAY0_DECAYS", [0, 2, 4, 6, 9])
            d0_truncations = getattr(_cfg, "DELAY0_TRUNCATIONS",
                                     [0.05, 0.08, 0.10, 0.03])
            return {
                "universe": trial.suggest_categorical("universe", d0_universes),
                "neutralization": trial.suggest_categorical("neutralization", d0_neutralizations),
                "decay": trial.suggest_categorical("decay", d0_decays),
                "truncation": trial.suggest_categorical("truncation", d0_truncations),
                "delay": trial.suggest_categorical("delay", delay_choices),
            }

        return {
            "universe": trial.suggest_categorical("universe", UNIVERSES),
            "neutralization": trial.suggest_categorical("neutralization", NEUTRALIZATIONS),
            "decay": trial.suggest_int("decay", 0, 12, step=2),
            "truncation": trial.suggest_categorical("truncation", TRUNCATIONS),
            "delay": trial.suggest_categorical("delay", delay_choices),
        }

    def _inject_historical_trials(
        self,
        study,  # optuna.Study - type hint removed for conditional import
        expression: str,
        core_signal: str,
        family: str,
        target_metric: str,
    ) -> int:
        """
        Inject historical sim results as completed trials.
        Searches for runs with same expression, same core signal, or same family.
        Returns number of trials injected.
        """
        if self.storage is None:
            return 0

        historical_runs = []

        # strategy 1: exact expression matches (different settings)
        try:
            exact = self._get_runs_for_expression(expression)
            historical_runs.extend(exact)
        except Exception:
            pass

        # strategy 2: same core signal (variants of the same underlying idea)
        if core_signal and len(historical_runs) < 30:
            try:
                core_runs = self._get_runs_for_core(core_signal)
                seen_ids = {r["run_id"] for r in historical_runs}
                for r in core_runs:
                    if r["run_id"] not in seen_ids:
                        historical_runs.append(r)
            except Exception:
                pass

        # strategy 3: same family (structural similarity)
        if family and len(historical_runs) < 30:
            try:
                family_runs = self._get_runs_for_family(family)
                seen_ids = {r["run_id"] for r in historical_runs}
                for r in family_runs:
                    if r["run_id"] not in seen_ids and len(historical_runs) < 50:
                        historical_runs.append(r)
            except Exception:
                pass

        # inject as completed trials.
        # filter warm-start trials by delay safety. if the current expression is
        # d=1-only (returns/close used unsafely), historical d=0 trials of the same
        # expression aren't relevant, so they're skipped. if d=0 is safe, both d=0
        # and d=1 trials are kept with `delay` as a parameter so TPE can learn that
        # (settings, d=0) and (settings, d=1) are different points. without this,
        # TPE was mixing d=0 sharpe (typically 0.8-1.5) with d=1 sharpe (1.0-2.5)
        # for the same other-settings combo, giving misleading recommendations.
        injected = 0
        d0_choices = _delay_choices_for_expression(expression)
        d0_safe = 0 in d0_choices

        for run in historical_runs:
            settings = run.get("settings_json") or run.get("settings") or {}
            universe = settings.get("universe")
            neutralization = settings.get("neutralization")
            decay = settings.get("decay")
            truncation = settings.get("truncation")
            # read delay from the historical run (default 1 if absent)
            try:
                delay = int(settings.get("delay", 1))
            except (TypeError, ValueError):
                delay = 1

            # skip if missing required settings
            if not all([universe, neutralization, decay is not None, truncation]):
                continue

            # skip trials whose delay isn't in the current search space.
            # if the expression is d=1-only, drop historical d=0 trials.
            if delay not in d0_choices:
                continue

            # normalize types
            if isinstance(decay, str):
                try:
                    decay = int(decay)
                except ValueError:
                    continue
            if isinstance(truncation, str):
                try:
                    truncation = float(truncation)
                except ValueError:
                    continue

            # skip if settings are outside our search space. when D0_ONLY_MODE is on
            # the active search space is the narrower DELAY0_* lists, so use those
            # instead of the full UNIVERSES/etc.
            try:
                import config as _cfg
                _d0_only = getattr(_cfg, "D0_ONLY_MODE", False)
            except Exception:
                _d0_only = False

            if _d0_only:
                _univ_space = getattr(_cfg, "DELAY0_UNIVERSES", UNIVERSES)
                _neut_space = getattr(_cfg, "DELAY0_NEUTRALIZATIONS", NEUTRALIZATIONS)
                _dec_space = getattr(_cfg, "DELAY0_DECAYS", DECAYS)
                _trunc_space = getattr(_cfg, "DELAY0_TRUNCATIONS", TRUNCATIONS)
            else:
                _univ_space = UNIVERSES
                _neut_space = NEUTRALIZATIONS
                _dec_space = DECAYS
                _trunc_space = TRUNCATIONS

            if universe not in _univ_space:
                continue
            if neutralization not in _neut_space:
                continue
            if decay not in _dec_space:
                # round to nearest valid decay
                decay = min(_dec_space, key=lambda d: abs(d - decay))
            if truncation not in _trunc_space:
                truncation = min(_trunc_space, key=lambda t: abs(t - truncation))

            # get target metric value
            if target_metric == "fitness":
                value = float(run.get("fitness") or run.get("sharpe", 0) or 0)
            else:
                value = float(run.get("sharpe", 0) or 0)

            # skip sims with no useful data
            if value == 0:
                continue

            try:
                # include delay in trial params and distribution so TPE can
                # distinguish (settings, d=0) from (settings, d=1). when the
                # expression supports both delays the distribution is [0,1]; when it
                # only supports d=1 the distribution is [1]. distributions must match
                # the narrowed D0_ONLY_MODE search space, otherwise add_trial throws.
                if _d0_only:
                    dist = {
                        "universe": optuna.distributions.CategoricalDistribution(_univ_space),
                        "neutralization": optuna.distributions.CategoricalDistribution(_neut_space),
                        "decay": optuna.distributions.CategoricalDistribution(_dec_space),
                        "truncation": optuna.distributions.CategoricalDistribution(_trunc_space),
                        "delay": optuna.distributions.CategoricalDistribution(d0_choices),
                    }
                else:
                    dist = {
                        "universe": optuna.distributions.CategoricalDistribution(UNIVERSES),
                        "neutralization": optuna.distributions.CategoricalDistribution(NEUTRALIZATIONS),
                        "decay": optuna.distributions.IntDistribution(0, 12, step=2),
                        "truncation": optuna.distributions.CategoricalDistribution(TRUNCATIONS),
                        "delay": optuna.distributions.CategoricalDistribution(d0_choices),
                    }
                trial = optuna.trial.create_trial(
                    params={
                        "universe": universe,
                        "neutralization": neutralization,
                        "decay": decay,
                        "truncation": truncation,
                        "delay": delay,
                    },
                    distributions=dist,
                    values=[value],
                )
                study.add_trial(trial)
                injected += 1
            except Exception:
                continue

        return injected

    def _get_runs_for_expression(self, expression: str) -> list[dict]:
        """Get all completed runs for a specific expression."""
        try:
            return self.storage.get_runs_for_expression(expression)
        except Exception:
            return []

    def _get_runs_for_core(self, core_signal: str) -> list[dict]:
        """Get runs with similar core signals."""
        try:
            return self.storage.get_runs_for_core_signal(core_signal)
        except Exception:
            return []

    def _get_runs_for_family(self, family: str) -> list[dict]:
        """Get top runs from the same family for cross-pollination."""
        try:
            return self.storage.get_runs_for_family(family)
        except Exception:
            return []
