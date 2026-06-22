"""Dynamic dataset loader - reads available fields from the team datasets Excel file.

Each teammate gets the same Excel listing all accessible WQ dataset fields. this
module parses it once at startup and exposes categorized field lists that
templates.py, generator.py, and llm_generator.py consume.

If the Excel is missing, falls back to a built-in minimal field set so the bot can
still run (just with fewer exploration options).
"""
from __future__ import annotations

import os
import logging
from pathlib import Path
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

# location of the datasets file(s). the bot loads datasets in this priority order:
#   1. PERSONAL_DATASETS_FILE (full personal dataset - if you have it)
#   2. DATASETS_FILE (team dataset - shared baseline)
#
# if you have the personal file, it REPLACES the team file (since it's a superset).
# if you only have the team file, that's used.
# if neither exists, built-in fallbacks are used.
_BASE_DIR = Path(__file__).resolve().parent
_DEFAULT_TEAM_PATH = _BASE_DIR / "data" / "wq_all_datasets.xlsx"
_DEFAULT_PERSONAL_PATH = _BASE_DIR / "data" / "wq_personal_datasets.xlsx"

DATASETS_FILE = Path(os.getenv("DATASETS_FILE", str(_DEFAULT_TEAM_PATH)))
PERSONAL_DATASETS_FILE = Path(os.getenv("PERSONAL_DATASETS_FILE", str(_DEFAULT_PERSONAL_PATH)))


# sheet-to-category mapping. supports both Excel formats:
#   team Excel: "Dataset_1", "Dataset_2", etc.
#   personal Excel: "Analyst Estimates", "Fundamental Data", etc.

SHEET_CATEGORY_MAP = {
    # team Excel sheet names
    "Dataset_1":  "analyst_estimates",
    "Dataset_2":  "fn_financial",
    "Dataset_3":  "fundamental",
    "Dataset_4":  "derivative_scores",
    "Dataset_5":  "risk_beta",
    "Dataset_6":  "news_data",
    "Dataset_7":  "news_events",
    "Dataset_8":  "hist_vol",
    "Dataset_9":  "options",
    "Dataset_10": "price_volume",
    "Dataset_11": "supply_chain",
    "Dataset_12": "universe_membership",
    "Dataset_13": "vector_data",
    "Dataset_14": "social_sentiment",
    # personal Excel sheet names (human-readable)
    "Analyst Estimates":     "analyst_estimates",
    "Fundamental Data":      "fundamental",
    "Report Footnotes":      "fn_financial",
    "Analysts Factor Model": "model77",          # 3,241 fields - exclusive data
    "Fundamental Scores":    "derivative_scores",
    "Risk Metrics":          "risk_beta",
    "Ravenpack News":        "news_events",
    "US News Data":          "news_data",
    "Options Analytics":     "options",
    "Volatility Data":       "hist_vol",
    "Price Volume":          "price_volume",
    "Relationship Data":     "supply_chain",
    "Universe Dataset":      "universe_membership",
    "Research Sentiment":    "research_sentiment",  # snt1_d1_* fields - exclusive data
    "SM Sentiment":          "social_sentiment",
    "Social Media Data":     "vector_data",
}


# built-in fallback fields (minimal set if Excel missing)
_FALLBACK_FIELDS: dict[str, list[str]] = {
    "price_volume": ["adv20", "cap", "close", "high", "low", "open", "returns", "volume", "vwap", "sharesout", "split", "dividend"],
    "fundamental": ["assets", "assets_curr", "bookvalue_ps", "capex", "cash", "cash_st", "cashflow", "cashflow_op", "cogs", "current_ratio", "debt", "debt_lt", "debt_st", "ebit", "ebitda", "employee", "enterprise_value", "eps", "equity", "income", "operating_income", "sales", "revenue"],
    "analyst_estimates": ["snt1_d1_earningssurprise", "snt1_d1_netearningsrevision", "snt1_d1_dynamicfocusrank", "consensus_analyst_rating", "snt1_d1_earningsrevision", "snt1_d1_stockrank"],
    "derivative_scores": ["analyst_revision_rank_derivative", "cashflow_efficiency_rank_derivative", "composite_factor_score_derivative", "earnings_certainty_rank_derivative", "growth_potential_rank_derivative", "relative_valuation_rank_derivative"],
    "risk_beta": ["beta_last_30_days_spy", "beta_last_60_days_spy", "beta_last_90_days_spy", "beta_last_120_days_spy", "beta_last_360_days_spy"],
    "options": ["implied_volatility_call_30", "implied_volatility_call_60", "implied_volatility_call_90", "implied_volatility_call_120", "implied_volatility_call_180", "implied_volatility_put_30", "implied_volatility_put_60", "implied_volatility_put_90", "implied_volatility_put_120", "implied_volatility_put_180", "historical_volatility_30", "historical_volatility_60", "historical_volatility_90", "historical_volatility_120"],
    "news_data": ["scl12_buzz", "scl12_sentiment", "snt_social_value"],
    "fn_financial": [],
    "hist_vol": [],
    "supply_chain": [],
    "news_events": [],
    "vector_data": [],
    "social_sentiment": [],
    "universe_membership": [],
}


@lru_cache(maxsize=1)
def load_datasets() -> dict[str, list[dict[str, Any]]]:
    """Load all dataset sheets from the best available Excel file.

    Priority: personal dataset (5,903 fields) > team dataset (2,496 fields) > fallback.

    Handles two Excel formats:
      - team format: header at row 0, column named "Field"
      - personal format: header at row 4, column named "id" or "field"
    """
    # try personal first, then team
    chosen_file = None
    if PERSONAL_DATASETS_FILE.exists():
        chosen_file = PERSONAL_DATASETS_FILE
        logger.info(f"[DATASETS] Using PERSONAL dataset: {PERSONAL_DATASETS_FILE.name}")
    elif DATASETS_FILE.exists():
        chosen_file = DATASETS_FILE
        logger.info(f"[DATASETS] Using TEAM dataset: {DATASETS_FILE.name}")
    else:
        logger.warning(f"[DATASETS] No Excel found - using fallback fields")
        return {}

    try:
        import pandas as pd
        xls = pd.ExcelFile(chosen_file)
        result = {}
        total = 0

        for sheet_name in xls.sheet_names:
            category = SHEET_CATEGORY_MAP.get(sheet_name, sheet_name.lower().replace(" ", "_"))

            # try team format first (header at row 0, "Field" column)
            try:
                df = pd.read_excel(xls, sheet_name)
                if "Field" in df.columns:
                    rows = df.to_dict("records")
                    if category in result:
                        result[category].extend(rows)
                    else:
                        result[category] = rows
                    total += len(rows)
                    continue
            except Exception:
                pass

            # try personal format (header at row 4, "id" or "field" column)
            try:
                df = pd.read_excel(xls, sheet_name, header=4)
                field_col = None
                for col in df.columns:
                    if str(col).strip().lower() in ("id", "field"):
                        field_col = col
                        break
                if field_col is not None:
                    # normalize to team format (rename to "Field" for consistency)
                    rename_map = {field_col: "Field"}
                    if "description" in df.columns:
                        rename_map["description"] = "Description"
                    df = df.rename(columns=rename_map)
                    df = df.dropna(subset=["Field"])
                    rows = df.to_dict("records")
                    if category in result:
                        result[category].extend(rows)
                    else:
                        result[category] = rows
                    total += len(rows)
                    continue
            except Exception:
                pass

            logger.warning(f"[DATASETS] Could not parse sheet '{sheet_name}'")

        logger.info(f"[DATASETS] Loaded {total} fields across {len(result)} categories from {chosen_file.name}")
        return result
    except Exception as e:
        logger.warning(f"[DATASETS] Failed to load Excel: {e} - using fallback fields")
        return {}


@lru_cache(maxsize=1)
def get_all_field_names() -> dict[str, list[str]]:
    """Return dict[category] -> list of field name strings."""
    datasets = load_datasets()
    if not datasets:
        return dict(_FALLBACK_FIELDS)

    result = {}
    for category, rows in datasets.items():
        fields = [str(r.get("Field", "")).strip() for r in rows if r.get("Field")]
        result[category] = fields
    return result


# nws18_ fields are completely unusable (reject all operators including days_from_last_change)
BLOCKED_EVENT_FIELDS_PREFIX = ('nws18_',)

def is_blocked_event_field(field: str) -> bool:
    return any(field.lower().startswith(p) for p in BLOCKED_EVENT_FIELDS_PREFIX)

@lru_cache(maxsize=1)
def get_all_valid_fields() -> set[str]:
    """Flat set of every known field name - used for LLM expression validation."""
    all_fields = set()
    for fields in get_all_field_names().values():
        all_fields.update(fields)
    # always include group fields
    all_fields.update({"industry", "subindustry", "sector", "market", "exchange"})
    return all_fields


def expression_uses_valid_fields(expr: str) -> bool:
    """Check if an expression only uses fields available in this bot's dataset.

    Used by the combiner and evolver to filter out near-passers from teammates'
    datasets that use fields this bot doesn't have. returns True if all fields are
    valid (or the check fails), False if invalid fields are found.
    """
    import re
    try:
        valid = get_all_valid_fields()
        tokens = set(re.findall(r'[a-z][a-z0-9_]+', expr.lower()))
        operators = {
            'rank', 'group_rank', 'ts_mean', 'ts_std_dev', 'ts_zscore', 'ts_rank',
            'ts_delta', 'ts_decay_linear', 'ts_corr', 'ts_sum', 'ts_backfill',
            'ts_regression', 'ts_step', 'ts_delay', 'ts_scale', 'ts_arg_min',
            'ts_arg_max', 'ts_covariance', 'ts_product', 'ts_count_nans',
            'ts_quantile', 'ts_av_diff', 'trade_when', 'if_else',
            'abs', 'log', 'sign', 'max', 'min', 'power', 'sqrt',
            'is_nan', 'bucket', 'densify', 'winsorize', 'normalize',
            'group_neutralize', 'group_zscore', 'group_scale', 'group_backfill',
            'group_mean', 'scale', 'quantile', 'zscore',
            'vec_avg', 'vec_sum', 'signed_power', 'inverse', 'reverse', 'hump',
            'kth_element', 'range', 'true', 'false', 'rettype',
            'industry', 'subindustry', 'sector', 'market', 'exchange',
            'days_from_last_change', 'last_diff_value', 'lag', 'std',
            'not', 'and', 'or',
        }
        field_tokens = tokens - operators
        valid_lower = {f.lower() for f in valid}
        # also check the engine-rejected blocklist (fields that are in the xlsx but
        # the runtime engine refuses to evaluate)
        rejected_lower = {f.lower() for f in ENGINE_REJECTED_FIELDS}
        # block if any token is in the rejected list
        for tok in field_tokens:
            if tok in rejected_lower:
                return False
        missing = [t for t in field_tokens if t not in valid_lower and len(t) > 3]
        # nws18_ event fields only work inside a vec_avg() wrapper. don't block them
        # here - the templates handle wrapping correctly.
        return len(missing) == 0
    except Exception:
        return True  # if the check fails, allow it


# convenience accessors for specific field categories.
# these replace the hardcoded lists in templates.py

def get_fundamental_fields() -> list[str]:
    """Core fundamental fields (price_volume + fundamental basics)."""
    names = get_all_field_names()
    core = ["cap", "assets", "sales", "income", "cash"]
    available = set(names.get("fundamental", []) + names.get("price_volume", []))
    return [f for f in core if f in available] or core


def get_deep_fundamental_fields() -> list[str]:
    """Detailed fundamental fields for value/quality templates."""
    names = get_all_field_names()
    candidates = [
        "cashflow_op", "ebit", "ebitda", "enterprise_value",
        "bookvalue_ps", "debt", "equity", "current_ratio",
        "eps", "capex", "cashflow", "cogs", "cash_st",
        "operating_income", "retained_earnings", "working_capital",
        "inventory_turnover", "rd_expense", "revenue",
    ]
    available = set(names.get("fundamental", []))
    result = [f for f in candidates if f in available]
    return result or candidates[:13]  # fallback to original set


def get_analyst_fields() -> list[str]:
    """Curated analyst fields for the template {analyst_field} placeholder.

    Kept tight - only fields proven to work in existing template structures. the
    curated core is always included. the personal dataset's Research Sentiment sheet
    adds snt1_d1_* fields that the team dataset doesn't have.
    """
    # core proven set - always included
    curated = [
        "snt1_d1_earningssurprise", "snt1_d1_netearningsrevision",
        "snt1_d1_dynamicfocusrank", "consensus_analyst_rating",
        "snt1_d1_earningsrevision", "snt1_d1_stockrank",
    ]
    # small expansion from the Excel: forward estimate fields
    expansion_prefixes = ["est_eps", "est_cashflow_op", "est_capex", "est_ptp", "est_fcf"]
    names = get_all_field_names()
    available = names.get("analyst_estimates", [])
    result = list(curated)
    for prefix in expansion_prefixes:
        matches = [a for a in available if a.startswith(prefix)]
        if matches:
            result.append(matches[0])

    # personal dataset bonus: Research Sentiment has extra snt1_d1_* fields
    for f in names.get("research_sentiment", []):
        if f.startswith("snt1_d1_") and f not in result:
            result.append(f)
    return result


def get_sentiment_fields() -> list[str]:
    """Curated sentiment fields for the template {sentiment_field} placeholder.

    Excludes vec fields (scl12_*vec) - those need vec_avg()/vec_sum() operators
    which most templates don't use. vec fields are available to the LLM.
    """
    # core proven scalar sentiment fields only
    curated = ["scl12_buzz", "scl12_sentiment", "snt_social_value"]
    # small expansion: other scalar sentiment fields (NOT vectors)
    scalar_prefixes = ["scl12_buzz", "scl12_sentiment", "snt_social", "snt_buzz", "snt_value"]
    vec_suffixes = ["vec", "typevec", "sentvec", "buzzvec"]

    names = get_all_field_names()
    result = list(curated)
    for cat in ["news_data", "social_sentiment", "vector_data"]:
        for f in names.get(cat, []):
            # skip vector fields - they need vec_avg/vec_sum operators
            if any(f.endswith(s) for s in vec_suffixes):
                continue
            if any(f.startswith(p) for p in scalar_prefixes) and f not in result:
                result.append(f)
    return result


def get_fscore_fields() -> list[str]:
    names = get_all_field_names()
    all_fund = names.get("fundamental", []) + names.get("derivative_scores", [])
    result = [f for f in all_fund if "fscore" in f.lower()]
    if not result:
        result = [
            "fscore_bfl_value", "fscore_bfl_momentum", "fscore_bfl_quality",
            "fscore_bfl_growth", "fscore_bfl_profitability", "fscore_bfl_total",
        ]
    return result


def get_derivative_fields() -> list[str]:
    names = get_all_field_names()
    result = [f for f in names.get("derivative_scores", []) if "derivative" in f.lower()]
    if not result:
        result = _FALLBACK_FIELDS["derivative_scores"]
    return result


def get_options_windows() -> list[int]:
    """Extract available options windows from the options dataset fields."""
    names = get_all_field_names()
    windows = set()
    import re
    for f in names.get("options", []):
        m = re.search(r"_(\d+)$", f)
        if m:
            windows.add(int(m.group(1)))
    # filter to reasonable windows for IV/HV
    reasonable = sorted(w for w in windows if 10 <= w <= 360)
    return reasonable or [30, 60, 90, 120, 180]


def get_pcr_windows() -> list[int]:
    names = get_all_field_names()
    windows = set()
    import re
    for f in names.get("options", []):
        if "pcr_" in f:
            m = re.search(r"_(\d+)$", f)
            if m:
                windows.add(int(m.group(1)))
    return sorted(windows) or [10, 30, 60, 90, 120, 180, 270]


def get_fn_financial_fields() -> list[str]:
    """fn_* financial statement fields - proven portfolio-additive."""
    return get_all_field_names().get("fn_financial", [])


def get_news_fields() -> list[str]:
    """All news/ravenpack fields."""
    names = get_all_field_names()
    return names.get("news_data", []) + names.get("news_events", [])


def get_news_event_fields() -> list[str]:
    """Pure nws18_* event fields (not rp_* ravenpack)."""
    names = get_all_field_names()
    return [f for f in names.get("news_events", []) if f.startswith("nws18_")]


def get_rp_underused_fields() -> list[str]:
    """RavenPack category fields that templates rarely touch."""
    names = get_all_field_names()
    all_rp = [f for f in names.get("news_events", []) if f.startswith("rp_")]
    # exclude the handful the LLM already overuses
    common = {"rp_ess_earnings", "rp_ess_mna", "rp_nip_earnings", "rp_css_credit", "rp_css_legal"}
    return [f for f in all_rp if f not in common]


# engine-rejected fields that are listed in the dataset xlsx but the runtime engine
# refuses to evaluate. these slip past dataset validation (because dataset.xlsx
# contains them) but cause [FAILED] sims with "Attempted to use unknown variable"
# errors. empirically collected from production logs - pre-screen and skip any
# expression containing these.
ENGINE_REJECTED_FIELDS = {
    # risk / beta - different naming than xlsx suggests
    'beta_last_30_days_spy',           # use beta_last_60_days_spy
    'systematic_risk_last_60_days',    # use systematic_risk_last_360_days
    'unsystematic_risk_last_60_days',  # use beta_last_60_days_spy substitute
    'correlation_last_30_days_spy',    # not exposed at runtime
    # risk / beta fields - Excel says TOP3000-only, but the bot runs sweeps across
    # TOP200/500/1000/2000/SP500. each non-TOP3000 sim fails with "unknown
    # variable". until proper universe-aware field gating is added, blocklist them.
    # source: May 5-6 logs - 17 + 10 + 9 + 8 + 5 unknown-var failures respectively.
    'unsystematic_risk_last_90_days',
    'unsystematic_risk_last_360_days',
    'systematic_risk_last_90_days',
    'beta_last_60_days_spy',
    'beta_last_90_days_spy',
    'beta_last_360_days_spy',
    'correlation_last_60_days_spy',
    'correlation_last_90_days_spy',
    'correlation_last_360_days_spy',
    # pv13_ supply chain - TOP3000-only per Excel. same universe issue. ucp_/usc_
    # untapped templates use these heavily and Optuna sweeps them across
    # TOP200/SP500 etc, all failing. disable until universe gating is fixed.
    'pv13_com_page_rank',
    'pv13_com_rk_au',
    # mdl77_ Analysts Factor Model fields - TOP3000-only per Excel.
    # top phantom-error generators from May 5-6 logs (each had 4-14 wasted sims).
    'mdl77_ohistoricalgrowthfactor_pctchgastto',
    'mdl77_earningmomentumfactor_spe2yfvc',
    'mdl77_earningsqualityfactor_ccacw',
    'mdl77_fa_pge_cf',
    'mdl77_earningmomentumfactor_fqsurstd',
    'mdl77_2historicalgrowthfactor_y3fcoq4rqsr',
    'mdl77_pricemomentumfactor_w57w03_rp',
    'mdl77_liquidityriskfactor_curratio',
    'mdl77_historicalgrowthfactor_slope4qcf3y',
    'mdl77_fa_capacq',
    'mdl77_400_ttmsaleev',
    'mdl77_2put_put_opincev',
    'mdl77_2liquidityriskfactor_sip',
    'mdl77_2gdna_pqipmtt',
    'mdl77_2gdna_vefcfmtt',
    'mdl77_2gdna_debtcf',
    'mdl77_2gdna_fc_numrevy1',
    'mdl77_2gdna_rationalalpha',
    'mdl77_pricemomemtummodel_indrelrtn5d_',
    'mdl77_2sensitivityfactor400_nasales',
    'mdl77_ohistoricalgrowthfactor_y3fcq4rqsr',
    # all mdl77_2400_* fields used in untapped_model77 templates - TOP3000-only per
    # Excel. all untapped_model77 templates will be field-validated out. the
    # untapped_model77 family is effectively retired until universe-aware gating is built.
    'mdl77_2400_chgqtrepssurp',
    'mdl77_2400_chg12msip',
    'mdl77_2400_cpgspea2y',
    'mdl77_2400_chginvavgast',
    'mdl77_2400_chg12mtotdebt',
    # group-typed pv13_ fields (industry hierarchy classifiers). the LLM generator
    # (template=llm_rela) wraps them in ts_backfill which expects MATRIX-type input -
    # produces "Incompatible unit for ts_backfill" error. 23 sims wasted on these in
    # May 5-6 logs alone. block until proper densify() wrapping is added to the prompt.
    'pv13_1l_scibr', 'pv13_2l_scibr', 'pv13_3l_scibr',
    'pv13_4l_scibr', 'pv13_5l_scibr', 'pv13_6l_scibr',
    'pv13_di_5l', 'pv13_di_6l',
    # derivative_scores - TOP3000-only
    'composite_factor_score_derivative',
    'multi_factor_static_score_derivative',
    # research sentiment - TOP3000-only or wrong format
    'snt1_d1_buyrecpercent',
    'snt1_d1_sellrecpercent',
    'snt1_d1_uptargetpercent',
    'snt_value_fast_d1',
    # analyst - wrong field name conventions
    'est_eps',                          # use actual_eps_value_quarterly... but that's also rejected
    'est_dividend_ps',
    'actual_eps_value_quarterly',      # listed but engine rejects
    'book_value_per_share_reported_value',
    'anl4_afv4_eps_mean',
    # sentiment / news - listed but rejected
    'snt1_cored1_score',                # the d0v7 templates use this
    'rp_ess_technical',
    # options
    'call_breakeven_150',               # only some breakeven tenors are exposed
    # older known-rejected fields
    'fnd6_epsfx',                       # banned in d0v7 templates already
    'rp_css_ratings',                   # banned in d0v7 templates already
    'mdl110_analyst_sentiment',
    'mdl110_score',
    'scl12_alltype_buzzvec',            # vec form rejected, scl12_buzz works
    'scl12_alltype_sentimentvec',
}


_SATURATED_FIELDS = {
    'assets', 'cash_burn_rate', 'cashflow', 'cashflow_op', 'cogs', 'debt',
    'earnings_momentum_composite_score', 'enterprise_value', 'equity', 'est_eps',
    'est_fcf', 'fn_liab_fair_val_l1_a', 'historical_volatility_20', 'historical_volatility_60',
    'implied_volatility_call_120', 'implied_volatility_call_270', 'implied_volatility_call_30',
    'implied_volatility_call_60', 'implied_volatility_put_120', 'implied_volatility_put_270',
    'implied_volatility_put_30', 'liabilities', 'news_max_up_ret', 'news_pct_1min',
    'nws12_afterhsz_sl', 'one_year_change_total_assets', 'operating_income',
    'parkinson_volatility_120', 'pcr_oi_270', 'rel_ret_comp', 'rp_ess_mna',
    'rp_ess_revenue', 'sales', 'scl12_alltype_buzzvec', 'snt1_d1_earningssurprise',
    'snt1_d1_netearningsrevision',
    # newly identified portfolio-saturated fields from log analysis (each appearing
    # 5+ times in confirmed submissions and triggering SCORE_NEG_BLOCK on new
    # candidates that include them)
    'rp_css_mna', 'fn_comp_non_opt_forfeited_a', 'fn_amortization_of_intangible_assets_a',
    'fn_amortization_of_intangible_assets_q', 'fn_oth_income_loss_net_of_tax_a',
    'fn_accrued_liab_a', 'rel_num_all',
}


def get_fresh_fundamental_fields() -> list[str]:
    """Fundamental fields NOT in any existing submission - guaranteed decorrelated."""
    names = get_all_field_names()
    fund = names.get("fundamental", [])
    # exclude fnd6_/fnd2_ event fields - they need ts_backfill() and break {field}/cap patterns
    return [f for f in fund if f.lower() not in _SATURATED_FIELDS and len(f) > 3
            and "event" not in f.lower() and not f.startswith("fnd6_") and not f.startswith("fnd2_")]


def get_fresh_fn_fields() -> list[str]:
    """fn_financial fields NOT in submissions (317 of 318 are fresh).
    Excludes fnd2_/fnd6_ group-typed fields which silently produce bad sims."""
    names = get_all_field_names()
    fn = names.get("fn_financial", [])
    return [f for f in fn if f.lower() not in _SATURATED_FIELDS
            and "event" not in f.lower()
            and not f.startswith("fnd2_")
            and not f.startswith("fnd6_")]


def get_fresh_estimate_fields() -> list[str]:
    """Analyst estimate fields beyond est_eps and est_fcf."""
    names = get_all_field_names()
    ae = names.get("analyst_estimates", [])
    return [f for f in ae if f.lower() not in _SATURATED_FIELDS
            and f.startswith("est_") and len(f) > 5]


def get_supply_chain_fields() -> list[str]:
    return get_all_field_names().get("supply_chain", [])


def get_hist_vol_fields() -> list[str]:
    return get_all_field_names().get("hist_vol", [])


def get_risk_beta_fields() -> list[str]:
    return get_all_field_names().get("risk_beta", [])


def get_vector_fields() -> list[str]:
    return get_all_field_names().get("vector_data", [])


# model77 fields (from Dataset_1 analyst_estimates).
# these are the pre-computed academic anomaly fields. they live in Dataset_1
# alongside raw analyst estimates.

MODEL77_KEYWORDS = [
    "standardized_unexpected_earnings", "earnings_momentum_composite",
    "earnings_revision_magnitude", "asset_growth_rate", "gross_profit_to_assets",
    "tobins_q_ratio", "distress_risk_measure", "trailing_twelve_month_accruals",
    "forward_median_earnings_yield", "cash_flow_return_on_invested",
    "twelve_month_short_interest", "financial_statement_value_score",
    "fcf_yield_times_forward", "value_momentum_analyst", "momentum_analyst_composite",
    "normalized_earnings_yield", "equity_value_score", "income_statement_value_score",
    "credit_risk_premium", "sustainable_growth_rate", "reinvestment_rate",
    "price_momentum_module", "fundamental_growth_module", "sales_surprise_score",
    "ttm_operating_cash_flow", "ttm_operating_income_to_ev", "ttm_sales_to_enterprise",
    "industry_relative_return", "industry_relative_book", "industry_relative_fcf",
    "implied_minus_realized_volatility", "out_of_money_put_call",
    "visibility_ratio", "treynor_ratio", "cash_burn_rate",
    "capex_to_total_assets", "capex_to_depreciation",
]


def get_model77_fields() -> list[str]:
    """Model77 pre-computed anomaly fields.

    In the personal dataset these are in the 'model77' category (3,241 fields).
    In the team dataset they're scattered across analyst_estimates (or missing).
    """
    names = get_all_field_names()

    # direct category (personal dataset has "Analysts Factor Model" -> "model77")
    if "model77" in names and names["model77"]:
        return names["model77"]

    # fallback: search analyst_estimates for model77-like fields
    ae_fields = names.get("analyst_estimates", [])
    model77 = []
    for f in ae_fields:
        if any(kw in f.lower() for kw in MODEL77_KEYWORDS):
            model77.append(f)
    return model77


def print_dataset_summary():
    """Print a summary of loaded datasets - useful for debugging."""
    names = get_all_field_names()
    total = sum(len(v) for v in names.values())
    print(f"\n{'='*60}")
    print(f"  DATASET SUMMARY - {total} total fields")
    print(f"{'='*60}")
    for cat, fields in sorted(names.items(), key=lambda x: -len(x[1])):
        print(f"  {cat:30s} {len(fields):5d} fields")
        if fields:
            print(f"    e.g.: {', '.join(fields[:3])}")
    print(f"{'='*60}\n")


# family blocking based on available data.
# families that require specific data categories to function. if the category is
# empty/missing, the family cannot produce valid expressions.

FAMILY_REQUIRED_CATEGORIES = {
    "model77_anomaly": ["model77"],
    "model77_combo": ["model77"],
    # note: relationship uses rel_ret_* from supply_chain - available to all via team dataset
    # note: earnings_momentum uses snt1_d1_* - available on WQ platform even if not in team Excel
}

# add personal-only research families to the blocking system
try:
    from research_templates import EWAN_ONLY_FAMILIES
    for fam in EWAN_ONLY_FAMILIES:
        if fam not in FAMILY_REQUIRED_CATEGORIES:
            FAMILY_REQUIRED_CATEGORIES[fam] = ["model77"]
except ImportError:
    pass


def get_blocked_families() -> set[str]:
    """Return families that this bot cannot use due to missing data.

    A family is blocked if all its required data categories are empty.

    Also blocks D0 families when D0_ONLY_MODE=False. an audit on 6 May 2026 showed
    every D0 family fails 100% on the Sharpe gate: 4,061 sims across 17 D0 families
    produced 0 eligible alphas, all rejected with checks_failed:LOW_SHARPE. the D0
    strategy is structurally non-viable in this team's account/region/universe setup.
    blocking saves ~11 hours of wasted compute per cycle across 4 bots.

    Reversible: set D0_ONLY_MODE=True in config to re-enable (and have D0-only mode
    take over generation entirely).
    """
    names = get_all_field_names()
    blocked = set()
    for family, required_cats in FAMILY_REQUIRED_CATEGORIES.items():
        has_any = any(len(names.get(cat, [])) > 0 for cat in required_cats)
        if not has_any:
            blocked.add(family)

    # block D0 families in mixed mode
    try:
        import config as _cfg
        if not getattr(_cfg, "D0_ONLY_MODE", False):
            d0_blocked = {
                # delay0_* legacy families
                "delay0_open_gap_reversal", "delay0_close_vwap_dislocation",
                "delay0_range_position", "delay0_volume_shock",
                "delay0_liquidity_pressure", "delay0_options_intraday",
                "delay0_news_reaction", "delay0_risk_intraday",
                # d0v7_* families
                "d0v7_open_price_reversal", "d0v7_group_reversion",
                "d0v7_news_triggers", "d0v7_sentiment", "d0v7_vol_regime",
                "d0v7_iv_rv", "d0v7_analyst", "d0v7_volume_shock",
                "d0v7_overnight_gap", "d0v7_fundamental",
            }
            blocked |= d0_blocked
    except Exception:
        pass  # never fail the gate on a config issue

    return blocked
