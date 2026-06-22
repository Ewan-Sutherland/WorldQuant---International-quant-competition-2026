from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

# base paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "bot.db"

# storage backend: "sqlite" or "supabase". supabase is the default so several
# accounts share the same data.
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "supabase")

# sprint mode: short competition push. set False to revert to normal pacing.
SPRINT_MODE = True

# supabase credentials (only needed if STORAGE_BACKEND = "supabase")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")

# brain api
BRAIN_USERNAME = os.getenv("BRAIN_USERNAME", "")
BRAIN_PASSWORD = os.getenv("BRAIN_PASSWORD", "")

# scheduler / runtime
MAX_CONCURRENT_SIMS = 3
# poll every 40s - WQ sims take 2-5 min, so faster polling just wastes bandwidth.
# 40s still catches completions within one extra poll cycle.
POLL_INTERVAL_SECONDS = 40
SESSION_REFRESH_MINUTES = 150
SIM_TIMEOUT_MINUTES = 45

# default simulation settings
DEFAULT_REGION = "USA"
DEFAULT_DELAY = 1

# delay-0 exploration. D0 scores lower but lives in a separate self-correlation
# space, so it's kept as a side-budget, not the default. stage 1 score = D1 + D0/3,
# so even mediocre D0 alphas add free points and unlock the second leaderboard column.
DELAY0_ENABLED = True
DELAY0_FRESH_PROBABILITY = 0.10
DELAY0_REFINE_PROBABILITY = 0.12

# treat delay 0 as a separate mini-universe, not a mutation of the delay 1 search.
# these probabilities control fresh template generation only; combiner/evolver stay
# delay 1 unless explicitly upgraded with their own delay-aware pools.

# D0-only overnight fork. when True the bot runs as a strict D=0 hunter: templates
# strip all non-D0 families, every fresh candidate is D0, LLM/combiner/evolver stay
# off, Optuna is restricted to delay=[0], and refinement uses D0 thresholds. left
# False - the overnight test produced 0 alphas in 2125 sims.
D0_ONLY_MODE = False

DELAY0_TEMPLATE_PROBABILITY = 1.0 if D0_ONLY_MODE else 0.0  # force all fresh candidates to D=0 in D0_ONLY_MODE
DELAY0_TEMPLATE_FAMILIES = {
    # original D0 families (kept available)
    "delay0_open_gap_reversal",
    "delay0_close_vwap_dislocation",
    "delay0_range_position",
    "delay0_volume_shock",
    "delay0_liquidity_pressure",
    "delay0_options_intraday",
    "delay0_news_reaction",
    "delay0_risk_intraday",
    # newer hand-picked D0 families from the research brief
    "d0v7_open_price_reversal",
    "d0v7_group_reversion",
    "d0v7_news_triggers",
    "d0v7_sentiment",
    "d0v7_vol_regime",
    "d0v7_iv_rv",
    "d0v7_analyst",
    "d0v7_volume_shock",
    "d0v7_overnight_gap",
    "d0v7_fundamental",
}
# prefer liquid universes - D0 alphas tend to do well in smaller/liquid universes
DELAY0_UNIVERSES = ["TOP500", "TOP1000", "TOP200", "TOPSP500", "TOP2000", "TOP3000"]
DELAY0_NEUTRALIZATIONS = ["SUBINDUSTRY", "INDUSTRY", "SECTOR", "MARKET", "NONE"]  # subindustry/industry preferred
# decay sweep is not zero-only - published USA D0 alphas score well at both decay=0 and decay=9
DELAY0_DECAYS = [0, 2, 4, 6, 9]
DELAY0_TRUNCATIONS = [0.05, 0.08, 0.10, 0.03] if D0_ONLY_MODE else [0.01, 0.03, 0.05, 0.08, 0.10]
# published USA D0 alphas cluster at 0.08-0.10 truncation, not the 0.01 typical of D1
# fundamentals. tighter truncation over-concentrates into event names and chops the
# signal an event-driven D0 alpha is trying to capture.

# delay 0 alphas shouldn't be bred with delay 1 populations by default - avoids
# turning a slow delay 1 composite into a noisy delay 0 expression or vice versa.
SEPARATE_DELAY_REGIMES = True
COMBINER_ALLOW_DELAY0 = False
EVOLVER_ALLOW_DELAY0 = False
LLM_ALLOW_DELAY0 = False

DELAY0_FAMILY_BOOST = {
    "delay0_open_gap_reversal": 1.0,
    "delay0_close_vwap_dislocation": 1.0,
    "delay0_range_position": 1.0,
    "delay0_volume_shock": 1.0,
    "delay0_liquidity_pressure": 1.0,
    "delay0_options_intraday": 1.0,
    "delay0_news_reaction": 1.0,
    "delay0_risk_intraday": 1.0,
}
DEFAULT_UNIVERSES = ["TOP3000", "TOP1000", "TOP500", "TOP200", "TOPSP500", "TOP2000"]
DEFAULT_NEUTRALIZATIONS = ["SUBINDUSTRY", "INDUSTRY", "SECTOR", "MARKET", "NONE"]
DEFAULT_DECAYS = [0, 2, 4, 6, 8, 10, 12]  # includes 0 (no-decay) - some alphas perform best raw
DEFAULT_TRUNCATIONS = [0.01, 0.03, 0.05, 0.08, 0.10]  # includes 0.01 (tightest) - improves sharpe on concentrated alphas

DEFAULT_INSTRUMENT_TYPE = "EQUITY"
DEFAULT_VISUALIZATION = False

DEFAULT_PASTEURIZATION = "ON"
DEFAULT_UNIT_HANDLING = "VERIFY"
DEFAULT_NAN_HANDLING = "OFF"
DEFAULT_MAX_STOCK_WEIGHT = 0.10
DEFAULT_LANGUAGE = "FASTEXPR"

# evaluation thresholds
# MIN_SHARPE tightened from 1.25 to 1.40: low-sharpe alphas drag the merged OS score
# even when the IS score_change is positive. 1.40 keeps the refinement queue full
# while pushing average submission quality up.
MIN_SHARPE = 1.40
MIN_FITNESS = 1.00
MAX_TURNOVER = 0.70

# near-passer / refinement settings
NEAR_PASSER_MIN_SHARPE = 1.30  # aligned with MIN_SHARPE
NEAR_PASSER_MIN_FITNESS = 0.65
NEAR_PASSER_MAX_TURNOVER = 0.75
REFINEMENT_PROBABILITY = 0.50  # 50/50 refine vs fresh

# sprint override - gap mining produces more near-passers, so refinement needs more
# budget to keep the queue from growing unbounded
if SPRINT_MODE:
    REFINEMENT_PROBABILITY = 0.55  # 55% refine, 45% fresh

MIN_REFINEMENT_SHARPE = 1.25  # with MIN_SHARPE=1.40 the 0.15 gap is reachable via settings sweeps but skips very-weak targets
FRONTIER_MIN_SHARPE = 0.95
FRONTIER_MIN_FITNESS = 0.75  # F=0.50 never reaches F>=1.0 through settings alone
FRONTIER_ALT_MIN_SHARPE = 1.35
FRONTIER_ALT_MIN_FITNESS = 0.60

# frontier templates worth exploiting more aggressively
STRONG_TEMPLATES = set()  # old saturated templates no longer elite
ELITE_TEMPLATES = set()   # old saturated templates no longer elite

# diversity / anti-self-correlation
DIVERSITY_LOOKBACK_RUNS = 120
MAX_RECENT_TEMPLATE_COUNT = 10  # faster rotation with 1167 templates
RELAXED_TEMPLATE_COUNT = 14
RELAXED_TEMPLATE_MIN_AVG_SHARPE = 1.30
RELAXED_TEMPLATE_MIN_AVG_FITNESS = 0.70
DIVERSITY_EXPLORATION_PROBABILITY = 0.08  # epoch rotation handles diversity
MAX_REFINEMENT_ATTEMPTS_PER_BASE = 10  # fundamentals need more settings sweeps
MAX_CORE_SIGNAL_EXHAUSTIONS = 2  # same core through different candidates wastes sims
MAX_FAMILY_TEMPLATE_EXHAUSTIONS = 5  # research families have 10-14 templates
MAX_REFINEMENT_PER_CORE = 6  # diverse signals close to 1.25 need more universe/neut combos
MAX_SUBMISSIONS_PER_CORE = 3  # self-corr wall means 4 variants all correlate
LOCAL_REFINEMENT_HISTORY = 10
LOCAL_REFINEMENT_MAX_SIMILARITY = 0.90

# template scoring / pruning
TEMPLATE_SCORE_LOOKBACK_RUNS = 50  # 50 recent runs is enough for Thompson, minimal egress
MIN_TEMPLATE_OBS_FOR_PRUNE = 6

HARD_PRUNE_MAX_AVG_SHARPE = 0.20
HARD_PRUNE_MAX_AVG_FITNESS = 0.10

SOFT_PRUNE_MAX_AVG_SHARPE = 0.60
SOFT_PRUNE_MAX_AVG_FITNESS = 0.35

TEMPLATE_EXPLORATION_PROBABILITY = 0.25  # trimmed to make budget for the gap_mining boost (highest hit rate)
SOFT_PRUNE_REFINEMENT_PROBABILITY = 0.35

# submission behaviour
# smart submission pipeline: checks self-corr + before/after via API, refines settings
# with Optuna, picks the best variant.
# AUTO_SUBMIT=True  -> submits the best variant directly to WQ
# AUTO_SUBMIT=False -> stages the best variant in ready_alphas for manual submission
AUTO_SUBMIT = False

# scheduled submission pipeline - runs at specific UTC hours per owner. each owner gets
# 2 windows per day, 12 hours apart. the pipeline re-checks scores, groups by core
# signal and submits greedily. fill in your own accounts here.
SUBMIT_SCHEDULE = {
    "owner1@example.com": [7, 19],   # 7:30am and 7:30pm UTC
    "owner2@example.com": [7, 19],
}
SUBMIT_MINUTE = 30  # fire at :30 past the hour
# minimum score change to auto-submit (avoids marginal alphas flipping negative).
# self-correlation budget is finite, so it's better spent on +15/+50 alphas than +1/+2
# trinkets. low-positive alphas stay in ready_alphas to be re-checked later.
SUBMIT_MIN_SCORE = 15

# per-family sharpe override for untapped_* families. untapped fields are noisy (low
# usage = low signal-to-noise), so they need a lower eligibility bar; once eligible,
# Optuna can push sharpe to 1.40+ and the decorrelation edge gives them a genuine shot
# at positive score_change. bot.py falls back to MIN_SHARPE.
MIN_SHARPE_BY_FAMILY = {
    "untapped_breakeven": 0.95,
    "untapped_supply_chain": 0.95,
    "untapped_model77": 0.95,
    "untapped_cross_prefix": 0.95,
}

# per-family fitness override (untapped fields often have F<1 even at S>1.4)
MIN_FITNESS_BY_FAMILY = {
    "untapped_breakeven": 0.50,
    "untapped_supply_chain": 0.50,
    "untapped_model77": 0.50,
    "untapped_cross_prefix": 0.50,
}
# single source of truth for the negative-score floor below which alphas are rejected
# rather than kept as marginal. was hardcoded as -10 in several places.
STAGING_FLOOR = -25
HIGH_SHARPE_RESCUE = 1.6  # sharpe at/above this stages even if score < STAGING_FLOOR

# number of Optuna settings variants to try per eligible alpha
OPTIMIZE_VARIANTS = 5

# IQC competition id for the before-and-after-performance endpoint
IQC_COMPETITION_ID = os.getenv("IQC_COMPETITION_ID", "IQC2026S1")

# submission diversity / self-correlation avoidance.
# structural-similarity threshold: if a candidate exceeds this against any submitted
# alpha it's flagged as correlated. this is a proxy for PnL correlation - structural
# sim of 0.50+ typically means PnL corr > 0.70.
SUBMISSION_MAX_SIMILARITY = 0.45
# boost for families not yet represented in submissions
UNSUBMITTED_FAMILY_BOOST = 1.60

# saturation-aware family bias. two mechanisms wired into bot._family_bias_map:
# (a) per-family saturation penalty proportional to submission count
#     (1.00 / 0.85 / 0.60 / 0.40 / 0.25 at 0 / 1-2 / 3-4 / 5-7 / 8+ submissions)
# (b) a boost for diversity-gap families the portfolio is structurally missing.
DIVERSITY_GAP_FAMILIES = set()  # disabled - see note below
DIVERSITY_GAP_BOOST = 1.0       # no-op
# the diversity-gap boost is turned off. it funnelled compute into families with a
# sub-0.1% eligible rate, and the data-driven saturation penalty does the job on its
# own. kept as a no-op (empty set) so bot.py code that references it still runs.

# exploration experiment: force compute into fresh families to find out whether they
# actually produce alphas, by boosting their weight and bypassing the DEAD_FAMILIES
# crush until each has 30+ sims (then normal Thompson sampling takes over). a deliberate
# evidence-gathering pass, not a permanent strategy.
EXPLORATION_TARGETS = {
    # intraday / D=0-favoured families (use today's prices/volume)
    "delay0_close_vwap_dislocation",   # (vwap - close) microstructure
    "delay0_open_gap_reversal",         # overnight gap reversion
    "delay0_range_position",            # (high - low) / (close - open) range pos
    "delay0_volume_shock",              # volume / adv20 spike conditional
    "d0v7_iv_rv",                       # implied vs realized vol
    "d0v7_overnight_gap",               # overnight gap reversal D0
    "d0v7_open_price_reversal",         # open-price reversion D0
    "d0v7_volume_shock",                # D0 volume shock
    # regression-based (ts_regression operator family)
    "regression_predicted",
    # event-conditional (trade_when + days_from_last_change - different turnover profile)
    "conditional",
    "group_conditional_high_momentum",
    "group_conditional_high_volume",
    "group_conditional_low_volatility",
    # cross-sectional non-rank patterns
    "cross_sectional",
    # fresh data categories with rich field counts
    "fresh_estimates",
    "alt_combo_min_max",
    "alt_normalization",
    "corr_pipeline",                    # ts_corr operator family
}
EXPLORATION_BOOST = 1.4       # weight multiplier while under EXPLORATION_MIN_SIMS
EXPLORATION_MIN_SIMS = 30     # boost falls off after this many sims
EXPLORATION_BYPASS_DEAD = True  # skip the DEAD_FAMILIES crush for these

# logging / reporting
REPORT_EVERY_N_COMPLETIONS = 50

# family/template weighting
DEFAULT_FAMILY_ORDER = [
    # ordered by data diversity - novel data categories first (highest exploration value)
    "model77_anomaly",
    "model77_combo",
    "expanded_fundamental",
    "relationship",
    "risk_beta",
    "analyst_estimates",
    "wq_proven",
    "combo_factor",
    # signal classes
    "fundamental_value",
    "quality_trend",
    "fundamental_scores",
    "earnings_momentum",
    "options_vol",
    "news_sentiment",
    "vol_regime",
    "size_value",
    # core families
    "cross_sectional",
    "liquidity_scaled",
    "conditional",
    "analyst_sentiment",
    "volume_flow",
    "price_vol_corr",
    "vol_adjusted",
    "volatility",
    "intraday",
    "fundamental",
    "mean_reversion",
    "momentum",
    # untapped data categories
    "vector_data",
    "supply_chain",
    "ravenpack_cat",
    "options_analytics",
    "hist_vol",
    "fscore",
    "risk_metrics",
    "intraday_pattern",
    "analyst_deep",
    "social_scalar",
    "wild_combos",
    "tutorial_proven",
    "high_sharpe",
    "fn_financial",
    "simple_ratio",
    "fundamental_vol",
]

FAMILY_BASE_WEIGHTS = {
    # curated weights from 600+ sims on this account.
    # dead families suppressed, portfolio-diverse families boosted.
    "model77_anomaly": 0.10,    # DEAD - standalone fields don't work
    "model77_combo": 0.80,      # 82 sims, 0% submit, hurts portfolio score
    "expanded_fundamental": 0.40,
    "relationship": 0.10,       # 60 sims, S=0.10, 0% submit - DEAD
    "risk_beta": 0.10,          # 12 sims, S=-0.05, 0% submit - DEAD
    "analyst_estimates": 1.50,
    "wq_proven": 1.50,
    "combo_factor": 1.50,
    # SATURATED - 9+ submissions are returns mean reversion variants
    "mean_reversion": 0.05,
    "cross_sectional": 0.05,
    "liquidity_scaled": 0.08,
    "conditional": 0.10,
    "vol_adjusted": 0.08,
    # PORTFOLIO-ADDITIVE - boost genuinely different data categories
    "fundamental_value": 3.00,  # operating_income/parkinson_vol showed +152 score change
    "quality_trend": 0.60,
    "fundamental_scores": 0.10, # 11 sims, S=-0.07 - DEAD
    "earnings_momentum": 1.80,
    "options_vol": 3.50,        # proven portfolio-additive (all 4 winners)
    "news_sentiment": 0.50,
    "vol_regime": 0.60,
    "size_value": 0.40,
    "volume_flow": 0.20,
    "price_vol_corr": 0.20,
    "analyst_sentiment": 2.00,  # works in combos (snt1_d1 signals)
    "volatility": 0.15,
    "intraday": 0.05,           # 14 sims, S=-0.66 - DEAD
    "fundamental": 0.10,
    "momentum": 0.05,
    # UNTAPPED DATA - virtually zero correlation with existing portfolio
    "vector_data": 3.00,
    "model_data": 0.01,         # all mdf_*, mdl175_* fields DEAD on this account
    "event_driven": 0.01,       # all fnd6_*, fam_* fields DEAD on this account
    "supply_chain": 4.00,
    "ravenpack_cat": 3.50,
    "options_analytics": 0.10,  # 8 sims, S=-0.15 - DEAD
    "hist_vol": 3.00,
    "fscore": 0.10,             # 10 sims, S=-0.28 - DEAD
    "risk_metrics": 0.10,
    "intraday_pattern": 0.50,
    "analyst_deep": 0.10,       # 6 sims, S=-0.22 - DEAD
    "social_scalar": 0.10,
    "wild_combos": 0.10,        # 7 sims, S=-0.23 - DEAD
    "tutorial_proven": 3.00,
    "high_sharpe": 5.00,        # research-proven S>2.0 patterns - HIGHEST PRIORITY
    # fn_ financial statement fields - massive portfolio diversity (+175, +198 score change)
    "fn_financial": 5.00,
    "simple_ratio": 5.00,       # liabilities/assets gave +175
    "fundamental_vol": 3.00,    # operating_income/parkinson_vol showed +152 score change
    # new signal dimensions - untouched fields, maximum decorrelation potential
    "news_event_signal": 5.00,  # 14 nws18_* fields completely untouched by any template
    "rp_category_fresh": 5.00,  # ~50 rp_css/rp_ess/rp_nip fields LLM never generates
    "derivative_interaction": 4.00,  # derivative_scores x price/vol cross-signals
    "cross_dimension": 4.00,    # model77 x events/options structural combos
    "vol_gated": 5.00,          # trade_when(vol_regime, alpha) - rescues S=1.0-1.2 near-passers
    # delay-0 specialist families. small side-budget because delay-0 contributes 1/3 points.
    "delay0_open_gap_reversal": 2.80,
    "delay0_close_vwap_dislocation": 3.50,
    "delay0_range_position": 3.00,
    "delay0_volume_shock": 2.80,
    "delay0_liquidity_pressure": 2.20,
    "delay0_options_intraday": 1.80,
    "delay0_news_reaction": 2.20,
    "delay0_risk_intraday": 1.60,
}

TEMPLATE_BASE_WEIGHTS = {
    # curated per-template weights from 600+ sims
    "cf_01": 1.90,      # -rank(close/field) + -rank(returns)
    "cf_02": 1.90,      # -rank(ts_zscore(field)) + -rank(vwap rev)
    "cf_03": 1.80,      # rank(field/assets) + -rank(vwap rev)
    "cf_04": 1.70,      # rank(field/cap) + -rank(returns)
    "cf_05": 1.50,      # fundamental + vol_regime
    "cf_06": 1.70,      # earnings momentum + reversion
    "cf_07": 1.65,      # earnings rank + vwap reversion
    "cf_08": 1.60,      # options IV ratio + reversion
    "cf_09": 1.55,      # fscore + reversion
    "cf_10": 1.40,      # sentiment + fundamental
    "fv_05": 1.40,
    "fv_06": 1.35,
    "qt_04": 1.30,
    "qt_06": 1.25,
    "em_01": 1.40,
    "em_07": 1.35,
    "opt_05": 1.40,
    "opt_06": 1.35,
    "opt_07": 1.30,
    "ns_01": 1.20,
    "ns_03": 1.20,
    "vr_01": 1.30,
    "vr_03": 1.20,
    "fs_07": 1.30,
    "fs_08": 1.25,
    "fs_04": 1.40,
    "fs_05": 1.30,
    "fs_06": 1.25,
    "opt_03": 1.20,
    "opt_04": 1.15,
    # legacy - heavily reduced (saturated signal classes)
    "cs_02": 0.30,
    "pvc_04": 0.60,
    "vol_03": 0.40,
    "mr_02": 0.20,
    "cond_01": 0.20,
    "mr_04": 0.15,
    "pvc_03": 0.40,
    "mr_01": 0.20,
}

PREFERRED_TEMPLATE_BOOSTS = {
    "mr_04": 1.35,
    "vol_03": 1.40,
    "va_02": 1.20,
    "mr_01": 1.15,
    "cond_01": 1.10,
    "fs_04": 1.50,
    "fs_05": 1.45,
    "opt_03": 1.30,
    "opt_04": 1.25,
}

# boost model77_combo templates (near-passers at S=1.47)
PREFERRED_TEMPLATE_BOOSTS.update({
    "m7c_03": 1.50,      # near-passers but never cracks fitness, Optuna will handle
    "m7c_02": 1.50,      # combo with -rank(returns)
    "m7c_01": 1.40,
    "m7c_04": 1.40,
    # promising templates from latest 600+ sim data
    "rp_04": 2.50,       # ravenpack insider x vwap reversion - S=1.07 across 4 sims, very promising
    "hv_02": 2.00,       # vol regime conditional - S=0.86, F=1.26, best fitness in bot
    "combo_3s": 2.00,    # 3-signal combos - S=1.15, F=1.29 average
    "combo_2s": 1.80,    # 2-signal combos - S=1.41, 12% submit rate
    "hs_01": 2.00,       # -ts_zscore(EV/EBITDA) - S=1.06, getting close
    "hs_10": 1.80,       # price/book zscore - S=0.90 early
    "tut_09": 1.50,      # OEY ts_rank - S=0.88, F=0.71 first sim
    # multiplicative combos - data-driven weights from overnight run
    "m7c_05": 0.01,      # DEAD: avg S=0.14 in 7 sims
    "m7c_06": 3.00,      # BEST NEW: avg S=0.81, best F=1.39 - multiplicative x vol_regime
    "m7c_07": 0.01,      # DEAD: avg S=-0.01 in 7 sims
    "m7c_08": 0.01,      # DEAD: avg S=-0.17 in 2 sims
    "m7c_09": 0.01,      # DEAD: avg S=0.14 standalone q-theory
    "m7c_10": 1.20,      # ALIVE: avg S=0.59, best S=1.01 - q-theory + price reversion
    "m7c_11": 0.01,      # DEAD: avg S=0.09 group_rank q-theory
    "m7c_12": 0.80,      # KEEP LOW: avg S=0.20 but best F=1.21 - unusual
    "m7c_13": 1.00,      # KEEP: only 2 sims, avg S=0.56
    "m7c_14": 1.20,      # KEEP: avg S=0.42, best F=0.84
    "m7c_15": 0.60,      # SOFT PRUNE: avg S=0.43, 12 sims, never close
    # raw multiplicative rank(A * B)
    "m7c_16": 2.50,      # model77 x price reversion
    "m7c_17": 2.50,      # model77 x vwap intraday
    "m7c_18": 2.50,      # model77 x vwap reversion smoothed
    "m7c_19": 2.00,      # model77 x IV skew - cross-dataset interaction
    "m7c_20": 2.00,      # model77 x earnings revision
    "m7c_21": 2.20,      # multiplicative pair + additive third (GP/A)
    "m7c_22": 2.20,      # multiplicative pair + additive third (investment)
    "m7c_23": 2.50,      # group_rank of model77 x reversion - industry relative
    "m7c_24": 2.50,      # group_rank of model77 x vwap - subindustry relative
    "m7c_25": 2.30,      # ts_rank temporal x reversion - best for quarterly data
    "m7c_26": 2.30,      # group_rank of ts_rank temporal x reversion
    "cf_11": 2.50,       # fundamental/cap x price reversion raw mult
    "cf_12": 2.50,       # fundamental zscore x vwap raw mult
    "cf_13": 2.50,       # fundamental/cap x vwap reversion raw mult
    "cf_14": 2.50,       # group_rank fundamental x reversion - industry
    "cf_15": 2.50,       # group_rank fundamental x reversion - subindustry
    "rel_09": 0.80,      # KEEP LOW: avg S=0.60 in 2 sims
    "rel_10": 0.01,      # DEAD: avg S=-1.09
    "rel_11": 0.40,      # WEAK: avg S=0.08
    "ef_15": 0.01,       # DEAD: S=-0.56
    "ef_16": 0.01,       # DEAD: avg S=-0.55
    "ef_17": 0.01,       # DEAD: avg S=-0.17
    "ef_18": 0.01,       # DEAD: avg S=0.03
    # portfolio-additive templates
    "opt_10": 3.00,      # IV/parkinson standalone
    "opt_11": 3.00,      # IV/parkinson group_rank
    "opt_12": 3.50,      # IV/parkinson x sentiment - the +48 pattern
    "opt_13": 3.50,      # IV/parkinson x fundamentals cross-category
    "opt_14": 2.50,      # options term structure
    "opt_15": 2.50,      # options term structure x liquidity
    "opt_16": 2.00,      # PCR mean reversion
    "ns_09": 2.50,       # news x reversion
    "ns_10": 2.50,       # RavenPack earnings x reversion
    "ns_11": 2.50,       # sentiment x liquidity x reversion
    "ns_12": 2.00,       # buzz acceleration x sentiment
    "rb_08": 2.00,       # beta x fundamentals
    "rb_09": 2.00,       # beta + analyst estimates
    "rb_10": 1.80,       # unsystematic risk x profitability
    "rb_11": 2.20,       # beta x options vol (two additive categories)
    "iday_06": 2.00,     # candle body x sentiment
    "iday_07": 1.80,     # range zscore x liquidity
    "iday_08": 1.80,     # industry-relative close position
    "ans_04": 2.50,      # sentiment x reversion
    "ans_05": 2.50,      # earnings surprise x value
    "ans_06": 2.50,      # analyst rating x vwap reversion
    "vec_01": 3.50,      # proven buzz pattern (S=1.94)
    "vec_02": 3.00,      # sentiment vector
    "vec_03": 3.00,      # buzz count x reversion
    "vec_04": 2.50,      # news significance
    "vec_05": 3.00,      # news x reversion cross-category
    "vec_06": 3.00,      # buzz x sentiment interaction
    "vec_07": 2.50,      # buzz IR
    "vec_08": 3.00,      # scl15 sentiment x reversion
    "mdf_01": 2.50,      # Piotroski score
    "mdf_02": 3.00,      # Piotroski x reversion
    "mdf_03": 2.50,      # operating earnings yield
    "mdf_04": 2.50,      # OEY group_rank
    "mdf_05": 3.50,      # proven eg3 pattern (S=1.59)
    "mdf_06": 2.50,      # R&D intensity
    "mdf_07": 2.00,      # model P/B
    "mdf_08": 2.50,      # gross margin from mdl175
    "evt_01": 3.50,      # proven forward EPS pattern (S=2.03)
    "evt_02": 3.00,      # forward EPS / price
    "evt_03": 3.00,      # EPS revision freshness
    "evt_04": 2.50,      # earnings surprise pct
    "evt_05": 3.00,      # surprise x reversion
    "evt_06": 2.50,      # ROE rank x reversion
    "evt_07": 3.00,      # event timing x fundamental
    "fv_08": 2.00,       # multi-period fundamental 22x252
    "fv_09": 2.00,       # multi-period fundamental 60x252
    "ef_19": 2.50,       # accrual anomaly - Sloan 1996
    "ef_20": 2.50,       # balance sheet accrual
    "ef_21": 2.50,       # retained earnings reversion - proven S=1.55
    "ef_22": 2.50,       # investment anomaly - Titman et al
    "vec_09": 2.50,      # pasteurize buzz
    "vec_10": 2.50,      # pasteurize news x reversion
    "vec_11": 3.50,      # news-conditional regime - proven S=1.84
})

TEMPLATE_WEIGHT_PENALTIES = {
    "va_01": 0.35,
    "vol_02": 0.30,
    "cond_03": 0.40,
    "fs_01": 0.40,
    "fs_02": 0.30,
    "fs_03": 0.40,
    "ae_03": 0.01,
    "wp_06": 0.01,
    "wp_03": 0.05,
    "m77_01": 0.05, "m77_02": 0.05, "m77_03": 0.05, "m77_04": 0.05,
    "m77_05": 0.05, "m77_06": 0.05, "m77_07": 0.05, "m77_08": 0.05, "m77_09": 0.05,
    "wp_05": 0.01,
    "llm_rela": 0.01,
    "llm_cros": 0.01,
    "llm_llm_": 0.05,
    "rel_01": 0.01,
    "rel_02": 0.01,
    "fs_06": 0.01,
    "fs_08": 0.01,
    # delay-0 specialist mini-universe
    "delay0_reversal": 2.50,
    "delay0_volume_pressure": 2.25,
    "delay0_vwap_range": 2.00,
    "delay0_event_reaction": 1.75,
}

DISABLED_REFINEMENT_TEMPLATES = {"vol_02", "ae_03", "wp_06"}
SOFT_BLOCK_REFINEMENT_TEMPLATES = {"cond_03", "va_01"}
SOFT_BLOCK_REFINEMENT_PROB = 0.08

REFINEMENT_TEMPLATE_SWITCH_PROB = 0.12
REFINEMENT_ELITE_STAY_PROB = 0.90
REFINEMENT_ELITE_FITNESS_STAY_PROB = 0.96
REFINEMENT_ELITE_TURNOVER_STAY_PROB = 0.98
REFINEMENT_ELITE_SHARPE_STAY_PROB = 0.84

LIGHT_POST_PROCESS_SMOOTH_PROB = 0.34
FRESH_FORCE_SMOOTH_PROB = 0.74
FRESH_RAW_RANK_PROB = 0.02
PREFER_TS_MEAN_WINDOW = [3, 5, 10]

# LLM generation
LLM_GENERATION_PROBABILITY = 0.0 if D0_ONLY_MODE else 0.10  # trimmed to make room for the EVOLVE boost; LLM combos pass checks but score_change goes negative

# signal combination - combos with an additive bias are the most likely path to positive score changes
COMBO_GENERATION_PROBABILITY = 0.05  # signal_combo had an 11% positive-score hit rate at avg +3.4 - basically noise; compute redirected to gap_mining

# evolutionary mutation - LLM mutates top performers
EVOLVE_GENERATION_PROBABILITY = 0.35  # the evolved family produced the top scorers (the +48 IS winner was evolve_mut); 27% positive-score hit rate vs signal_combo 11%

# signal-class settings profiles. each signal class has preferred settings from WQ
# researcher recommendations. 85% of sims use these profiles, 15% explore the full space.
SIGNAL_CLASS_SETTINGS = {
    # fundamental - quarterly data, long lookback, subindustry neutral
    "fundamental_value": {"universes": ["TOP3000", "TOP2000", "TOP1000", "TOP500", "TOP200"], "neutralizations": ["SUBINDUSTRY", "INDUSTRY", "MARKET"], "decays": [0, 2, 4, 6, 8, 10], "truncations": [0.05, 0.08, 0.10]},
    "quality_trend": {"universes": ["TOP3000"], "neutralizations": ["SUBINDUSTRY"], "decays": [0, 2, 4], "truncations": [0.05, 0.08]},
    "size_value": {"universes": ["TOP3000"], "neutralizations": ["SUBINDUSTRY"], "decays": [0, 2, 4], "truncations": [0.05, 0.08]},
    # fundamental scores - mid universe, some smoothing
    "fundamental_scores": {"universes": ["TOP1000", "TOP500"], "neutralizations": ["SUBINDUSTRY", "INDUSTRY"], "decays": [4, 6, 8], "truncations": [0.05]},
    # earnings momentum - daily data, broad universe
    "earnings_momentum": {"universes": ["TOP3000", "TOP2000", "TOP1000"], "neutralizations": ["NONE", "INDUSTRY"], "decays": [2, 4, 6], "truncations": [0.05, 0.08]},
    # options - higher decay proven by a +37 score winner (TOP3000/MARKET/d10)
    "options_vol": {"universes": ["TOP3000", "TOP2000", "TOP1000"], "neutralizations": ["MARKET", "INDUSTRY", "NONE"], "decays": [6, 8, 10], "truncations": [0.05, 0.08]},
    # news/sentiment - liquid universe, minimal neutral
    "news_sentiment": {"universes": ["TOP1000", "TOP500"], "neutralizations": ["NONE", "MARKET"], "decays": [2, 4, 6], "truncations": [0.05, 0.08]},
    # vol regime - market neutral
    "vol_regime": {"universes": ["TOP3000", "TOP2000", "TOP1000"], "neutralizations": ["MARKET", "NONE"], "decays": [4, 6, 8], "truncations": [0.05, 0.08]},
    # multi-factor combinations - broad settings
    "combo_factor": {"universes": ["TOP3000", "TOP2000", "TOP1000"], "neutralizations": ["MARKET", "SUBINDUSTRY", "SECTOR"], "decays": [4, 6, 8, 10], "truncations": [0.05, 0.08, 0.10]},
    "model77_anomaly": {"universes": ["TOP3000", "TOP2000", "TOP1000"], "neutralizations": ["INDUSTRY", "SUBINDUSTRY", "MARKET"], "decays": [2, 4, 6, 8], "truncations": [0.05, 0.08]},
    "model77_combo": {"universes": ["TOP3000", "TOP2000", "TOP1000"], "neutralizations": ["INDUSTRY", "SUBINDUSTRY", "MARKET"], "decays": [4, 6, 8], "truncations": [0.05, 0.08]},
    "relationship": {"universes": ["TOP3000", "TOP2000", "TOP1000"], "neutralizations": ["SUBINDUSTRY", "INDUSTRY"], "decays": [2, 4, 6], "truncations": [0.05, 0.08]},
    "risk_beta": {"universes": ["TOP3000", "TOP2000", "TOP1000"], "neutralizations": ["MARKET", "INDUSTRY"], "decays": [4, 6, 8, 10], "truncations": [0.05, 0.08]},
    "expanded_fundamental": {"universes": ["TOP3000", "TOP2000", "TOP1000", "TOP200"], "neutralizations": ["INDUSTRY", "SUBINDUSTRY"], "decays": [2, 4, 6], "truncations": [0.05, 0.08]},
    "analyst_estimates": {"universes": ["TOP3000", "TOP2000", "TOP1000"], "neutralizations": ["INDUSTRY", "SUBINDUSTRY"], "decays": [2, 4, 6], "truncations": [0.05, 0.08]},
    "wq_proven": {"universes": ["TOP3000", "TOP2000", "TOP1000", "TOP200"], "neutralizations": ["INDUSTRY", "SUBINDUSTRY", "SECTOR", "MARKET"], "decays": [0, 2, 4, 6, 8, 10], "truncations": [0.05, 0.08, 0.10]},
    "analyst_sentiment": {"universes": ["TOP3000", "TOP2000", "TOP1000"], "neutralizations": ["MARKET", "INDUSTRY", "NONE"], "decays": [4, 6, 8], "truncations": [0.05, 0.08]},
    "intraday": {"universes": ["TOP3000", "TOP2000", "TOP1000"], "neutralizations": ["MARKET", "INDUSTRY"], "decays": [4, 6, 8], "truncations": [0.05, 0.08]},
    "vector_data": {"universes": ["TOP3000", "TOP2000", "TOP1000"], "neutralizations": ["SUBINDUSTRY", "MARKET"], "decays": [4, 6, 8, 10], "truncations": [0.05, 0.08]},
    "model_data": {"universes": ["TOP3000", "TOP2000", "TOP1000"], "neutralizations": ["MARKET", "INDUSTRY", "SUBINDUSTRY"], "decays": [4, 6, 8], "truncations": [0.05, 0.08]},
    "event_driven": {"universes": ["TOP3000", "TOP2000", "TOP1000"], "neutralizations": ["INDUSTRY", "SUBINDUSTRY"], "decays": [2, 4, 6], "truncations": [0.05, 0.08]},
    "supply_chain": {"universes": ["TOP3000", "TOP2000", "TOP1000"], "neutralizations": ["SUBINDUSTRY", "INDUSTRY"], "decays": [3, 5, 8], "truncations": [0.01, 0.08]},
    "ravenpack_cat": {"universes": ["TOP3000", "TOP2000", "TOP1000"], "neutralizations": ["SUBINDUSTRY", "MARKET", "INDUSTRY"], "decays": [6, 8, 10], "truncations": [0.05, 0.08]},
    "options_analytics": {"universes": ["TOP3000", "TOP2000", "TOP1000"], "neutralizations": ["MARKET", "SECTOR", "INDUSTRY"], "decays": [6, 8, 10], "truncations": [0.05, 0.08]},
    "hist_vol": {"universes": ["TOP3000", "TOP2000", "TOP1000"], "neutralizations": ["MARKET", "SECTOR"], "decays": [6, 8, 10], "truncations": [0.05, 0.08]},
    "fscore": {"universes": ["TOP3000", "TOP2000", "TOP1000"], "neutralizations": ["INDUSTRY", "SUBINDUSTRY", "MARKET"], "decays": [8, 10], "truncations": [0.08]},
    "risk_metrics": {"universes": ["TOP3000", "TOP2000", "TOP1000"], "neutralizations": ["MARKET", "INDUSTRY", "SUBINDUSTRY"], "decays": [6, 8, 10], "truncations": [0.01, 0.05]},
    "intraday_pattern": {"universes": ["TOP3000", "TOP200"], "neutralizations": ["SECTOR", "MARKET"], "decays": [4, 6], "truncations": [0.08, 0.10]},
    "analyst_deep": {"universes": ["TOP3000", "TOP2000", "TOP1000"], "neutralizations": ["INDUSTRY", "SUBINDUSTRY"], "decays": [6, 8], "truncations": [0.08]},
    "social_scalar": {"universes": ["TOP3000", "TOP2000", "TOP1000"], "neutralizations": ["SUBINDUSTRY", "MARKET"], "decays": [4, 6, 8], "truncations": [0.08]},
    "wild_combos": {"universes": ["TOP3000", "TOP2000", "TOP1000"], "neutralizations": ["MARKET", "INDUSTRY", "SUBINDUSTRY"], "decays": [6, 8, 10], "truncations": [0.05, 0.08]},
    "tutorial_proven": {"universes": ["TOP3000", "TOP2000", "TOP1000", "TOP500"], "neutralizations": ["MARKET", "INDUSTRY", "SECTOR"], "decays": [0, 4, 6, 8], "truncations": [0.01, 0.05, 0.08]},
    "high_sharpe": {"universes": ["TOP3000", "TOP2000", "TOP1000", "TOP500", "TOP200"], "neutralizations": ["SUBINDUSTRY", "INDUSTRY", "MARKET"], "decays": [0, 2, 4, 6, 8], "truncations": [0.01, 0.05, 0.08]},
    # fn_ financial statement fields - +175, +198 score change, totally uncorrelated
    "fn_financial": {"universes": ["TOP3000", "TOP2000", "TOP1000", "TOP500", "TOP200"], "neutralizations": ["SUBINDUSTRY", "INDUSTRY", "MARKET", "SECTOR"], "decays": [0, 2, 4, 6, 8, 10, 12], "truncations": [0.01, 0.05, 0.08, 0.10]},
    "simple_ratio": {"universes": ["TOP3000", "TOP2000", "TOP1000", "TOP500", "TOP200"], "neutralizations": ["SUBINDUSTRY", "INDUSTRY", "MARKET", "SECTOR"], "decays": [0, 2, 4, 6, 8, 10, 12], "truncations": [0.01, 0.05, 0.08, 0.10]},
    "fundamental_vol": {"universes": ["TOP3000", "TOP2000", "TOP1000", "TOP500", "TOP200"], "neutralizations": ["SUBINDUSTRY", "INDUSTRY", "MARKET"], "decays": [0, 2, 4, 6, 8, 10], "truncations": [0.05, 0.08, 0.10]},
}

# minimum exploration guarantee per family
MIN_EXPLORATION_PER_FAMILY = 25

# LLM rate-limit cooldown (seconds between calls)
LLM_COOLDOWN_SECONDS = 30  # key rotation handles per-key rate limits (60s each)
LLM_AST_RETRY_MAX = 1      # retry failed expressions once with error feedback

# teammate score checking. after your own submission pipeline runs, also check scores
# for teammates' ready alphas so you can manually submit on their behalf. toggle off
# once they can check scores independently.
CHECK_TEAMMATE_SCORES = False
TEAMMATE_OWNERS = []

# coordinated team submission - which bots participate (can check their own scores)
COORDINATED_SUBMIT_OWNERS = [
    "owner1@example.com",
    "owner2@example.com",
]
# owners whose scores are checked by the coordinator (can't check their own). these
# bots skip phase 1 (score checking) and just wait for submit commands. empty here -
# the proxy infrastructure is kept in coordinated_submit.py in case it's needed.
PROXY_SCORE_OWNERS = []
# only the coordinator ranks globally and orchestrates
IS_COORDINATOR = True  # coordinator config = True, teammate config = False
MAX_SUBMISSIONS_PER_WINDOW = 200

# sprint mode config - concentrates sims on proven families with unused fields,
# disables epoch rotation, suppresses dead families. toggle SPRINT_MODE at the top.

# gap mining probability: when generating fresh candidates, what fraction should use
# the field-gap miner vs normal templates
ENABLE_GAP_MINER = True  # re-enabled after data showed an 8% hit rate (highest of any family); the slowdown was the fnd2_/fnd6_ filter bug, not exhaustion
GAP_MINING_PROBABILITY = 0.0 if D0_ONLY_MODE else (0.20 if SPRINT_MODE else 0.0)  # gap_mining had a 55% positive-score hit rate - highest of all engines; low absolute count but high EV per sim

# increased refinement depth for sprint
if SPRINT_MODE:
    # reverted 6 -> 12 after recognising cap=6 truncates Optuna mid-search. the
    # dead-cores cache (data/dead_cores.json, 48h TTL) handles cross-batch waste by
    # skipping refinement for cores that already exhausted 12 attempts without
    # positives, so good cores get the full search and we never re-pay for losers.
    MAX_REFINEMENT_PER_CORE = 12
    OPTIMIZE_VARIANTS = 8            # more settings per optimize pass

# dead-cores cache settings - cross-batch persistence to skip refinement on cores
# that already exhausted their Optuna budget without any positive score_change.
# TTL=48h so cores can re-enter the pool eventually (portfolio shifts may help).
DEAD_CORES_CACHE_PATH = "data/dead_cores.json"
DEAD_CORES_TTL_SEC = 48 * 3600  # 48 hours

# suppress dead families (0 eligible after 50+ sims)
DEAD_FAMILY_WEIGHT = 0.03  # cooldown, not hard death: keeps rare exploration alive

# field-prefix diversification quota. Supabase CSV analysis showed concentration:
#   field prefix     submissions using
#   returns          71  (saturated)
#   cap              67
#   fn_              58
#   close            41
#   industry         40
#   implied_vol_     35
#   adv20            33
#   nws12_           26
#   parkinson_       24
#   ----------------------------------
#   pv13_            0  <- untapped (154 fields, supply chain)
#   mdl77_           0  <- untapped (1,546 fields, model77 - needs personal Excel)
#   call_breakeven_  0  <- untapped (12 tenors, options sentiment)
#   put_breakeven_   0  <- untapped (12 tenors)
#
# these prefixes are safe (not engine-rejected, not in BLOCKED_EVENT_FIELDS):
#   - pv13_ -> supply_chain category, freely usable
#   - mdl77_ -> model77 category, requires data/wq_personal_datasets.xlsx
#   - call_breakeven_/put_breakeven_ -> options category, most tenors work
#     (call_breakeven_150 is rejected; the rest are fine)
# excluded from diversification (already known-bad): nws18_ (rejects all operators),
# fnd2_/fnd6_ (silently produce bad sims).
#
# when ENABLE_UNTAPPED_PREFIX_QUOTA=True, FieldGapMiner prioritises fields whose prefix
# matches UNTAPPED_PREFIXES until each has reached MIN_PER usage in submissions, then
# falls back to normal weighted selection.
ENABLE_UNTAPPED_PREFIX_QUOTA = True
UNTAPPED_PREFIXES = ('pv13_', 'mdl77_', 'm77_', 'call_breakeven_', 'put_breakeven_')
UNTAPPED_PREFIX_BOOST = 3.0   # multiplier for these in gap-miner field selection
UNTAPPED_PREFIX_MIN_PER = 5   # stop boosting a prefix once it has N+ submissions


# templates that hardcode saturated fields. never sample these - they were producing
# alphas that hit SCORE_NEG_BLOCK because their baked-in field appears 5+ times in the
# portfolio. removing them at sampling time saves 6-12 sims per tick.
BLACKLISTED_TEMPLATES = {
    # operating_income hardcoded (20x in portfolio)
    "rel_11", "ef_17", "wp_03", "wp_05", "sc_03", "wild_07", "tut_09",
    "hs_06", "fn_05", "fn_10", "sr_12",
    # operating_income + parkinson_volatility combo
    "fv_02", "fv_03", "fv_04", "fv_05", "fv_10", "fv_11", "fv_12",
    # accruals quality - operating_income heavy
    "aq_01", "aq_02", "aq_05", "aq_06", "aq_08", "aq_09",
    # rp_css_mna hardcoded (heavily used in portfolio via emna_*)
    "emna_01", "emna_03", "emna_04", "emna_05", "emna_06", "emna_07",
    "emna_08", "em_09", "em_10", "ser_05",
    # d0 templates that use rp_css_mna or operating_income with -returns
    "d0_news_01",
    # high-volume zero-eligible templates from CSV analysis - each has 100+ runs and
    # 0 eligibles (combined waste ~10k sims).
    # gap_mining family - 8 templates with 100+ runs each, all 0% eligible
    "gap_gap_backfill_group",          # 1,363 runs, 0 eligibles, avg S=0.07
    "gap_gap_backfill_rank",           # 863 runs, 0 eligibles, avg S=0.09
    "gap_gap_group_zscore",            # 480 runs, 0 eligibles, avg S=0.17
    "gap_gap_standalone_neg_zscore",   # 444 runs, 0 eligibles, avg S=0.08
    "gap_gap_standalone_zscore",       # 415 runs, 0 eligibles, avg S=-0.02
    "gap_gap_signed_power",            # 401 runs, 0 eligibles, avg S=0.42
    "gap_gap_standalone_delta",        # 395 runs, 0 eligibles, avg S=-0.10
    "gap_gap_regression_trend",        # 360 runs, 0 eligibles, avg S=0.04
    "gap_gap_group_neutralize",        # 427 runs, 0 eligibles
    # nonlinear_power - 1,704 runs, 0 eligibles
    "nl_02",
    # llm_novel - LLM produces non-eligible expressions consistently
    "llm_llm_",                        # 1,004 runs, 0 eligibles
    "llm_cros",                        # 486 runs, 0 eligibles
    "llm_opti",                        # 228 runs, only 2 eligibles after Optuna
    # analyst_estimates - ae_04 has 496 runs, 0 eligibles (avg S=0.93 but never crosses gate)
    "ae_04",
    # wq_proven - wp_01/wp_04 are dead variants (wp_05 already blacklisted above)
    "wp_01",                           # 356 runs, 0 eligibles
    "wp_04",                           # 355 runs, 0 eligibles
    # fn_quarterly - entire family has 0.31% eligible rate; specific dead templates:
    "fnq_02", "fnq_03", "fnq_06", "fnq_07", "fnq_08",
    # fn_financial individual dead templates (family is OK overall, these specific ones aren't)
    "fn_07", "fn_08", "fn_11", "fn_02", "fn_04", "fn_01", "fn_12",
    # liquidity_scaled - liq_02 has 311 runs, 0 eligibles (liq_01 stays - 27 eligibles)
    "liq_02",
    # model77_combo - m7c_03 has 239 runs, 0 eligibles
    "m7c_03",
    # price_vol_corr - pvc_04 has 239 runs, 0 eligibles
    "pvc_04",
    # options_vol - opt_01 has 388 runs, 0 eligibles
    "opt_01",
}

# family-level saturation cooldown. when a family produces N consecutive saturated
# candidates, freeze its sampling weight to near-zero for M generations. prevents the
# Thompson sampler getting stuck on a family whose templates all hardcode saturated fields.
FAMILY_COOLDOWN_TRIGGER = 3       # N saturated candidates in a row -> cooldown
FAMILY_COOLDOWN_DURATION = 50     # M generations to freeze
FAMILY_COOLDOWN_WEIGHT = 0.05     # weight multiplier during cooldown
DEAD_FAMILIES = {
    "fundamental_scores", "analyst_sentiment", "expanded_fundamental",
    "price_vol_corr", "ravenpack_cat", "size_value", "llm_novel",
    "derivative_interaction", "risk_beta", "news_sentiment", "volatility",
    "earnings_momentum", "quality_trend", "fundamental_vol", "model77_anomaly",
    "intraday_pattern", "fscore", "options_analytics", "analyst_deep",
    "social_scalar", "wild_combos", "risk_metrics", "intraday",
    # research families with 0% eligible after 50+ sims
    "deriv_score", "beta_signal", "regression_alpha", "pipeline_select",
    "earnings_quality", "model77_novel", "fresh_fundamental", "fn_quarterly",
    "composite_cross_category", "cross_dimension", "news_event_signal",
    "momentum_price", "momentum_industry", "tech_macd_like", "tech_breakout",
    "tech_rsi_like", "tech_trend_strength", "tech_bollinger_like",
    "lev_debt_ratios", "lev_distress", "lev_interest_coverage",
    "lev_credit_quality_qoq", "event_credit", "event_mna", "event_business",
    "event_insider", "deriv_fscore_bfl", "deriv_fscore_momentum",
    "deriv_fscore_composites", "deriv_fscore_x_price", "deriv_rank_composites",
    "pure_deriv_scores", "analyst_derivative_scores", "analyst_target_price",
    "analyst_coverage_dispersion", "analyst_revision_breadth",
    "analyst_recommendations", "quality_earnings_stability",
    "quality_balance_sheet_quarterly", "quality_cash_earnings",
    "quality_accruals", "earnings_quality_quarterly",
    "earnings_surprise_magnitude", "earnings_sue_pead", "earnings_torpedo",
    "composite_vqm", "composite_adaptive", "composite_adaptive_regime",
    "composite_risk_adjusted", "risk_systematic_decomp", "risk_idiosyncratic",
    "risk_bab", "risk_correlation_regime", "gap_beta_mean_reversion",
    "gap_cash_conversion", "gap_piotroski", "gap_iv_momentum",
    "gap_corr_regime_shift", "interact_size_x_value_x_quality",
    "interact_value_x_quality", "interact_value_x_momentum",
    "interact_momentum_x_quality", "interact_sentiment_x_fundamental",
    "invest_asset_growth", "invest_net_issuance", "invest_rnd", "invest_capex",
    "profit_margins", "profit_return_on_capital", "profit_cash_return_quarterly",
    "profit_gross", "value_book", "value_earnings_yield", "value_dividend",
    "value_cashflow_yield", "size_microcap_liquidity",
    "size_conditioned_momentum", "size_conditioned_quality",
    "sent_news_reaction", "sent_ravenpack", "sent_price_divergence",
    "sent_level_change", "sent_social_buzz", "sentiment",
    "liq_amihud", "liq_turnover_reversal", "liq_volume_trend",
    "liq_volume_price_divergence", "liq_risk_premium",
    "opt_forward_price", "opt_call_breakeven_ts", "opt_put_breakeven_ts",
    "opt_call_put_skew", "opt_breakeven_dynamics",
    "iv_term_structure", "vol_of_vol", "vol_term_structure",
    "vol_low_vol", "vol_realized_vs_implied",
    "season_data_release_mr", "season_earnings_calendar",
    "compound_momentum", "data_quality", "low_turnover",
    "group_fill_scale", "m77_credit", "m77_profitability",
    "m77_momentum", "m77_quality", "m77_growth", "m77_value",
    "m77_vol_risk", "m77_mega_composite",
    "sc_customer_returns", "sc_network_centrality", "sc_hierarchy_sector",
    "sc_breadth",
    "mr_short_term", "mr_long_term", "mr_regression_residual", "mr_vol_gated",
    "accruals_quality",
}
