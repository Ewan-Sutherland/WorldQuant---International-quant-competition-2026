"""
v5.6.1: LLM-guided alpha expression generator.

Uses Google Gemini 2.5 Flash (free, 250 RPD) as primary,
Groq GPT-OSS 120B (free, 1000 RPD) as fallback.

Fixes over v5.6:
- Groq model: openai/gpt-oss-120b (was llama-4-scout-17b - much weaker)
- Temperature: 0.7 (was 0.9 - too creative, too many syntax errors)
- Comprehensive operator + field reference in system prompt
- Field name validation (rejects expressions with invalid field names)
- Failed expression feedback in prompt (LLM learns from errors)
"""
from __future__ import annotations

import os
import re
import time
import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

#  Complete verified field set
# Every field name the WQ API actually accepts. Used for validation.

VALID_FIELDS = {
    # Price Volume (pv1)
    "adv20", "cap", "close", "dividend", "high", "low", "open", "returns",
    "sharesout", "split", "volume", "vwap",
    # Group fields
    "industry", "subindustry", "sector", "market", "exchange",
    # Fundamental - common
    "assets", "assets_curr", "bookvalue_ps", "capex", "cash", "cash_st",
    "cashflow", "cashflow_dividends", "cashflow_fin", "cashflow_invst",
    "cashflow_op", "cogs", "current_ratio", "debt", "debt_lt", "debt_st",
    "depre_amort", "ebit", "ebitda", "employee", "enterprise_value", "eps",
    "equity", "income", "sales", "operating_income",
    "inventory_turnover", "rd_expense", "retained_earnings", "working_capital", "revenue",
    # Fundamental Scores (model16)
    "fscore_bfl_value", "fscore_bfl_momentum", "fscore_bfl_quality",
    "fscore_bfl_growth", "fscore_bfl_profitability", "fscore_bfl_total",
    "fscore_bfl_surface", "fscore_bfl_surface_accel",
    "fscore_value", "fscore_momentum", "fscore_quality", "fscore_growth",
    "fscore_profitability", "fscore_total", "fscore_surface", "fscore_surface_accel",
    "analyst_revision_rank_derivative", "cashflow_efficiency_rank_derivative",
    "composite_factor_score_derivative", "earnings_certainty_rank_derivative",
    "growth_potential_rank_derivative", "multi_factor_acceleration_score_derivative",
    "multi_factor_static_score_derivative", "relative_valuation_rank_derivative",
    # Research Sentiment (sentiment1)
    "snt1_cored1_score", "snt1_d1_analystcoverage", "snt1_d1_buyrecpercent",
    "snt1_d1_downtargetpercent", "snt1_d1_dtstsespe", "snt1_d1_dynamicfocusrank",
    "snt1_d1_earningsrevision", "snt1_d1_earningssurprise", "snt1_d1_earningstorpedo",
    "snt1_d1_fundamentalfocusrank", "snt1_d1_longtermepsgrowthest",
    "snt1_d1_netearningsrevision", "snt1_d1_netrecpercent", "snt1_d1_nettargetpercent",
    "snt1_d1_sellrecpercent", "snt1_d1_stockrank", "snt1_d1_uptargetpercent",
    "consensus_analyst_rating",
    # SM Sentiment (socialmedia12)
    "scl12_buzz", "scl12_buzz_fast_d1", "scl12_sentiment", "scl12_sentiment_fast_d1",
    "snt_buzz", "snt_buzz_bfl", "snt_buzz_bfl_fast_d1", "snt_buzz_fast_d1",
    "snt_buzz_ret", "snt_buzz_ret_fast_d1", "snt_value", "snt_value_fast_d1",
    "snt_social_value",
    # Analyst Estimates - key fields
    "est_ptp", "est_fcf", "est_cashflow_op", "est_capex",
    # Ravenpack News - key event sentiment fields
    "rp_css_earnings", "rp_css_revenue", "rp_css_dividends", "rp_css_mna",
    "rp_css_credit", "rp_css_price", "rp_css_product", "rp_css_technical",
    "rp_ess_earnings", "rp_ess_revenue", "rp_ess_dividends", "rp_ess_mna",
    "rp_ess_credit", "rp_ess_price", "rp_ess_product", "rp_ess_technical",
    "nws18_ber", "nws18_bee", "nws18_bam", "nws18_ssc", "nws18_sse",
    # US News Data - key fields
    "news_pct_1min", "news_pct_5_min", "news_pct_10min", "news_pct_30min",
    "news_pct_60min", "news_pct_90min", "news_pct_120min",
    "news_max_up_ret", "news_max_dn_ret", "news_max_up_amt", "news_max_dn_amt",
    "news_open_gap", "news_ls",
}

# Dynamically add volatility/options fields with all known windows
for _prefix in ["implied_volatility_call_", "implied_volatility_put_",
                "implied_volatility_mean_", "implied_volatility_mean_skew_",
                "historical_volatility_"]:
    for _w in [10, 20, 30, 60, 90, 120, 150, 180, 270, 360, 720, 1080]:
        VALID_FIELDS.add(f"{_prefix}{_w}")

for _prefix in ["call_breakeven_", "forward_price_", "option_breakeven_",
                "pcr_oi_", "pcr_vol_"]:
    for _w in [10, 20, 30, 60, 90, 120, 150, 180, 270, 360, 720, 1080]:
        VALID_FIELDS.add(f"{_prefix}{_w}")

# v5.9: Add Parkinson volatility fields
for _w in [10, 20, 30, 60, 90, 120, 150, 180]:
    VALID_FIELDS.add(f"parkinson_volatility_{_w}")

# v5.9: model77 pre-computed anomaly fields (Analysts Factor Model)
VALID_FIELDS.update({
    "standardized_unexpected_earnings", "standardized_unexpected_earnings_2",
    "earnings_momentum_composite_score", "earnings_momentum_analyst_score",
    "earnings_revision_magnitude", "sales_surprise_score",
    "change_in_eps_surprise", "net_fy1_analyst_revisions",
    "three_month_fy1_eps_revision", "six_month_avg_fy1_eps_revision",
    "forward_median_earnings_yield", "normalized_earnings_yield",
    "forward_cash_flow_to_price", "forward_ebitda_to_enterprise_value_2",
    "tobins_q_ratio", "financial_statement_value_score",
    "equity_value_score", "income_statement_value_score",
    "gross_profit_to_assets_ratio", "gross_profit_margin_ttm_2",
    "cash_flow_return_on_invested_capital", "cash_earnings_return_on_equity",
    "return_on_invested_capital_4", "fcf_yield_times_forward_roe",
    "asset_growth_rate", "one_year_change_total_assets",
    "sustainable_growth_rate", "reinvestment_rate",
    "distress_risk_measure", "credit_risk_premium_indicator",
    "twelve_month_short_interest_change",
    "value_momentum_analyst_score", "momentum_analyst_composite_score",
    "price_momentum_module_score", "fundamental_growth_module_score",
    "trailing_twelve_month_accruals",
    "standardized_unexpected_cash_flow", "standardized_unexpected_cashflow",
    "book_leverage_ratio_3", "interest_coverage_ratio_5",
    "yearly_change_leverage", "twelve_month_total_debt_change_2",
    "five_year_eps_stability", "one_year_eps_growth_rate",
    "forward_two_year_eps_growth", "one_year_ahead_eps_growth",
    "one_quarter_ahead_eps_growth", "long_term_growth_estimate",
    "capex_to_total_assets", "capex_to_depreciation_linkage",
    "ttm_operating_cash_flow_to_price", "ttm_operating_income_to_ev",
    "ttm_sales_to_enterprise_value",
    "implied_minus_realized_volatility_2", "implied_option_volatility",
    "out_of_money_put_call_ratio",
    "industry_relative_return_4w", "industry_relative_return_5d",
    "industry_relative_book_to_market", "industry_relative_fcf_to_price",
    "cash_burn_rate", "inventory_change_avg_assets",
    "rd_expense_to_sales_2", "visibility_ratio", "treynor_ratio",
})

# v5.9: Relationship / supply chain data (pv13)
VALID_FIELDS.update({
    "rel_ret_cust", "rel_ret_comp", "rel_ret_all", "rel_ret_part",
    "rel_num_cust", "rel_num_comp", "rel_num_all", "rel_num_part",
    "pv13_ustomergraphrank_page_rank", "pv13_ustomergraphrank_hub_rank",
    "pv13_ustomergraphrank_auth_rank", "pv13_com_page_rank",
})

# v5.9: Risk Metrics (model51)
VALID_FIELDS.update({
    "beta_last_30_days_spy", "beta_last_60_days_spy",
    "beta_last_90_days_spy", "beta_last_360_days_spy",
    "correlation_last_30_days_spy", "correlation_last_60_days_spy",
    "correlation_last_90_days_spy", "correlation_last_360_days_spy",
    "systematic_risk_last_30_days", "systematic_risk_last_60_days",
    "systematic_risk_last_90_days", "systematic_risk_last_360_days",
    "unsystematic_risk_last_30_days", "unsystematic_risk_last_60_days",
    "unsystematic_risk_last_90_days", "unsystematic_risk_last_360_days",
})

# v5.9: Expanded Fundamental fields
VALID_FIELDS.update({
    "operating_income", "retained_earnings", "working_capital",
    "inventory_turnover", "rd_expense", "goodwill", "revenue",
    "return_assets", "return_equity", "sales_ps", "sales_growth",
    "sga_expense", "ppent", "pretax_income", "invested_capital",
    "operating_expense", "income_beforeextra", "income_tax",
    "interest_expense", "receivable", "liabilities", "liabilities_curr",
    "fn_liab_fair_val_l1_a", "fn_liab_fair_val_l1_q",
    "fn_liab_fair_val_a", "fn_liab_fair_val_q",
})

# v6.2.1: fn_ financial statement fields - massive portfolio diversity (+175, +198 score change)
VALID_FIELDS.update({
    "fn_oth_income_loss_fx_transaction_and_tax_translation_adj_a",
    "fn_oth_income_loss_fx_transaction_and_tax_translation_adj_q",
    "fn_accum_oth_income_loss_fx_adj_net_of_tax_a",
    "fn_accum_oth_income_loss_fx_adj_net_of_tax_q",
    "fn_assets_fair_val_l1_a", "fn_assets_fair_val_l1_q",
    "fn_assets_fair_val_l2_a", "fn_assets_fair_val_l2_q",
    "fn_debt_instrument_carrying_amount_a", "fn_debt_instrument_carrying_amount_q",
    "fn_allocated_share_based_compensation_expense_a",
    "fn_comprehensive_income_net_of_tax_a", "fn_comprehensive_income_net_of_tax_q",
    "fn_accum_oth_income_loss_net_of_tax_a",
    "fn_eff_income_tax_rate_continuing_operations_a",
    "fn_income_tax_expense_a",
    "fn_def_tax_assets_liab_net_a",
    "fn_liab_fair_val_l2_a", "fn_liab_fair_val_l3_a",
    "parkinson_volatility_120", "parkinson_volatility_150",
    "parkinson_volatility_180", "parkinson_volatility_60",
    "parkinson_volatility_90", "parkinson_volatility_30",
})

# v5.9: Additional analyst estimate fields
VALID_FIELDS.update({
    "est_eps", "est_epsr", "est_fcf", "est_fcf_ps", "est_ptp",
    "est_cashflow_op", "est_capex", "est_ebit", "est_ebitda",
    "est_sales", "est_netprofit", "est_dividend_ps",
})

# v6.2.1: Vector dataset fields (multiple values per stock per day - use vec_avg/vec_sum ONLY)
VALID_FIELDS.update({
    # Social media vectors
    "scl12_alltype_buzzvec", "scl12_alltype_sentvec",
    # News vectors
    "nws12_afterhsz_sl", "nws12_prez_result2",
    # v6.2.1: scl15_d1_sentiment, fnd6_epsfx, fnd6_newqeventv110_optrfrq - ALL DEAD, removed
})

# v6.2.1: model_data (mdf_*), mdl175_*, fam_* - ALL DEAD on this account, removed from VALID_FIELDS

# v6.2.1: New untapped fields for 10 new template families
VALID_FIELDS.update({
    # Supply chain (pv13) - pv13_custretsig_retsig REMOVED: consistently S=-1.4
    # RavenPack category sentiment
    "rp_ess_insider", "rp_css_legal", "rp_nip_earnings",  # nws18_event_relevance REMOVED - event field
    "rp_css_mna", "rp_ess_mna", "rp_css_revenue", "rp_ess_revenue",
    "rp_css_product", "rp_ess_product", "rp_css_credit",
    "rp_css_dividends", "rp_ess_dividends", "rp_nip_mna",
    "rp_css_insider", "rp_nip_revenue", "rp_nip_legal",
    # Options analytics - breakeven & forward price
    "put_breakeven_30", "put_breakeven_60", "put_breakeven_90",
    "put_breakeven_120", "put_breakeven_180",
    "option_breakeven_30", "option_breakeven_60", "option_breakeven_90",
    "option_breakeven_120", "option_breakeven_180",
    # Fundamental scores (model16)
    "fscore_bfl_growth", "fscore_bfl_surface",
    "growth_potential_rank_derivative", "composite_factor_score_derivative",
    "analyst_revision_rank_derivative", "cashflow_efficiency_rank_derivative",
    "earnings_certainty_rank_derivative", "relative_valuation_rank_derivative",
    "multi_factor_acceleration_score_derivative", "multi_factor_static_score_derivative",
    # Risk metrics - full field names
    "beta_last_30_days_spy", "beta_last_90_days_spy", "beta_last_360_days_spy",
    "correlation_last_30_days_spy", "correlation_last_90_days_spy", "correlation_last_360_days_spy",
    "systematic_risk_last_30_days", "systematic_risk_last_90_days", "systematic_risk_last_360_days",
    "unsystematic_risk_last_30_days", "unsystematic_risk_last_90_days", "unsystematic_risk_last_360_days",
    # Historical volatility
    "historical_volatility_10", "historical_volatility_20", "historical_volatility_30",
    "historical_volatility_60", "historical_volatility_90", "historical_volatility_120",
    # Deep analyst sentiment
    "snt1_d1_earningstorpedo", "snt1_d1_uptargetpercent", "snt1_d1_downtargetpercent",
    "snt1_d1_analystcoverage", "snt1_d1_longtermepsgrowthest", "snt1_d1_stockrank",
    "snt1_d1_earningsrevision", "snt1_d1_fundamentalfocusrank",
    "snt1_cored1_score", "snt1_d1_netrecpercent", "snt1_d1_nettargetpercent",
    # Social media scalar
    "scl12_buzz", "scl12_buzz_fast_d1", "scl12_sentiment", "scl12_sentiment_fast_d1",
    "snt_value", "snt_value_fast_d1", "snt_buzz_ret", "snt_buzz_ret_fast_d1",
    "snt_buzz", "snt_buzz_fast_d1", "snt_buzz_bfl", "snt_buzz_bfl_fast_d1",
})

# v7.0: Merge in ALL fields from the team datasets Excel
# This ensures LLM-generated expressions can use any field the team has access to
try:
    from datasets import get_all_valid_fields
    _dynamic_fields = get_all_valid_fields()
    VALID_FIELDS.update(_dynamic_fields)
    logger.info(f"[LLM_FIELDS] Loaded {len(_dynamic_fields)} dynamic fields from datasets")
except Exception as _e:
    logger.info(f"[LLM_FIELDS] Using hardcoded fields only: {_e}")


#  Operators

VALID_OPERATORS = {
    "rank", "group_rank", "ts_mean", "ts_std_dev", "ts_zscore", "ts_rank",
    "ts_delta", "ts_decay_linear", "ts_corr", "ts_sum",
    "ts_arg_min", "ts_arg_max", "ts_covariance", "ts_product", "ts_backfill",
    "ts_count_nans", "ts_regression", "ts_step", "ts_delay", "ts_scale",
    "ts_quantile",
    "trade_when", "if_else",  # v6.2.1: if_else is base-level conditional (no position holding)
    "abs", "log", "sign", "max", "min", "power",
    "is_nan", "bucket", "densify", "winsorize", "normalize",
    "group_neutralize", "group_zscore", "group_scale", "group_backfill", "group_mean",
    "scale", "quantile", "zscore",
    "vec_avg", "vec_sum",  # v6.2.1: ONLY these two vec_ operators work
    "signed_power", "sqrt", "inverse", "reverse", "hump",
    # v6.2.1: removed ts_min, ts_max, ts_argmin, ts_argmax - DON'T EXIST on platform
    # v6.2.1: last_diff_value, days_from_last_change - exist but LLM misuses them, kept banned
    # v6.2.1: pasteurize - inaccessible at base level
    "kth_element",
    "ts_av_diff",  # v6.2.1: ts_mean(x,n) - x - proven in mdf_eg3 alpha (S=1.59)
}

LOCKED_OPERATORS = {"ts_skewness", "ts_kurtosis", "ts_momentum"}

# v6.2: Fields that don't exist in WQ BRAIN but LLMs keep generating
BANNED_FIELDS = {
    "unsystematic_risk",   # correct form is unsystematic_risk_last_30_days etc.
    "systematic_risk",     # correct form is systematic_risk_last_30_days etc.
    "short_interest",      # not a valid field name
    "institutional_ownership",  # not available
    "put_call_ratio",      # use pcr_oi_30 etc. instead
    # v6.2.1: ALL confirmed dead fields from overnight logs
    "mdf_nps", "mdf_oey", "mdf_rds", "mdf_pbk", "mdf_eg3", "mdf_sg3",  # model_data family ALL dead
    "mdl175_grossprofit", "mdl175_revenuettm", "mdl175_volatility",  # mdl175 ALL dead
    "fnd6_epsfx",          # event_driven dead
    "fam_earn_surp_pct", "fam_roe_rank",  # event_driven dead
    "scl15_d1_sentiment",  # doesn't exist - not in any dataset
    "nws18_event_relevance",  # v6.2.1: event field - ts_backfill doesn't support event inputs
    "gross_profit",        # v6.2.1: NOT a valid WQ field - use gross_profit_to_assets_ratio instead
}

# v6.2.1: Operators that are inaccessible or broken at base level
BANNED_OPERATORS = {
    "vec_count", "vec_ir", "vec_max", "vec_min", "vec_stddev", "vec_range",  # only vec_avg and vec_sum work
    "pasteurize",          # inaccessible at base level
    "last_diff_value",     # needs lookback param we don't provide
    "days_from_last_change",  # needs lookback param we don't provide
}

# v7.0: Clean up - remove banned fields from valid set to avoid conflicts
VALID_FIELDS -= BANNED_FIELDS


#  v7.2.12 system prompt - data-grounded, anti-overlap

SYSTEM_PROMPT = """You are a quantitative researcher generating alpha expressions for WorldQuant BRAIN.

YOUR MISSION: produce alphas that ADD score to a team portfolio that's already 80% concentrated in price/cap/fundamentals. The team has 110+ existing alphas; novelty matters more than predicted Sharpe (Optuna will tune Sharpe later, but it cannot fix correlation).


CRITICAL CONSTRAINT - SELF-CORRELATION


WQ rejects any new alpha whose daily PnL correlates >0.7 with an already-submitted alpha. Your alphas will compete against the team's existing 110+ submissions on this test. Most alphas centered on saturated fields will fail this gate even if their individual Sharpe is excellent.

SATURATED - DO NOT center an alpha on these (they're in 80%+ of submitted portfolio):
  returns, cap, income, close, eps, adv20, assets, debt, vwap, volume, snt_social_value

You may USE these as secondary modifiers (e.g., scale by rank(cap)), but they must NOT be the primary signal source.


PRODUCTIVE UNDER-USED FIELDS - center alphas on THESE


These fields produce eligible alphas (Sharpe >= 1.4) but appear in fewer than 30 submitted alphas. They're your sweet spot - proven productive, low correlation risk:

OPTIONS VOLATILITY SURFACE (8-10 eligible uses each, avg Sharpe 1.72-1.85):
  implied_volatility_mean_skew_10, _20, _30, _90, _120, _150, _180, _270, _360, _720
  These measure the call-put IV asymmetry at multiple horizons.

PUT-CALL RATIOS (3-5 eligible uses, avg Sharpe 1.53-1.60):
  pcr_oi_30, pcr_oi_60, pcr_oi_150, pcr_oi_270 (open interest ratios)
  pcr_vol_20, pcr_vol_30, pcr_vol_60 (volume ratios)

OPTIONS-IMPLIED PRICES (zero current uses, novel territory):
  call_breakeven_30, call_breakeven_60, call_breakeven_120
  put_breakeven_30, put_breakeven_60, put_breakeven_120
  forward_price_30, forward_price_60

ANALYST SIGNALS (3-8 eligible uses, avg Sharpe 1.71-1.96):
  anl4_afv4_eps_mean (highest avg Sharpe = 1.96, only 3 uses)
  rel_num_part (supply chain partner count, 8 uses, S=1.80)

QUARTERLY FUNDAMENTAL DETAIL (3 uses, S=1.75):
  fnd6_cptnewqv1300_oibdpq

COMPOSITE FACTOR SCORES (under-used, 3-7 eligible uses):
  fscore_bfl_growth, fscore_bfl_momentum

VOLATILITY (under-used relative to portfolio):
  parkinson_volatility_30, parkinson_volatility_60, parkinson_volatility_120
  historical_volatility_30, historical_volatility_90, historical_volatility_180


ANOMALY CONCEPTS - your team has ZERO exposure to these


Each is academically documented and behavioral or microstructural in origin (slow to decay). Pick ONE per expression and translate the mechanism:

1. IV SKEW PREDICTION (Xing/Zhang/Zhao 2010)
   Mechanism: When informed traders expect bad news, they buy out-of-money puts, steepening put-side IV. The resulting skew predicts negative equity returns over 1-4 weeks.
   Use: implied_volatility_mean_skew_{30,90,180,360}
   Pattern: -rank(ts_backfill(implied_volatility_mean_skew_90, 60)) - short steeper skew
   Or: rank(implied_volatility_call_60 - implied_volatility_put_60) - call-put gap

2. PUT-CALL OPEN INTEREST RATIO (Pan/Poteshman 2006)
   Mechanism: Elevated put/call OI = informed bearish positioning. Mean-reverts as info becomes public.
   Use: pcr_oi_{30,60,150,270}, pcr_vol_{20,30}
   Pattern: -rank(ts_zscore(ts_backfill(pcr_oi_60, 60), 30))

3. PUT-CALL PARITY DEVIATIONS (Cremers/Weinbaum 2010)
   Mechanism: When forward_price implied by options diverges from spot, the spread predicts future equity returns over ~1 week.
   Use: call_breakeven_*, put_breakeven_*, forward_price_*
   Pattern: rank(ts_backfill(call_breakeven_60, 60) / close - 1)
   Or: rank((call_breakeven_60 - put_breakeven_60) / (call_breakeven_60 + put_breakeven_60 + 0.001))

4. ROUND-NUMBER PRICE EFFECT (Bhattacharya/Holden/Jacobsen 2011)
   Mechanism: Stocks closing just below round dollars (.99) see negative next-day returns; just above (.01) see positive. Cluster undercutting creates predictable buy-sell imbalances.
   Use: close, with cents extraction
   Pattern: -rank((close - bucket(close, range="0,1000,1")) - 0.5)
   Or: rank(if_else((close - bucket(close, range="0,1000,1")) > 0.5, -1, 1))

5. 52-WEEK HIGH ANCHORING (George/Hwang 2004)
   Mechanism: Stocks near 52-week high have continued momentum; investors anchor to the high as reference point.
   Use: high, with ts_arg_max (returns DAYS since the maximum, 0=today)
   Pattern: rank(-ts_arg_max(high, 252)) - fewer days since 52w high -> higher rank
   Or: rank(-ts_arg_max(high, 126)) - 6-month version (lower noise)
   Note: Lower ts_arg_max value = more recent peak = stronger momentum anchor

6. LOTTERY-LIKE STOCK PREFERENCE (Bali/Cakici/Whitelaw 2011)
   Mechanism: Stocks with high recent volatility / extreme single-day movements underperform - retail investors overpay for "lottery tickets."
   Use: high, low (for daily range proxy); implied_volatility_call_30 (IV proxy for lottery demand)
   Pattern: -rank(ts_decay_linear((high - low) / (close + 0.001), 21)) - recent range as lottery proxy
   Or: -rank(implied_volatility_call_30) - high IV stocks underperform on average
   Note: Without ts_max, exact "max-in-window" can't be computed - these are weakened approximations.

7. CASH FLOW DIRECT-METHOD SUPERIORITY (Foerster/Tsagarelis/Wang 2017)
   Mechanism: Disaggregated direct-method cash flows predict returns better than profits/earnings. Free cash flow yield (operating cashflow minus capex, scaled by market cap) outperforms earnings yield by 10%+ annually risk-adjusted.
   Why not arbitraged: Most quant signals use earnings-based metrics (eps, income); cash flow decomposition requires more careful data parsing.
   Use: cashflow_op, capex, cashflow_invst, cashflow_dividends - NOT eps (saturated)
   Pattern: rank((cashflow_op - capex) / (cap + 0.001)) - free cash flow yield
   Or: rank(ts_delta(cashflow_op, 252) / (cap + 0.001)) - operating CF growth, market-scaled
   Or: rank((cashflow_op - income) / (cap + 0.001)) - quality of earnings (CF beats accruals)

8. CROSS-FIRM LEADER-FOLLOWER LAG (Scherbina/Schlusche 2014)
   Mechanism: Some stocks lead others by 1-2 days; information diffuses through supply-chain and economic-link networks. Followers under-react initially. Independent of firm size.
   Why not arbitraged: Requires network/relationship data most teams don't access.
   Use: rel_ret_cust, rel_ret_comp, rel_num_cust, rel_num_part (supply-chain returns + counts)
   Pattern: rank(ts_backfill(rel_ret_cust, 60)) - customer return spillover predicts our return
   Or: ts_delay(rank(group_mean(returns, industry)), 2) - lagged industry leader signal
   Or: rank(ts_backfill(rel_ret_comp, 60) - ts_backfill(rel_ret_cust, 60)) - competitor vs customer divergence

9. EARNINGS EXPECTATIONS BEAT PERSISTENCE (Bartov/Givoly/Hayn 2002)
   Mechanism: Stocks that meet/beat EPS estimates earn ~3-quarter abnormal returns. Surprise effect persists much longer than typical PEAD windows; the market gradually recognizes the consistency.
   Why not arbitraged: Most quant teams use 30-60 day PEAD windows; the 3-quarter persistence is under-exploited.
   Use: est_eps, est_epsr, eps, est_revenue
   Pattern: ts_decay_linear(rank((eps - ts_backfill(est_epsr, 60)) / (abs(est_epsr) + 0.001)), 63)
   Or: rank(ts_sum(sign(eps - ts_backfill(est_epsr, 60)), 90)) - 90-day count of beats
   Or: group_zscore((eps - ts_backfill(est_epsr, 60)) / (abs(est_epsr) + 0.001), industry) - peer-relative


PROPOSE YOUR OWN ANOMALIES (encouraged)


You may propose alphas based on anomalies NOT in the list above. If you do, the JSON `novelty_argument` field MUST explain:
  (a) the mechanism in 1-2 sentences
  (b) why this anomaly hasn't been arbitraged away (behavioral? institutional friction? data access? regulatory?)
  (c) the academic citation if known

If you cannot articulate (b), the anomaly is probably already mined and your alpha will fail self-correlation. Stick to the listed concepts.


WQ FASTEXPRESSION SYNTAX


CORE OPERATORS (use these freely):
  Arithmetic: +, -, *, /, abs, log, sign, max, min, power, sqrt, signed_power, inverse, reverse
  Cross-sectional: rank, group_rank, group_zscore, group_neutralize, scale, normalize, quantile, winsorize
  Time-series: ts_mean, ts_std_dev, ts_zscore, ts_rank, ts_delta, ts_decay_linear, ts_corr, ts_sum,
               ts_arg_min, ts_arg_max, ts_covariance, ts_product, ts_backfill, ts_count_nans,
               ts_regression, ts_step, ts_delay, ts_scale, ts_quantile, ts_av_diff, kth_element
  Vector (only these two): vec_avg, vec_sum
  Conditional: trade_when (holds position), if_else (no holding)
  Other: bucket, densify, hump, is_nan
  Groups: industry, subindustry, sector, market, exchange

LOCKED - DO NOT USE: ts_skewness, ts_kurtosis, ts_momentum, ts_min, ts_max (use ts_arg_min/max instead)
                     vec_count, vec_ir, vec_max, vec_stddev, pasteurize, last_diff_value, days_from_last_change

CRITICAL RULES:
  1. Every expression MUST contain rank() or group_rank() at the outer level
  2. For sparse data (options, sentiment, news, supply chain): wrap field in ts_backfill(field, 60)
  3. Keep nesting shallow: 2-4 function calls max. Deeper = overfit.
  4. Avoid stacking 3+ rank() calls - produces high-turnover noise alphas
  5. NEVER center on saturated fields (returns, cap, income, close, eps, adv20, assets)
  6. Output JSON only - see format below


OUTPUT FORMAT


For each alpha, output EXACTLY two lines, in this order:

  # anomaly=<concept>; novelty=<one sentence why this isn't arbitraged + why decorrelated>
  <valid WQ FastExpression>

Then a blank line, then the next alpha. Example:

  # anomaly=iv_skew; novelty=Put-side IV asymmetry reflects informed bearish bets; team uses zero skew fields
  -rank(ts_backfill(implied_volatility_mean_skew_90, 60))

  # anomaly=parity_deviation; novelty=Forward-price gap proxies institutional positioning; team has zero call_breakeven uses
  rank(ts_backfill(call_breakeven_60, 60) / close - 1)

The `# anomaly=...` line is a COMMENT. The bot's parser will strip it. The expression line MUST be valid WQ syntax with no commentary.

Do NOT use markdown code fences. Do NOT number the alphas. Just comment+expression+blank, repeated."""




def _build_generation_prompt(
    *,
    submitted_exprs: list[str],
    best_near_passers: list[dict],
    underexplored_categories: list[str],
    recent_failures: list[dict],
    recent_eligible_count: int,
    recently_generated: list[str] | None = None,
    num_expressions: int = 5,
) -> str:
    """v7.2.12: Anti-correlation user prompt - show team-saturated structure, not winning patterns.

    The system prompt already covers WHAT to generate (anomalies, fields, syntax).
    This user prompt focuses on WHAT NOT to clone - it shows the LLM the structural
    signature of recent saturated-territory alphas so it can deliberately diverge.
    """

    # Show what's been submitted so the LLM sees the saturation surface, NOT to copy
    saturated_section = ""
    if submitted_exprs:
        # Pick a diverse sample, not just the most recent (which would all look similar)
        sample_size = min(8, len(submitted_exprs))
        # Take evenly-spaced samples across the list
        if len(submitted_exprs) <= sample_size:
            sample = submitted_exprs
        else:
            step = len(submitted_exprs) // sample_size
            sample = [submitted_exprs[i * step] for i in range(sample_size)]
        saturated_section = (
            "TEAM PORTFOLIO STRUCTURAL SIGNATURE (your alphas must NOT resemble these):\n"
        )
        for expr in sample:
            saturated_section += f"  - {expr[:140]}\n"

    # Recent failures are still useful as syntax hints
    failure_section = ""
    if recent_failures:
        failure_section = "\nRECENT SYNTAX ERRORS - avoid these specific mistakes:\n"
        for f in recent_failures[:4]:
            err = f.get('error', '?')[:80]
            expr_snip = f.get('expression', '?')[:80]
            failure_section += f"  x {err} -> {expr_snip}\n"

    # Avoid repeating within session
    recently_generated_section = ""
    if recently_generated:
        recently_generated_section = "\nALREADY PROPOSED THIS SESSION - pick different anomalies/fields:\n"
        for expr in recently_generated[-10:]:
            recently_generated_section += f"  - {expr[:120]}\n"

    return f"""Generate {num_expressions} alpha expressions targeting genuinely DIFFERENT anomalies.

{saturated_section}{failure_section}{recently_generated_section}

REQUIREMENTS:
1. Each expression must target a DIFFERENT anomaly (no two from the same concept).
2. At least {max(2, num_expressions // 2)} expressions must use FIELDS from the under-used productive list (options skew, pcr ratios, breakeven prices, anl4_*, fnd6_*, fscore_bfl_growth/momentum, parkinson_volatility_*).
3. NEVER center an expression on returns, cap, income, close, eps, adv20, assets, debt, vwap, or volume. These can appear as MODIFIERS only.
4. Reuse the saturated portfolio's structural patterns is FORBIDDEN. If you see ts_zscore(eps_change, 60) in the saturated list, do NOT propose ts_zscore(est_eps_change, 60) - it correlates.
5. For each expression, the novelty_argument MUST be specific and falsifiable, not generic claims like "uses different data."

Total team eligible alphas so far: {recent_eligible_count}. We need DIVERSITY, not more of the same.

Output JSON array of {num_expressions} elements following the schema in the system prompt. NO markdown fences, NO commentary, just the JSON array."""



#  API clients

class LLMClient:
    """Handles API calls to Gemini and Groq with automatic fallback and key rotation."""

    def __init__(self):
        # v6.2.1: Support multiple Gemini API keys for rate limit rotation
        # Set in .env as: GEMINI_API_KEYS=key1,key2,key3,key4,key5
        # Falls back to single GEMINI_API_KEY if GEMINI_API_KEYS not set
        multi_keys = os.environ.get("GEMINI_API_KEYS", "")
        if multi_keys:
            self.gemini_keys = [k.strip() for k in multi_keys.split(",") if k.strip()]
        else:
            single = os.environ.get("GEMINI_API_KEY", "")
            self.gemini_keys = [single] if single else []

        # Same for Groq - GROQ_API_KEYS=key1,key2 or single GROQ_API_KEY
        multi_groq = os.environ.get("GROQ_API_KEYS", "")
        if multi_groq:
            self.groq_keys = [k.strip() for k in multi_groq.split(",") if k.strip()]
        else:
            single_groq = os.environ.get("GROQ_API_KEY", "")
            self.groq_keys = [single_groq] if single_groq else []

        # Per-key tracking
        self._gemini_calls = [0] * len(self.gemini_keys)
        self._gemini_rate_limited_until = [0.0] * len(self.gemini_keys)  # timestamp
        self._groq_calls = [0] * len(self.groq_keys)
        self._groq_rate_limited_until = [0.0] * len(self.groq_keys)
        self._last_reset_day = 0

        # Log key count
        if self.gemini_keys:
            print(f"[LLM] {len(self.gemini_keys)} Gemini API key(s) loaded - rotating on rate limit")
        else:
            print("[LLM_WARN] No GEMINI_API_KEY(S) set")
        if self.groq_keys:
            print(f"[LLM] {len(self.groq_keys)} Groq API key(s) loaded")
        else:
            print("[LLM_WARN] No GROQ_API_KEY(S) set - no fallback when Gemini rate-limits!")

    @property
    def gemini_key(self):
        """Legacy compat - return first key or empty."""
        return self.gemini_keys[0] if self.gemini_keys else ""

    @property
    def groq_key(self):
        return self.groq_keys[0] if self.groq_keys else ""

    def _reset_daily_counters(self):
        today = int(time.time() // 86400)
        if today != self._last_reset_day:
            self._gemini_calls = [0] * len(self.gemini_keys)
            self._groq_calls = [0] * len(self.groq_keys)
            self._last_reset_day = today

    def generate(self, system_prompt: str, user_prompt: str) -> str | None:
        """Try all Gemini keys, then all Groq keys. Returns raw text or None.

        v7.2.11: Distinguishes between 'rate_limit' (key exhausted, mark dead
        until end-of-day) and 'overload' (Google server 503, retry in 5 min).
        Previously, 503 was treated identically to 429 - meaning a single 503
        would mark a key as exhausted for the entire day. With Google's
        ongoing 503 surge from the Feb 2026 model launches, this caused all
        13 Gemini keys to get nuked within minutes, dropping LLM
        contribution to ~50% of attempts.
        """
        self._reset_daily_counters()
        now = time.time()
        # v6.2.1: End of today (UTC) for daily exhaustion marking
        end_of_day = (int(now // 86400) + 1) * 86400
        # v7.2.11: Short backoff for 503 overloads (5 minutes)
        overload_backoff = now + 300

        # Try each Gemini key - skip exhausted/rate-limited ones SILENTLY
        gemini_attempted = 0
        any_overload_seen = False
        for i, key in enumerate(self.gemini_keys):
            if self._gemini_calls[i] >= 18:  # 20 RPD free tier with buffer
                continue
            if now < self._gemini_rate_limited_until[i]:
                continue  # exhausted for today or in cooldown - skip silently

            gemini_attempted += 1
            result, status = self._call_gemini(key, system_prompt, user_prompt)
            if status == 'ok':
                self._gemini_calls[i] += 1
                return result
            elif status == 'overload':
                # v7.2.11: 503 = Google server overload. Key is fine, just back
                # off briefly and try the next key. Don't mark dead-for-day.
                self._gemini_rate_limited_until[i] = overload_backoff
                any_overload_seen = True
                continue
            elif status == 'rate_limit':
                # 429 = quota exhausted, mark key dead for rest of day
                self._gemini_rate_limited_until[i] = end_of_day
                # Only log once per key exhaustion, not every call attempt
                remaining = sum(1 for j in range(len(self.gemini_keys))
                              if self._gemini_calls[j] < 18 and now >= self._gemini_rate_limited_until[j])
                if remaining == 0 and i == len(self.gemini_keys) - 1:
                    print(f"[LLM] All {len(self.gemini_keys)} Gemini keys exhausted for today")
            else:  # 'error' or 'no_content'
                # transient error - short backoff (1 min)
                self._gemini_rate_limited_until[i] = now + 60

        # If all Gemini calls returned 503 (not quota), log it once
        if any_overload_seen and gemini_attempted > 0:
            print(f"[LLM] Gemini 503 overload (Google server capacity issue) - falling back to Groq")

        # Fallback: try each Groq key
        for i, key in enumerate(self.groq_keys):
            if self._groq_calls[i] >= 18:  # same free tier limit
                continue
            if now < self._groq_rate_limited_until[i]:
                continue

            result = self._call_groq(key, system_prompt, user_prompt)
            if result is not None:
                self._groq_calls[i] += 1
                return result
            else:
                self._groq_rate_limited_until[i] = end_of_day

        return None

    def _call_gemini(self, api_key: str, system_prompt: str, user_prompt: str) -> tuple[str | None, str]:
        """Call Google Gemini 2.5 Flash via REST API.

        v7.2.11: Returns (text, status) tuple instead of just text.
        status is one of:
          - 'ok': call succeeded, text contains response
          - 'rate_limit': 429 - key is exhausted for today, don't retry
          - 'overload': 503 - server overload, this key is FINE, retry in ~5 min
          - 'error': other error, give up on this key for now
          - 'no_content': 200 but empty response, treat as 'error'
        """
        try:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"gemini-2.5-flash:generateContent?key={api_key}"
            )
            payload = {
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"parts": [{"text": user_prompt}]}],
                "generationConfig": {
                    "temperature": 0.7,
                    "maxOutputTokens": 1500,
                },
            }
            resp = requests.post(url, json=payload, timeout=30)

            if resp.status_code == 429:
                return None, 'rate_limit'  # quota exhausted for this key
            if resp.status_code == 503:
                # v7.2.11: server overload - Google's problem, not ours.
                # Per the Feb 2026 incident, 503 affects all tiers and lasts
                # until Google adds capacity. The key is still valid; we just
                # need to back off briefly (5-10 min) and retry.
                return None, 'overload'
            if resp.status_code != 200:
                print(f"[LLM] Gemini error {resp.status_code}: {resp.text[:200]}")
                return None, 'error'

            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return None, 'no_content'

            text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            if text and text.strip():
                return text.strip(), 'ok'
            return None, 'no_content'

        except Exception as exc:
            print(f"[LLM] Gemini exception: {exc}")
            return None, 'error'

    def _call_groq(self, api_key: str, system_prompt: str, user_prompt: str) -> str | None:
        """Call Groq GPT-OSS 120B (OpenAI-compatible). Prompt caching is automatic."""
        try:
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": "openai/gpt-oss-120b",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.7,
                "max_tokens": 1500,
            }
            resp = requests.post(url, json=payload, headers=headers, timeout=30)

            if resp.status_code == 429:
                return None  # v6.2.1: rate limit logging handled by generate()
            if resp.status_code != 200:
                print(f"[LLM] Groq error {resp.status_code}: {resp.text[:200]}")
                return None

            data = resp.json()
            choices = data.get("choices", [])
            if not choices:
                return None

            text = choices[0].get("message", {}).get("content", "")
            return text.strip() if text else None

        except Exception as exc:
            print(f"[LLM] Groq exception: {exc}")
            return None

    @property
    def available(self) -> bool:
        return bool(self.gemini_key or self.groq_key)


#  Expression validation

def validate_expression(expr: str) -> tuple[bool, str]:
    """
    Validate that an LLM-generated expression is syntactically plausible
    AND uses real WQ data fields.
    Returns (is_valid, reason).
    """
    expr = expr.strip()

    # v7.2: Replace scientific notation (WQ doesn't support 1e-6 etc)
    expr = re.sub(r'\d+(?:\.\d+)?[eE][-+]?\d+', lambda m: f"{float(m.group(0)):.10f}".rstrip('0').rstrip('.'), expr)

    if not expr:
        return False, "empty"

    if len(expr) > 500:
        return False, "too_long"

    if len(expr) < 8:
        return False, "too_short"

    # Must not contain Python/code artifacts
    for bad in ["import ", "def ", "print(", "return ", "lambda ", "class ", "#", "//", "```", "\"", "'"]:
        if bad in expr:
            return False, f"contains_code: {bad}"

    # Must not start with a number (likely a list item)
    if re.match(r"^\d+[\.\):]", expr):
        return False, "starts_with_number"

    # Check balanced parentheses
    depth = 0
    for ch in expr:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if depth < 0:
            return False, "unbalanced_parens"
    if depth != 0:
        return False, "unbalanced_parens"

    # Must contain at least one function call
    if "(" not in expr:
        return False, "no_function_calls"

    # Check for locked operators
    expr_lower = expr.lower()
    for locked in LOCKED_OPERATORS:
        if locked in expr_lower:
            return False, f"locked_operator: {locked}"

    # v6.2: Check for banned fields (invalid WQ variables the LLM keeps generating)
    for banned in BANNED_FIELDS:
        if banned in expr_lower:
            return False, f"banned_field: {banned}"

    # v6.2.1: Check for banned operators (inaccessible at base level)
    for banned in BANNED_OPERATORS:
        if banned + "(" in expr_lower:
            return False, f"banned_operator: {banned}"

    # Must contain rank() somewhere
    if "rank" not in expr_lower and "group_rank" not in expr_lower:
        return False, "no_rank"

    # Field validation: extract all potential field names and check at least one is valid
    # Extract words that could be field names (not operators, not numbers, not keywords)
    tokens = re.findall(r'[a-zA-Z_][a-zA-Z0-9_]*', expr)
    non_operator_tokens = [
        t for t in tokens
        if t not in VALID_OPERATORS
        and t not in LOCKED_OPERATORS
        and t not in {"rettype", "range", "true", "false", "True", "False"}
        and not t.startswith("ts_")
        and not t.startswith("vec_")
    ]

    if non_operator_tokens:
        # At least one non-operator token must be a valid field
        valid_count = sum(1 for t in non_operator_tokens if t in VALID_FIELDS)
        if valid_count == 0:
            bad_fields = list(set(non_operator_tokens))[:3]
            return False, f"no_valid_fields: {bad_fields}"

    return True, "ok"


def parse_expressions(raw_text: str) -> list[str]:
    """
    Parse LLM output into individual expressions.
    Handles numbered lists, bullet points, and raw lines.
    """
    valid, _ = parse_expressions_with_errors(raw_text)
    return valid


def parse_expressions_with_errors(raw_text: str) -> tuple[list[str], list[tuple[str, str]]]:
    """
    Parse LLM output, returning (valid_expressions, [(failed_expr, reason), ...]).
    Used for self-correcting retry.
    """
    if not raw_text:
        return [], []

    lines = raw_text.strip().split("\n")
    expressions = []
    failures = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # v7.2.12: Skip comment lines starting with # (used for anomaly tagging)
        # These provide context/reasoning but aren't expressions
        if line.startswith("#"):
            continue

        # Strip common prefixes: "1. ", "- ", "* ", "1) ", etc.
        line = re.sub(r"^[\d]+[\.\):\-]\s*", "", line)
        # v7.2.12: only strip * or - as bullets, NOT - (it's a leading negative sign in expressions)
        # Old regex stripped "-rank(...)" -> "rank(...)", silently flipping the alpha's sign.
        line = re.sub(r"^[*-]\s+", "", line)
        line = line.strip()

        # Strip markdown code backticks
        line = line.strip("`")
        line = line.strip()

        if not line:
            continue

        # Skip lines that look like explanations
        lower = line.lower()
        if any(w in lower for w in [
            "this ", "the ", "here ", "note:", "explanation",
            "because", "where ", "uses ", "combines ", "measures ",
            "//", "/*", "output:", "expression", "alpha",
        ]):
            continue

        valid, reason = validate_expression(line)
        if valid:
            expressions.append(line)
        else:
            failures.append((line, reason))

    return expressions, failures


#  Main generator class

class LLMAlphaGenerator:
    """
    Generates alpha expressions using LLM APIs.
    Integrated into the bot's candidate generation flow.
    """

    def __init__(self):
        self.client = LLMClient()
        self._cache: list[str] = []
        self._total_generated = 0
        self._total_valid = 0
        self._total_api_calls = 0
        self._total_failed_calls = 0
        self._recent_failures: list[dict] = []  # Track failed expressions for feedback
        self._last_api_call_time: float = 0.0  # v5.9: Rate limit cooldown
        self._session_generated_cores: list[str] = []  # v6.2: Track recently generated for dedup prompt

    @property
    def available(self) -> bool:
        return self.client.available

    def record_failure(self, expression: str, error: str):
        """Record a failed expression so the LLM can learn from it."""
        self._recent_failures.append({
            "expression": expression,
            "error": error,
        })
        # Keep only last 10 failures
        if len(self._recent_failures) > 10:
            self._recent_failures = self._recent_failures[-10:]

    def get_expression(
        self,
        *,
        submitted_exprs: list[str] | None = None,
        best_near_passers: list[dict] | None = None,
        underexplored_categories: list[str] | None = None,
        recent_eligible_count: int = 0,
    ) -> str | None:
        """
        Get a single novel expression. Uses cached buffer when available,
        refills from LLM when empty.
        """
        if self._cache:
            return self._cache.pop(0)

        self._refill_cache(
            submitted_exprs=submitted_exprs or [],
            best_near_passers=best_near_passers or [],
            underexplored_categories=underexplored_categories or [],
            recent_eligible_count=recent_eligible_count,
        )

        if self._cache:
            return self._cache.pop(0)

        return None

    def _refill_cache(
        self,
        submitted_exprs: list[str],
        best_near_passers: list[dict],
        underexplored_categories: list[str],
        recent_eligible_count: int,
    ) -> None:
        """Call LLM to generate a batch of expressions."""
        # v5.9: Rate limit cooldown - prevent Gemini 429 errors
        import config as _cfg
        cooldown = getattr(_cfg, "LLM_COOLDOWN_SECONDS", 30)
        now = time.time()
        elapsed = now - self._last_api_call_time
        if elapsed < cooldown:
            wait = cooldown - elapsed
            print(f"[LLM] Cooldown: waiting {wait:.0f}s before next API call")
            time.sleep(wait)

        self._last_api_call_time = time.time()
        self._total_api_calls += 1

        user_prompt = _build_generation_prompt(
            submitted_exprs=submitted_exprs,
            best_near_passers=best_near_passers,
            underexplored_categories=underexplored_categories,
            recent_failures=self._recent_failures,
            recent_eligible_count=recent_eligible_count,
            recently_generated=self._session_generated_cores,
            num_expressions=6,
        )

        raw = self.client.generate(SYSTEM_PROMPT, user_prompt)
        if raw is None:
            self._total_failed_calls += 1
            print("[LLM_GEN] API call failed - no expressions generated")
            return

        expressions, failures = parse_expressions_with_errors(raw)
        self._total_generated += len(expressions)
        self._total_valid += len(expressions)

        # v6.1: Self-correcting retry - feed errors back to LLM for fixing
        max_retries = getattr(_cfg, "LLM_AST_RETRY_MAX", 1)
        if failures and len(expressions) < 3 and max_retries > 0:
            retry_prompt = "These expressions had syntax errors. Fix each one and output ONLY the corrected expressions, one per line:\n\n"
            for failed_expr, reason in failures[:4]:
                retry_prompt += f"  ERROR: {reason}\n  EXPRESSION: {failed_expr}\n\n"
            retry_prompt += "Output ONLY corrected expressions - no explanation, no numbering."

            # Respect cooldown
            time.sleep(max(2, cooldown - (time.time() - self._last_api_call_time)))
            self._last_api_call_time = time.time()
            self._total_api_calls += 1

            retry_raw = self.client.generate(SYSTEM_PROMPT, retry_prompt)
            if retry_raw:
                fixed = parse_expressions(retry_raw)
                if fixed:
                    expressions.extend(fixed)
                    self._total_generated += len(fixed)
                    self._total_valid += len(fixed)
                    print(f"[LLM_AST_RETRY] Fixed {len(fixed)}/{len(failures)} failed expressions")

        if expressions:
            self._cache.extend(expressions)
            # v6.2: Track generated cores to prevent repeats in next API call
            for expr in expressions:
                core = expr.strip().lower()
                if core not in self._session_generated_cores:
                    self._session_generated_cores.append(core)
            # Keep last 30
            self._session_generated_cores = self._session_generated_cores[-30:]
            print(
                f"[LLM_GEN] Generated {len(expressions)} valid expressions "
                f"(api_calls={self._total_api_calls} total_valid={self._total_valid} "
                f"failed_calls={self._total_failed_calls})"
            )
            for i, expr in enumerate(expressions):
                print(f"  [LLM_EXPR_{i}] {expr}")
        else:
            self._total_failed_calls += 1
            print(f"[LLM_GEN] No valid expressions from LLM output. Raw: {raw[:300]}")

    def stats(self) -> dict[str, int]:
        return {
            "total_generated": self._total_generated,
            "total_valid": self._total_valid,
            "total_api_calls": self._total_api_calls,
            "total_failed_calls": self._total_failed_calls,
            "cache_size": len(self._cache),
            "tracked_failures": len(self._recent_failures),
        }
