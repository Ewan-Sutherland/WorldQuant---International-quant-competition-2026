from __future__ import annotations

TEMPLATE_LIBRARY: dict[str, list[dict[str, str]]] = {
    "mean_reversion": [
        {"template_id": "mr_01", "expression": "rank(ts_mean(close, {n}) - close)"},
        {"template_id": "mr_02", "expression": "rank(-ts_delta(close, {n}))"},
        {"template_id": "mr_03", "expression": "rank(-(close / ts_mean(close, {n}) - 1))"},
        {"template_id": "mr_04", "expression": "rank(-(returns - ts_mean(returns, {n})))"},
    ],
    "cross_sectional": [
        {"template_id": "cs_01", "expression": "-rank(ts_zscore(close, {n}))"},
        {"template_id": "cs_02", "expression": "-rank(ts_zscore(returns, {n}))"},
        {"template_id": "cs_03", "expression": "rank(ts_mean(returns, {m}) - ts_mean(returns, {n}))"},
        {"template_id": "cs_04", "expression": "group_rank(-ts_zscore(close, {n}), subindustry)"},
    ],
    "liquidity_scaled": [
        {"template_id": "liq_01", "expression": "rank(-(returns - ts_mean(returns, {n})) * rank(adv20))"},
        {"template_id": "liq_02", "expression": "rank(-ts_zscore(returns, {n}) * rank(cap))"},
        {"template_id": "liq_03", "expression": "rank((ts_mean(close, {n}) - close) * rank(adv20) / (ts_std_dev(returns, {m}) + 0.001))"},
    ],
    "conditional": [
        {"template_id": "cond_01", "expression": "trade_when(volume > ts_mean(volume, {n}), rank(-returns), -1)"},
        {"template_id": "cond_02", "expression": "trade_when(abs(returns) > ts_std_dev(returns, {n}), rank(-returns), -1)"},
        {"template_id": "cond_03", "expression": "trade_when(volume > ts_mean(volume, {n}), rank(ts_delta(close, {m})), -1)"},
    ],
    "vol_adjusted": [
        {"template_id": "va_01", "expression": "rank(ts_delta(close, {n}) / ts_std_dev(returns, {m}))"},
        {"template_id": "va_02", "expression": "rank((ts_mean(close, {n}) - close) / ts_std_dev(returns, {m}))"},
    ],
    "fundamental_value": [
        {"template_id": "fv_01", "expression": "ts_zscore({deep_field} / cap, {n})"},
        {"template_id": "fv_02", "expression": "rank(ts_delta({deep_field}, {n}) / ({deep_field} + 0.001))"},
        {"template_id": "fv_03", "expression": "-rank(close / ({deep_field} + 0.001))"},
        {"template_id": "fv_04", "expression": "group_rank(-ts_zscore({deep_field}, {n}), industry)"},
        {"template_id": "fv_05", "expression": "ts_rank({deep_field} / cap, 252)"},
        {"template_id": "fv_06", "expression": "group_rank(ts_rank({deep_field} / cap, 252), subindustry)"},
        {"template_id": "fv_07", "expression": "rank({deep_field} / enterprise_value)"},
        # v6.2.1: Multi-period - short+long agreement as a signal (structurally different)
        {"template_id": "fv_08", "expression": "rank(ts_rank({deep_field} / cap, 22)) * rank(ts_rank({deep_field} / cap, 252))"},
        {"template_id": "fv_09", "expression": "rank(ts_rank({deep_field} / cap, 60)) * rank(ts_rank({deep_field} / cap, 252))"},
    ],
    "size_value": [
        {"template_id": "sv_01", "expression": "rank(ts_zscore(eps / close, {n}))"},
        {"template_id": "sv_02", "expression": "rank(ts_delta(ebitda / enterprise_value, {n}))"},
        {"template_id": "sv_03", "expression": "-rank(ts_zscore(close / (bookvalue_ps + 0.001), {n}))"},
    ],
    "quality_trend": [
        {"template_id": "qt_01", "expression": "rank(ts_delta(cashflow_op / assets, {n}))"},
        {"template_id": "qt_02", "expression": "rank(ts_delta(current_ratio, {n}))"},
        {"template_id": "qt_03", "expression": "rank(cashflow_op / (income + 0.001))"},
        {"template_id": "qt_04", "expression": "ts_rank(cashflow_op / debt, 252)"},
        {"template_id": "qt_05", "expression": "rank(ts_delta(equity / assets, {n}))"},
        {"template_id": "qt_06", "expression": "group_rank(ts_rank(cashflow_op / debt, 252), subindustry)"},
    ],
    "fundamental_scores": [
        {"template_id": "fs_01", "expression": "rank(ts_delta({fscore_field}, {n}))"},
        {"template_id": "fs_02", "expression": "rank(ts_zscore({fscore_field}, {n}))"},
        {"template_id": "fs_03", "expression": "group_rank(-ts_zscore({fscore_field}, {n}), industry)"},
        {"template_id": "fs_04", "expression": "rank(ts_zscore({fscore_field}, {n})) * rank(cap)"},
        {"template_id": "fs_05", "expression": "rank(ts_zscore({fscore_field}, {n})) * rank(adv20)"},
        {"template_id": "fs_06", "expression": "rank(ts_zscore({fscore_field}, {n}) * rank(cap))"},
        {"template_id": "fs_07", "expression": "rank({derivative_field}) * rank(adv20)"},
        {"template_id": "fs_08", "expression": "ts_decay_linear(rank({derivative_field}) * rank(cap), {n})"},
    ],
    "earnings_momentum": [
        {"template_id": "em_01", "expression": "rank(snt1_d1_netearningsrevision)"},
        {"template_id": "em_02", "expression": "rank(ts_delta(snt1_d1_earningsrevision, {n}))"},
        {"template_id": "em_03", "expression": "rank(snt1_d1_dynamicfocusrank)"},
        {"template_id": "em_04", "expression": "ts_decay_linear(rank(snt1_d1_buyrecpercent), {n})"},
        {"template_id": "em_05", "expression": "rank(snt1_d1_stockrank)"},
        {"template_id": "em_06", "expression": "rank(ts_zscore(snt1_d1_netearningsrevision, {n}))"},
        {"template_id": "em_07", "expression": "group_rank(snt1_d1_earningsrevision, subindustry)"},
        {"template_id": "em_08", "expression": "rank(ts_decay_linear(snt1_d1_earningsrevision, 60))"},
        {"template_id": "em_09", "expression": "rank(ts_decay_linear(snt1_d1_earningsrevision, 60)) + rank(ts_decay_linear(snt1_d1_netearningsrevision, 40))"},
    ],
    "options_vol": [
        {"template_id": "opt_01", "expression": "rank(ts_backfill(implied_volatility_call_{opt_window}, 60) - ts_backfill(implied_volatility_put_{opt_window}, 60))"},
        {"template_id": "opt_02", "expression": "rank(ts_backfill(implied_volatility_call_{opt_window}, 60) / (ts_backfill(historical_volatility_{opt_window}, 60) + 0.001))"},
        {"template_id": "opt_03", "expression": "rank((ts_backfill(implied_volatility_call_{opt_window}, 60) - ts_backfill(implied_volatility_put_{opt_window}, 60)) * rank(adv20))"},
        {"template_id": "opt_04", "expression": "rank((ts_backfill(implied_volatility_call_{opt_window}, 60) / (ts_backfill(historical_volatility_{opt_window}, 60) + 0.001)) * rank(adv20))"},
        {"template_id": "opt_05", "expression": "trade_when(ts_arg_max(ts_backfill(pcr_vol_{pcr_window}, 60), 7) < 1, rank(-returns), -1)"},
        {"template_id": "opt_06", "expression": "ts_decay_linear(ts_delta(ts_backfill(implied_volatility_call_{opt_window}, 60), 25) > 0, 20)"},
        {"template_id": "opt_07", "expression": "rank(-ts_backfill(pcr_oi_{pcr_window}, 60)) * rank(adv20)"},
        {"template_id": "opt_08", "expression": "rank(ts_backfill(implied_volatility_mean_skew_{opt_window}, 60)) * rank(cap)"},
        {"template_id": "opt_09", "expression": "trade_when(ts_backfill(pcr_oi_270, 60) < 1, ts_backfill(implied_volatility_call_270, 60) - ts_backfill(implied_volatility_put_270, 60), -1)"},
        # v6.2.1: PROVEN PORTFOLIO-ADDITIVE - IV/realized ratio (all 4 overnight winners used this)
        {"template_id": "opt_10", "expression": "rank(ts_backfill(implied_volatility_call_120, 60) / (ts_backfill(parkinson_volatility_120, 60) + 0.001))"},
        {"template_id": "opt_11", "expression": "group_rank(ts_backfill(implied_volatility_call_120, 60) / (ts_backfill(parkinson_volatility_120, 60) + 0.001), industry)"},
        # v6.2.1: IV/realized x fundamentals cross-category (the +48 winning pattern)
        {"template_id": "opt_12", "expression": "rank(ts_backfill(implied_volatility_call_120, 60) / (ts_backfill(parkinson_volatility_120, 60) + 0.001) * snt1_d1_netearningsrevision)"},
        {"template_id": "opt_13", "expression": "rank(ts_backfill(implied_volatility_call_120, 60) / (ts_backfill(parkinson_volatility_120, 60) + 0.001) * ebitda / (enterprise_value + 0.001))"},
        # v6.2.1: Options term structure (long vs short IV spread)
        {"template_id": "opt_14", "expression": "rank(ts_backfill(implied_volatility_call_120, 60) - ts_backfill(implied_volatility_call_30, 60))"},
        {"template_id": "opt_15", "expression": "rank((ts_backfill(implied_volatility_call_120, 60) - ts_backfill(implied_volatility_call_30, 60)) * rank(adv20))"},
        # v6.2.1: PCR mean reversion (high PCR -> oversold -> buy)
        {"template_id": "opt_16", "expression": "rank(ts_zscore(ts_backfill(pcr_oi_60, 60), 20))"},
    ],
    "news_sentiment": [
        {"template_id": "ns_01", "expression": "rank(ts_backfill(scl12_sentiment, 60))"},
        {"template_id": "ns_02", "expression": "rank(ts_delta(ts_backfill(scl12_buzz, 60), {n}))"},
        {"template_id": "ns_03", "expression": "rank(ts_backfill(rp_ess_earnings, 60))"},
        {"template_id": "ns_04", "expression": "ts_decay_linear(rank(ts_backfill(news_pct_1min, 60)), {n})"},
        {"template_id": "ns_05", "expression": "rank(ts_backfill(snt_buzz_bfl, 60)) * rank(adv20)"},
        {"template_id": "ns_06", "expression": "rank(ts_backfill(rp_css_earnings, 60) - ts_backfill(rp_css_credit, 60))"},
        {"template_id": "ns_07", "expression": "-ts_std_dev(ts_backfill(scl12_buzz, 60), {n})"},
        {"template_id": "ns_08", "expression": "-rank(ts_backfill(scl12_buzz, 60) / (ts_mean(ts_backfill(scl12_buzz, 60), {n}) + 0.001))"},
        # v6.2.1: News x reversion combos (cross-category, likely uncorrelated with portfolio)
        {"template_id": "ns_09", "expression": "rank(-ts_backfill(news_max_up_ret, 60) * ts_mean(-returns, {n}))"},
        {"template_id": "ns_10", "expression": "rank(ts_backfill(rp_ess_earnings, 60) * -ts_mean(returns, {n}))"},
        {"template_id": "ns_11", "expression": "rank(ts_backfill(scl12_sentiment, 60) * rank(adv20) * -returns)"},
        # v6.2.1: News momentum (buzz acceleration)
        {"template_id": "ns_12", "expression": "rank(ts_delta(ts_backfill(scl12_buzz, 60), 5) * ts_backfill(scl12_sentiment, 60))"},
    ],
    "vol_regime": [
        {"template_id": "vr_01", "expression": "trade_when(ts_rank(ts_std_dev(returns, 22), 252) > 0.55, -ts_regression(returns, ts_delay(returns, 1), 252, rettype=2), -1)"},
        {"template_id": "vr_02", "expression": "trade_when(ts_rank(ts_std_dev(returns, {n}), 252) > 0.5, rank(-returns), -1)"},
        {"template_id": "vr_03", "expression": "rank(-ts_regression(returns, ts_delay(returns, 1), {n}, rettype=2))"},
        {"template_id": "vr_04", "expression": "rank(ts_regression(close, ts_step(1), {n}, rettype=2))"},
    ],
    "combo_factor": [
        {"template_id": "cf_01", "expression": "-rank(close / {deep_field}) + -rank(ts_mean(returns, {n}))"},
        {"template_id": "cf_02", "expression": "-rank(ts_zscore({deep_field}, {n})) + -rank(ts_mean((close - vwap) / vwap, {m}))"},
        {"template_id": "cf_03", "expression": "rank({deep_field} / assets) + -rank(ts_mean((close - vwap) / vwap, {n}))"},
        {"template_id": "cf_04", "expression": "rank({deep_field} / cap) + -rank(ts_mean(returns, {n}))"},
        {"template_id": "cf_05", "expression": "rank({deep_field} / cap) + rank(trade_when(ts_rank(ts_std_dev(returns, 22), 252) > 0.5, rank(-returns), -1))"},
        {"template_id": "cf_06", "expression": "rank(snt1_d1_netearningsrevision) + -rank(ts_mean(returns, {n}))"},
        {"template_id": "cf_07", "expression": "rank(snt1_d1_dynamicfocusrank) + -rank(ts_mean((close - vwap) / vwap, {n}))"},
        {"template_id": "cf_08", "expression": "rank(ts_backfill(implied_volatility_call_{opt_window}, 60) / (ts_backfill(historical_volatility_{opt_window}, 60) + 0.001)) + -rank(ts_mean(returns, {n}))"},
        {"template_id": "cf_09", "expression": "rank(ts_zscore({fscore_field}, {n})) * rank(adv20) + -rank(ts_mean(returns, {m}))"},
        {"template_id": "cf_10", "expression": "rank(ts_backfill(scl12_sentiment, 60)) + rank({deep_field} / cap)"},
        # v6.1: RAW MULTIPLICATIVE combo factors - rank(A * B) form
        {"template_id": "cf_11", "expression": "rank(({deep_field} / cap) * (-ts_mean(returns, {n})))"},
        {"template_id": "cf_12", "expression": "rank(ts_zscore({deep_field}, {n}) * (-(close - vwap) / vwap))"},
        {"template_id": "cf_13", "expression": "rank(({deep_field} / cap) * (-ts_mean((close - vwap) / vwap, {m})))"},
        # v6.1: GROUP_RANK of fundamental x reversion product
        {"template_id": "cf_14", "expression": "group_rank(({deep_field} / cap) * (-ts_mean(returns, {n})), industry)"},
        {"template_id": "cf_15", "expression": "group_rank(ts_zscore({deep_field}, {n}) * (-ts_mean(returns, {m})), subindustry)"},
    ],

    # v5.9 NEW FAMILIES
    "model77_anomaly": [
        {"template_id": "m77_01", "expression": "rank({model77_field})"},
        {"template_id": "m77_02", "expression": "-rank({model77_field})"},
        {"template_id": "m77_03", "expression": "rank(ts_zscore({model77_field}, {n}))"},
        {"template_id": "m77_04", "expression": "rank(ts_delta({model77_field}, {n}))"},
        {"template_id": "m77_05", "expression": "ts_decay_linear(rank({model77_field}), {n})"},
        {"template_id": "m77_06", "expression": "group_rank({model77_field}, industry)"},
        {"template_id": "m77_07", "expression": "group_rank({model77_field}, subindustry)"},
        {"template_id": "m77_08", "expression": "rank({model77_field}) * rank(adv20)"},
        {"template_id": "m77_09", "expression": "rank({model77_field}) * rank(cap)"},
    ],
    "model77_combo": [
        # Additive (original)
        {"template_id": "m7c_01", "expression": "rank({model77_field}) + -rank(ts_mean(returns, {m}))"},
        {"template_id": "m7c_02", "expression": "-rank({model77_field}) + -rank(ts_mean(returns, {m}))"},
        {"template_id": "m7c_03", "expression": "rank({model77_field}) + rank(trade_when(ts_rank(ts_std_dev(returns, 22), 252) > 0.5, rank(-returns), -1))"},
        {"template_id": "m7c_04", "expression": "group_rank({model77_field}, industry) + -rank(ts_mean((close - vwap) / vwap, {m}))"},
        # v5.9.1: MULTIPLICATIVE combos (research: outperform additive)
        {"template_id": "m7c_05", "expression": "rank({model77_field}) * rank(-ts_mean(returns, {m}))"},
        {"template_id": "m7c_06", "expression": "rank({model77_field}) * rank(trade_when(ts_rank(ts_std_dev(returns, 22), 252) > 0.5, rank(-returns), -1))"},
        {"template_id": "m7c_07", "expression": "rank(group_zscore({model77_field}, industry) * group_zscore(-returns, industry))"},
        {"template_id": "m7c_08", "expression": "rank(group_zscore({model77_field}, subindustry) * group_zscore(-ts_mean(returns, {m}), subindustry))"},
        # v5.9.1: Q-theory composite (Hou, Xue & Zhang - strongest academic signal)
        {"template_id": "m7c_09", "expression": "rank((revenue - cogs) / (assets + 0.001)) - rank(asset_growth_rate)"},
        {"template_id": "m7c_10", "expression": "rank((revenue - cogs) / (assets + 0.001)) - rank(asset_growth_rate) + rank(-ts_mean(returns, {m}))"},
        {"template_id": "m7c_11", "expression": "group_rank((revenue - cogs) / (assets + 0.001), subindustry) - group_rank(asset_growth_rate, subindustry)"},
        # v5.9.1: Earnings quality x value (multiplicative model77 x model77)
        {"template_id": "m7c_12", "expression": "rank(ts_std_dev(eps, 252) * ebitda / (enterprise_value + 0.001))"},
        {"template_id": "m7c_13", "expression": "rank(ts_std_dev(eps, 252) * ebitda / (enterprise_value + 0.001)) * rank(-ts_mean(returns, {m}))"},
        # v5.9.1: 3-signal composites (weak signals -> strong combined)
        {"template_id": "m7c_14", "expression": "rank({model77_field}) + rank((revenue - cogs) / (assets + 0.001)) + rank(-ts_mean(returns, {m}))"},
        {"template_id": "m7c_15", "expression": "rank({model77_field}) + rank(-asset_growth_rate) + rank(-ts_mean(returns, {m}))"},
        # v6.1: RAW MULTIPLICATIVE - rank(A * B) form (research: outperforms rank(A) + rank(B) and rank(A) * rank(B))
        {"template_id": "m7c_16", "expression": "rank({model77_field} * (-ts_mean(returns, {m})))"},
        {"template_id": "m7c_17", "expression": "rank({model77_field} * (-(close - vwap) / vwap))"},
        {"template_id": "m7c_18", "expression": "rank({model77_field} * (-ts_mean((close - vwap) / vwap, {m})))"},
        {"template_id": "m7c_19", "expression": "rank({model77_field} * ts_backfill(implied_volatility_mean_skew_30, 60))"},
        {"template_id": "m7c_20", "expression": "rank({model77_field} * snt1_d1_netearningsrevision)"},
        # v6.1: 3-signal with multiplicative pair + additive third
        {"template_id": "m7c_21", "expression": "rank({model77_field} * (revenue - cogs) / (assets + 0.001)) + rank(-ts_mean(returns, {m}))"},
        {"template_id": "m7c_22", "expression": "rank({model77_field} * (-asset_growth_rate)) + rank(-ts_mean(returns, {m}))"},
        # v6.1: GROUP_RANK of product - research: outperforms rank() for fundamentals 78% of the time
        {"template_id": "m7c_23", "expression": "group_rank({model77_field} * (-ts_mean(returns, {m})), industry)"},
        {"template_id": "m7c_24", "expression": "group_rank({model77_field} * (-ts_mean((close - vwap) / vwap, {m})), subindustry)"},
        # v6.1: TS_RANK temporal ranking x reversion - best for quarterly fundamental data
        {"template_id": "m7c_25", "expression": "rank(ts_rank({model77_field}, 252) * (-ts_mean(returns, {m})))"},
        {"template_id": "m7c_26", "expression": "group_rank(ts_rank({model77_field}, 252) * (-ts_mean(returns, {m})), industry)"},
    ],
    "relationship": [
        {"template_id": "rel_01", "expression": "rank(rel_ret_cust)"},
        {"template_id": "rel_02", "expression": "-rank(rel_ret_comp)"},
        {"template_id": "rel_03", "expression": "rank(ts_delta(rel_ret_cust, {n}))"},
        {"template_id": "rel_04", "expression": "rank(ts_zscore(rel_ret_cust, {n}))"},
        {"template_id": "rel_05", "expression": "rank(rel_ret_cust) * rank(rel_num_cust)"},
        {"template_id": "rel_06", "expression": "group_rank(pv13_ustomergraphrank_page_rank, sector) * rank(adv20)"},
        {"template_id": "rel_07", "expression": "rank(rel_ret_cust) + -rank(ts_mean(returns, {m}))"},
        {"template_id": "rel_08", "expression": "-rank(rel_ret_comp) + -rank(ts_mean(returns, {m}))"},
        # v5.9.1: Decayed customer momentum (Cohen & Frazzini 2008 - 150bp monthly)
        {"template_id": "rel_09", "expression": "ts_decay_linear(ts_mean(rel_ret_cust, 5), 10)"},
        {"template_id": "rel_10", "expression": "ts_decay_linear(rank(rel_ret_cust) - rank(rel_ret_comp), 10)"},
        # v5.9.1: Multiplicative customer momentum x profitability
        {"template_id": "rel_11", "expression": "rank(ts_decay_linear(rel_ret_cust, 10) * group_zscore(operating_income / (sales + 0.001), sector))"},
    ],
    "risk_beta": [
        {"template_id": "rb_01", "expression": "-rank(beta_last_60_days_spy)"},
        {"template_id": "rb_02", "expression": "-rank(beta_last_360_days_spy)"},
        {"template_id": "rb_03", "expression": "rank(unsystematic_risk_last_60_days)"},
        {"template_id": "rb_04", "expression": "-rank(ts_zscore(beta_last_60_days_spy, {n}))"},
        {"template_id": "rb_05", "expression": "-rank(correlation_last_60_days_spy) * rank(adv20)"},
        {"template_id": "rb_06", "expression": "-rank(beta_last_60_days_spy) + rank({deep_field} / cap)"},
        {"template_id": "rb_07", "expression": "-rank(beta_last_60_days_spy) + -rank(ts_mean(returns, {m}))"},
        # v6.2.1: Cross-category beta x fundamentals (beta is genuinely different data)
        {"template_id": "rb_08", "expression": "rank(-beta_last_60_days_spy * ebitda / (enterprise_value + 0.001))"},
        {"template_id": "rb_09", "expression": "rank(-beta_last_60_days_spy) + rank(est_eps / close)"},
        {"template_id": "rb_10", "expression": "rank(unsystematic_risk_last_60_days * (revenue - cogs) / (assets + 0.001))"},
        {"template_id": "rb_11", "expression": "rank(-beta_last_60_days_spy * ts_backfill(implied_volatility_call_120, 60))"},
    ],
    "expanded_fundamental": [
        {"template_id": "ef_01", "expression": "rank(cashflow_op / assets) - rank(income / assets)"},
        {"template_id": "ef_02", "expression": "-group_rank(ts_delta(assets, 252) / (ts_delay(assets, 252) + 0.001), subindustry)"},
        {"template_id": "ef_03", "expression": "-rank(ts_delta(sharesout, 252) / (ts_delay(sharesout, 252) + 0.001))"},
        {"template_id": "ef_04", "expression": "rank((sales - cogs) / assets)"},
        {"template_id": "ef_05", "expression": "group_rank((sales - cogs) / assets, subindustry)"},
        {"template_id": "ef_06", "expression": "-ts_rank(retained_earnings, 500)"},
        {"template_id": "ef_07", "expression": "rank(rd_expense / cap)"},
        {"template_id": "ef_08", "expression": "rank(ts_delta(working_capital / assets, {n}))"},
        {"template_id": "ef_09", "expression": "rank(ts_delta(inventory_turnover, {n}))"},
        {"template_id": "ef_10", "expression": "group_rank((sales - ebitda) / assets, subindustry)"},
        {"template_id": "ef_11", "expression": "-ts_zscore(enterprise_value / (ebitda + 0.001), 63)"},
        {"template_id": "ef_12", "expression": "-rank(ebit / (capex + 0.001))"},
        {"template_id": "ef_13", "expression": "rank(cashflow_op / enterprise_value)"},
        {"template_id": "ef_14", "expression": "rank(sales / assets) + rank(bookvalue_ps / close)"},
        # v5.9.1: R&D intensity (Lev & Sougiannis - 1.52% monthly FF5 alpha)
        {"template_id": "ef_15", "expression": "group_rank(rd_expense / (sales + 0.001), industry)"},
        {"template_id": "ef_16", "expression": "rank(rd_expense / (sales + 0.001)) * rank(1 / (tobins_q_ratio + 0.001))"},
        # v5.9.1: Piotroski-style 3-factor quality composite
        {"template_id": "ef_17", "expression": "rank(group_zscore(cashflow_op / assets, subindustry) + group_zscore(operating_income / (sales + 0.001), subindustry) - group_zscore(debt / assets, subindustry))"},
        # v5.9.1: Altman Z-Score composite
        {"template_id": "ef_18", "expression": "rank(1.2 * working_capital / (assets + 0.001) + 1.4 * retained_earnings / (assets + 0.001) + 3.3 * ebit / (assets + 0.001))"},
        # v6.2.1: Proven academic anomalies (from previous research session)
        # Accrual anomaly (Sloan 1996) - cash flow vs earnings gap
        {"template_id": "ef_19", "expression": "rank(cashflow_op / assets) - rank(income / assets)"},
        {"template_id": "ef_20", "expression": "-rank(ts_delta(assets_curr - liabilities_curr + debt_st, 252) / (ts_delay(assets, 252) + 0.001))"},
        # Retained earnings reversion - proven S=1.55 in previous chat
        {"template_id": "ef_21", "expression": "-ts_rank(retained_earnings, 500)"},
        # Investment anomaly (Titman, Wei & Xie) - overinvestors underperform
        {"template_id": "ef_22", "expression": "-rank(ts_delta(assets, 252) / (ts_delay(assets, 252) + 0.001))"},
    ],
    "analyst_estimates": [
        {"template_id": "ae_01", "expression": "group_rank(ts_rank(est_eps / close, 60), industry)"},
        {"template_id": "ae_02", "expression": "ts_decay_linear(ts_scale(est_cashflow_op, 252), 22) - ts_decay_linear(ts_scale(est_capex, 252), 22)"},
        {"template_id": "ae_03", "expression": "-ts_corr(est_ptp, est_fcf, 252)"},
        {"template_id": "ae_04", "expression": "rank(ts_zscore(est_fcf / cap, {n}))"},
        {"template_id": "ae_05", "expression": "rank(est_eps / close) + rank(snt1_d1_netearningsrevision)"},
    ],
    "wq_proven": [
        {"template_id": "wp_01", "expression": "group_rank(-ts_zscore(enterprise_value / cashflow, 63), industry)"},
        {"template_id": "wp_02", "expression": "ts_backfill(implied_volatility_call_120, 60) / (ts_backfill(parkinson_volatility_120, 60) + 0.001)"},
        {"template_id": "wp_03", "expression": "ts_regression(ts_sum(ts_backfill(operating_income, 60), 252), ts_step(1), 756, rettype=2)"},
        {"template_id": "wp_04", "expression": "winsorize(-ts_backfill(news_max_up_ret, 60) * abs(ts_regression(ts_backfill(news_pct_1min, 60), ts_step(1), 5, rettype=2)), std=4)"},
        {"template_id": "wp_05", "expression": "ts_rank(operating_income / cap, 252)"},
        {"template_id": "wp_06", "expression": "-ts_rank(fn_liab_fair_val_l1_a, 252)"},
    ],
    "momentum": [
        {"template_id": "mom_01", "expression": "rank(ts_delta(close, {n}))"},
        {"template_id": "mom_02", "expression": "rank(ts_rank(close, {n}))"},
        {"template_id": "mom_03", "expression": "rank(ts_mean(returns, {n}))"},
    ],
    "volume_flow": [
        {"template_id": "vol_01", "expression": "rank(volume / ts_mean(volume, {n}))"},
        {"template_id": "vol_02", "expression": "rank(ts_delta(volume, {n}) * returns)"},
        {"template_id": "vol_03", "expression": "rank((volume / ts_mean(volume, {n})) * -returns)"},
    ],
    "price_vol_corr": [
        {"template_id": "pvc_01", "expression": "-rank(ts_corr(rank(close), rank(volume), {n}))"},
        {"template_id": "pvc_02", "expression": "rank(ts_corr(ts_delta(close, {m}), volume, {n}))"},
        {"template_id": "pvc_03", "expression": "-rank(ts_corr(vwap, volume, {n}))"},
        {"template_id": "pvc_04", "expression": "-rank((close - vwap) / (vwap + 0.001) * log(volume + 1))"},
    ],
    "volatility": [
        {"template_id": "vlty_01", "expression": "rank(1 / (ts_std_dev(returns, {n}) + 0.001))"},
        {"template_id": "vlty_04", "expression": "rank(ts_mean(returns, {m}) / (ts_std_dev(returns, {n}) + 0.001))"},
    ],
    "intraday": [
        {"template_id": "iday_01", "expression": "rank(-(high - low) / (close + 0.001))"},
        {"template_id": "iday_02", "expression": "rank((close - low) / (high - low + 0.001))"},
        {"template_id": "iday_03", "expression": "-rank(ts_mean(high - low, {n}) / (close + 0.001))"},
        {"template_id": "iday_04", "expression": "rank(open / close - 1)"},
        {"template_id": "iday_05", "expression": "-rank(ts_mean(open / close - 1, {n}))"},
        # v6.2.1: Intraday cross-category (genuinely different data from price returns)
        {"template_id": "iday_06", "expression": "rank((close - open) / (high - low + 0.001) * snt1_d1_earningsrevision)"},
        {"template_id": "iday_07", "expression": "rank(ts_zscore((high - low) / (close + 0.001), {n})) * rank(adv20)"},
        {"template_id": "iday_08", "expression": "group_rank((close - low) / (high - low + 0.001), industry)"},
    ],
    "fundamental": [
        {"template_id": "fund_01", "expression": "rank({field})"},
        {"template_id": "fund_02", "expression": "rank(ts_delta({field}, {n}))"},
        {"template_id": "fund_03", "expression": "rank(({field} - ts_mean({field}, {n})))"},
    ],
    "analyst_sentiment": [
        {"template_id": "ans_01", "expression": "rank(ts_delta({analyst_field}, {n}))"},
        {"template_id": "ans_02", "expression": "-rank({sentiment_field} / (ts_mean({sentiment_field}, {n}) + 0.001))"},
        {"template_id": "ans_03", "expression": "rank(ts_zscore({analyst_field}, {n}))"},
        # v6.2.1: Sentiment x reversion combos (cross-category, proven in +46 resim winner)
        {"template_id": "ans_04", "expression": "rank(ts_backfill(snt1_d1_netearningsrevision, 60) * -ts_mean(returns, {n}))"},
        {"template_id": "ans_05", "expression": "rank(ts_backfill(snt1_d1_earningsrevision, 60) * ebitda / (enterprise_value + 0.001))"},
        {"template_id": "ans_06", "expression": "rank(ts_backfill(snt1_d1_buyrecpercent, 60) * -ts_mean((close - vwap) / vwap, {n}))"},
    ],

    # v6.2.1: UNTAPPED DATA CATEGORIES - virtually zero portfolio correlation

    # Vector datasets - multiple values per stock per day, use vec_* operators
    # Most competitors skip these entirely. Proven: S=1.94 buzz alpha.
    "vector_data": [
        # Social buzz vectors - proven pattern: aggregate then smooth
        {"template_id": "vec_01", "expression": "ts_av_diff(ts_backfill(-vec_sum(scl12_alltype_buzzvec), 20), 60)"},
        {"template_id": "vec_02", "expression": "rank(ts_backfill(vec_avg(scl12_alltype_sentvec), 20))"},
        # News vectors - after-hours significance
        {"template_id": "vec_04", "expression": "rank(ts_backfill(vec_sum(nws12_afterhsz_sl), 20))"},
        {"template_id": "vec_05", "expression": "rank(ts_backfill(vec_avg(nws12_afterhsz_sl), 20) * -ts_mean(returns, {n}))"},
        # Buzz x sentiment interaction
        {"template_id": "vec_06", "expression": "rank(ts_backfill(vec_sum(scl12_alltype_buzzvec), 20) * ts_backfill(vec_avg(scl12_alltype_sentvec), 20))"},
        # Buzz IR (information ratio - signal-to-noise of social media)
        # v6.2.1: News-conditional regime switching - proven S=1.84
        {"template_id": "vec_11", "expression": "trade_when(rank(ts_sum(ts_backfill(vec_avg(nws12_afterhsz_sl), 20), 60)) > 0.5, rank(-ts_delta(close, 2)), -1)"},
    ],

    # v6.2.1: 10 NEW FAMILIES - completely untapped data categories

    # SUPPLY CHAIN - 165 pv13_* fields, 0 submitted alphas, fewest users on platform
    "supply_chain": [
        {"template_id": "sc_01", "expression": "rank(ts_mean(rel_ret_cust, {n}))"},
        {"template_id": "sc_02", "expression": "rank(ts_mean(rel_ret_comp, {n})) * rank(-returns)"},
        {"template_id": "sc_03", "expression": "group_rank(pv13_com_page_rank, sector) * rank(ts_rank(operating_income / cap, 252))"},
        {"template_id": "sc_04", "expression": "trade_when(ts_rank(ts_std_dev(returns, 22), 252) > 0.5, rank(ts_mean(rel_ret_cust, {n})), -1)"},
        {"template_id": "sc_05", "expression": "rank(ts_mean(rel_ret_cust, {n}) - ts_mean(rel_ret_comp, {n}))"},
        {"template_id": "sc_06", "expression": "group_rank(pv13_com_page_rank, sector) * rank(ebitda / (enterprise_value + 0.001))"},
        {"template_id": "sc_07", "expression": "rank(ts_delta(rel_num_cust, {n}))"},
        {"template_id": "sc_08", "expression": "group_rank(pv13_custretsig_retsig, sector) * group_rank(ts_rank(est_eps / close, 60), industry)"},
    ],

    # RAVENPACK CATEGORY SENTIMENT - 75 fields, 0 submitted alphas
    "ravenpack_cat": [
        {"template_id": "rp_01", "expression": "rank(ts_backfill(rp_ess_mna, 60))"},
        {"template_id": "rp_02", "expression": "rank(ts_backfill(rp_ess_earnings, 60)) * rank(-ts_mean(returns, {n}))"},
        {"template_id": "rp_03", "expression": "-rank(ts_av_diff(ts_backfill(rp_css_credit, 60), 30))"},
        {"template_id": "rp_04", "expression": "rank(ts_backfill(rp_ess_insider, 60)) * rank(-(close - vwap) / vwap)"},
        {"template_id": "rp_05", "expression": "rank(ts_backfill(rp_ess_revenue, 60)) * rank(snt1_d1_netearningsrevision)"},
        {"template_id": "rp_06", "expression": "-rank(ts_backfill(rp_css_legal, 60))"},
        {"template_id": "rp_07", "expression": "rank(ts_delta(ts_backfill(rp_ess_product, 60), 10))"},
        {"template_id": "rp_08", "expression": "rank(ts_backfill(rp_nip_earnings, 60) * ts_backfill(rp_ess_earnings, 60))"},
        {"template_id": "rp_09", "expression": "rank(ts_backfill(rp_ess_earnings, 60)) * rank(ts_backfill(rp_css_earnings, 60))"},
    ],

    # OPTIONS ANALYTICS - breakeven & forward price, 74 fields, 0 submitted
    "options_analytics": [
        {"template_id": "oa_01", "expression": "rank(ts_backfill(call_breakeven_30, 60) / close - 1)"},
        {"template_id": "oa_02", "expression": "rank(ts_backfill(call_breakeven_120, 60) - ts_backfill(call_breakeven_30, 60))"},
        {"template_id": "oa_03", "expression": "rank(ts_delta(ts_backfill(forward_price_60, 60), 10) / close)"},
        {"template_id": "oa_04", "expression": "rank(1 - ts_backfill(put_breakeven_30, 60) / close)"},
        {"template_id": "oa_05", "expression": "rank((ts_backfill(call_breakeven_60, 60) - close) / (close - ts_backfill(put_breakeven_60, 60) + 0.001))"},
        {"template_id": "oa_06", "expression": "rank(ts_delta(ts_backfill(option_breakeven_60, 60), {n})) * rank(volume / adv20)"},
    ],

    # HISTORICAL VOLATILITY - vol risk premium, 8 fields, 0 submitted
    "hist_vol": [
        {"template_id": "hv_01", "expression": "rank(ts_backfill(implied_volatility_call_60, 60) / (historical_volatility_60 + 0.001))"},
        {"template_id": "hv_02", "expression": "trade_when(historical_volatility_20 > ts_mean(historical_volatility_20, 60), rank(-returns), -1)"},
        {"template_id": "hv_03", "expression": "rank(historical_volatility_20 / (historical_volatility_90 + 0.001))"},
        {"template_id": "hv_04", "expression": "rank(ts_delta(ts_backfill(implied_volatility_mean_skew_60, 60), 10))"},
        {"template_id": "hv_05", "expression": "-rank(ts_backfill(implied_volatility_mean_60, 60))"},
    ],

    # FUNDAMENTAL SCORES (fscore_*) - 24 fields, 0 submitted
    "fscore": [
        {"template_id": "fs_01", "expression": "rank(ts_backfill(fscore_bfl_quality, 60)) * rank(ts_backfill(fscore_bfl_momentum, 60))"},
        {"template_id": "fs_02", "expression": "rank(ts_backfill(fscore_bfl_surface_accel, 60)) * rank(cap)"},
        {"template_id": "fs_03", "expression": "rank(ts_backfill(fscore_bfl_total, 60) * rank(cap))"},
        {"template_id": "fs_04", "expression": "rank(ts_backfill(fscore_bfl_value, 60)) * rank(ts_backfill(fscore_bfl_profitability, 60))"},
        {"template_id": "fs_05", "expression": "rank(ts_backfill(growth_potential_rank_derivative, 60))"},
        {"template_id": "fs_06", "expression": "rank(ts_delta(ts_backfill(composite_factor_score_derivative, 60), 20))"},
    ],

    # RISK METRICS - beta, correlation, systematic risk, 16 fields, 0 submitted
    "risk_metrics": [
        {"template_id": "rm_01", "expression": "-rank(beta_last_60_days_spy)"},
        {"template_id": "rm_02", "expression": "rank(unsystematic_risk_last_60_days / (systematic_risk_last_60_days + 0.001))"},
        {"template_id": "rm_03", "expression": "rank(beta_last_30_days_spy - beta_last_60_days_spy)"},
        {"template_id": "rm_04", "expression": "-rank(ts_delta(correlation_last_60_days_spy, 20))"},
        {"template_id": "rm_05", "expression": "-rank(beta_last_60_days_spy) * rank(ebitda / (enterprise_value + 0.001))"},
        {"template_id": "rm_06", "expression": "trade_when(systematic_risk_last_30_days > systematic_risk_last_60_days, rank(-returns), -1)"},
    ],

    # INTRADAY PATTERNS - open/high/low/close relationships, 0 submitted
    "intraday_pattern": [
        {"template_id": "id_01", "expression": "rank(-(open - ts_delay(close, 1)) / (ts_delay(close, 1) + 0.001))"},
        {"template_id": "id_02", "expression": "rank((close - open) / (high - low + 0.001))"},
        {"template_id": "id_03", "expression": "-rank((high - max(open, close)) / (high - low + 0.001))"},
        {"template_id": "id_04", "expression": "rank(-ts_mean(high - low, {n}) / (ts_mean(high - low, 60) + 0.001))"},
        {"template_id": "id_05", "expression": "rank(ts_mean((high - low) / (volume + 0.001), {n}))"},
    ],

    # DEEP ANALYST SENTIMENT - snt1_d1_* deep fields, mostly untapped
    "analyst_deep": [
        {"template_id": "as_01", "expression": "-rank(snt1_d1_earningsrevision)"},
        {"template_id": "as_02", "expression": "rank(snt1_d1_buyrecpercent - snt1_d1_sellrecpercent)"},
        {"template_id": "as_03", "expression": "rank(snt1_d1_uptargetpercent - snt1_d1_downtargetpercent)"},
        {"template_id": "as_04", "expression": "rank(snt1_d1_analystcoverage) * rank(snt1_d1_earningsrevision)"},
        {"template_id": "as_05", "expression": "rank(snt1_d1_longtermepsgrowthest) * rank(-returns)"},
        {"template_id": "as_06", "expression": "rank(snt1_d1_stockrank)"},
        {"template_id": "as_07", "expression": "rank(snt1_d1_fundamentalfocusrank - snt1_d1_dynamicfocusrank)"},
    ],

    # SOCIAL MEDIA SCALAR - non-vector buzz/sentiment, 0 submitted
    "social_scalar": [
        {"template_id": "sm_01", "expression": "-rank(scl12_buzz)"},
        {"template_id": "sm_02", "expression": "rank(scl12_buzz_fast_d1)"},
        {"template_id": "sm_03", "expression": "rank(snt_value)"},
        {"template_id": "sm_04", "expression": "rank(scl12_buzz * scl12_sentiment)"},
        {"template_id": "sm_05", "expression": "rank(snt_buzz_ret)"},
    ],

    # WILD COMBOS - cross-category novel interactions
    "wild_combos": [
        {"template_id": "wild_01", "expression": "rank(ts_mean(rel_ret_cust, 5)) * rank(ts_backfill(implied_volatility_call_60, 60) / (historical_volatility_60 + 0.001))"},
        {"template_id": "wild_02", "expression": "group_zscore(ts_backfill(rp_css_credit, 60), industry) * rank(ts_rank(cashflow_op / cap, 252))"},
        {"template_id": "wild_03", "expression": "trade_when(historical_volatility_20 > ts_mean(historical_volatility_20, 60), rank(-returns) * rank(volume / adv20), -1)"},
        {"template_id": "wild_04", "expression": "rank(ts_backfill(forward_price_60, 60) / close - 1) * rank((revenue - cogs) / (assets + 0.001))"},
        {"template_id": "wild_05", "expression": "rank(-snt1_d1_earningsrevision) * rank(ts_mean(rel_ret_comp, 5))"},
        {"template_id": "wild_06", "expression": "rank(ts_backfill(fscore_bfl_surface_accel, 60)) * rank(ts_backfill(implied_volatility_mean_skew_60, 60))"},
        {"template_id": "wild_07", "expression": "rank(correlation_last_30_days_spy - correlation_last_360_days_spy) * rank(ts_rank(operating_income / cap, 252))"},
    ],

    # v6.2.1: TUTORIAL-PROVEN - expressions directly from WorldQuant's official tutorial
    "tutorial_proven": [
        # CLV (Close Location Value) - tutorial says S > 1.4 with volume
        {"template_id": "tut_01", "expression": "-zscore(((close - low) - (high - close)) / (high - low + 0.001)) * rank(volume)"},
        # Momentum with reversion dodge - delay 10 days to skip short-term reversion
        {"template_id": "tut_02", "expression": "ts_delay(ts_delta(close, 250) / ts_delay(close, 250), 10)"},
        # Count positive return days - completely different signal structure
        {"template_id": "tut_03", "expression": "rank(ts_sum(if_else(returns > 0, 1, 0), 252))"},
        # Positive days + volume condition via trade_when
        {"template_id": "tut_04", "expression": "trade_when(volume > adv20, ts_sum(if_else(returns > 0, 1, 0), 250), -1)"},
        # Buzz vs volume regression - tutorial says "most effective method"
        {"template_id": "tut_05", "expression": "ts_regression(-scl12_buzz, volume, 250)"},
        # News conditional momentum/reversion - tutorial answer expression
        {"template_id": "tut_06", "expression": "if_else(rank(ts_sum(vec_avg(nws12_afterhsz_sl), 60)) > 0.5, 1, rank(-ts_delta(close, 2)))"},
        # Custom cap-group neutralized IV spread - tutorial advanced pattern
        {"template_id": "tut_07", "expression": "group_neutralize(ts_backfill(implied_volatility_call_120, 60) - ts_backfill(implied_volatility_put_120, 60), bucket(rank(cap), range=\"0.1,1,0.1\"))"},
        # EV/EBITDA value - tutorial basic pattern
        {"template_id": "tut_08", "expression": "-rank(enterprise_value / (ebitda + 0.001))"},
        # OEY with ts_rank - tutorial recommended approach
        {"template_id": "tut_09", "expression": "ts_rank(operating_income / cap, 250)"},
    ],

    # v6.2.1: HIGH SHARPE - research-proven S>2.0 patterns we've never templated
    "high_sharpe": [
        # -ts_zscore(EV/EBITDA) - research: S=2.58, F=1.70 on TOP3000/SUBINDUSTRY
        {"template_id": "hs_01", "expression": "-ts_zscore(enterprise_value / (ebitda + 0.001), 63)"},
        {"template_id": "hs_02", "expression": "-ts_zscore(enterprise_value / (ebitda + 0.001), {n})"},
        # -rank(ebit/capex) - research: S=2.02, F=2.30 on TOP500
        {"template_id": "hs_03", "expression": "-rank(ebit / (capex + 0.001))"},
        {"template_id": "hs_04", "expression": "-group_rank(ebit / (capex + 0.001), industry)"},
        # hump() wrapped versions - reduces turnover -> boosts fitness
        {"template_id": "hs_05", "expression": "hump(-ts_zscore(enterprise_value / (ebitda + 0.001), 63))"},
        {"template_id": "hs_06", "expression": "hump(rank(ts_rank(operating_income / cap, 252)))"},
        {"template_id": "hs_07", "expression": "hump(-rank(ebit / (capex + 0.001)))"},
        # Simple value ratios that research shows work but we never tried standalone
        {"template_id": "hs_08", "expression": "-rank(enterprise_value / (sales + 0.001))"},
        {"template_id": "hs_09", "expression": "rank(ebitda / enterprise_value)"},
        {"template_id": "hs_10", "expression": "-ts_zscore(close / (bookvalue_ps + 0.001), 63)"},
        # Gross profit to assets - Novy-Marx factor, use model77 pre-computed ratio
        {"template_id": "hs_11", "expression": "rank((revenue - cogs) / (assets + 0.001))"},
        {"template_id": "hs_12", "expression": "ts_rank((revenue - cogs) / (assets + 0.001), 252)"},
        # FCF yield - free cash flow / market cap
        {"template_id": "hs_13", "expression": "rank(cashflow_op / cap)"},
        {"template_id": "hs_14", "expression": "-ts_zscore(cap / (cashflow_op + 0.001), 63)"},
        # Custom bucket neutralization - tutorial advanced technique, nobody else does this
        {"template_id": "hs_15", "expression": "group_neutralize(-ts_zscore(enterprise_value / (ebitda + 0.001), 63), bucket(rank(cap), range=\"0.1,1,0.1\"))"},
        {"template_id": "hs_16", "expression": "group_neutralize(rank(ebitda / enterprise_value), bucket(rank(cap), range=\"0.1,1,0.1\"))"},
    ],
    # v6.2.1: Financial statement (fn_) fields - massive portfolio diversity (+175, +198 score change)
    # These raw signals fail Sharpe/Fitness alone but wrapped properly become uncorrelated submissions
    "fn_financial": [
        # Fair value liabilities - the +175 score change signal
        {"template_id": "fn_01", "expression": "rank(-ts_rank(fn_liab_fair_val_l1_a, {n}))"},
        {"template_id": "fn_02", "expression": "rank(-ts_rank(fn_liab_fair_val_l1_a, {n})) + rank(-returns)"},
        {"template_id": "fn_03", "expression": "rank(-ts_rank(fn_liab_fair_val_l1_a, {n})) * rank(adv20)"},
        {"template_id": "fn_04", "expression": "group_rank(-ts_rank(fn_liab_fair_val_l1_a, {n}), industry)"},
        {"template_id": "fn_05", "expression": "rank(-ts_rank(fn_liab_fair_val_l1_a, {n})) + rank(ts_rank(operating_income / cap, 252))"},
        # FX transaction - the +198 score change signal
        {"template_id": "fn_06", "expression": "rank(ts_mean(fn_oth_income_loss_fx_transaction_and_tax_translation_adj_a, {n}))"},
        {"template_id": "fn_07", "expression": "rank(ts_mean(fn_oth_income_loss_fx_transaction_and_tax_translation_adj_a, {n})) + rank(-returns)"},
        {"template_id": "fn_08", "expression": "rank(ts_mean(fn_oth_income_loss_fx_transaction_and_tax_translation_adj_a, {n})) * rank(adv20)"},
        {"template_id": "fn_09", "expression": "group_rank(ts_mean(fn_oth_income_loss_fx_transaction_and_tax_translation_adj_a, {n}), industry)"},
        {"template_id": "fn_10", "expression": "rank(ts_mean(fn_oth_income_loss_fx_transaction_and_tax_translation_adj_a, {n})) + rank(ts_rank(operating_income / cap, 252))"},
        # Fair value assets - opposite side of the balance sheet
        {"template_id": "fn_11", "expression": "rank(ts_rank(fn_assets_fair_val_l1_a, {n}))"},
        {"template_id": "fn_12", "expression": "rank(ts_rank(fn_assets_fair_val_l1_a, {n})) + rank(-returns)"},
        # Debt instruments
        {"template_id": "fn_13", "expression": "rank(-ts_rank(fn_debt_instrument_carrying_amount_a / (cap + 0.001), {n}))"},
        {"template_id": "fn_14", "expression": "rank(-ts_rank(fn_debt_instrument_carrying_amount_a / (cap + 0.001), {n})) + rank(-returns)"},
        # Share-based compensation (employee stock options signal)
        {"template_id": "fn_15", "expression": "rank(-ts_rank(fn_allocated_share_based_compensation_expense_a / (cap + 0.001), {n}))"},
        {"template_id": "fn_16", "expression": "rank(fn_comprehensive_income_net_of_tax_a / (cap + 0.001))"},
        # FX accumulation
        {"template_id": "fn_17", "expression": "rank(fn_accum_oth_income_loss_fx_adj_net_of_tax_a / (cap + 0.001))"},
        {"template_id": "fn_18", "expression": "rank(fn_accum_oth_income_loss_fx_adj_net_of_tax_a / (cap + 0.001)) + rank(-returns)"},
    ],
    # v6.2.1: Simple ratios - liabilities/assets gave +175 score change with 1 operator!
    # Dead-simple balance sheet ratios are massively portfolio-diverse
    "simple_ratio": [
        # Balance sheet ratios
        {"template_id": "sr_01", "expression": "liabilities / assets"},
        {"template_id": "sr_02", "expression": "rank(liabilities / assets)"},
        {"template_id": "sr_03", "expression": "rank(liabilities / assets) + rank(-returns)"},
        {"template_id": "sr_04", "expression": "rank(liabilities / assets) * rank(adv20)"},
        {"template_id": "sr_05", "expression": "group_rank(liabilities / assets, industry)"},
        {"template_id": "sr_06", "expression": "rank(debt / assets)"},
        {"template_id": "sr_07", "expression": "rank(debt / assets) + rank(-returns)"},
        {"template_id": "sr_08", "expression": "rank(equity / assets)"},
        {"template_id": "sr_09", "expression": "rank(equity / liabilities)"},
        {"template_id": "sr_10", "expression": "rank(cashflow_op / assets)"},
        {"template_id": "sr_11", "expression": "rank(cashflow_op / liabilities)"},
        {"template_id": "sr_12", "expression": "rank(operating_income / assets)"},
        {"template_id": "sr_13", "expression": "rank(ebitda / assets)"},
        {"template_id": "sr_14", "expression": "rank(sales / liabilities)"},
        {"template_id": "sr_15", "expression": "rank(income / assets)"},
        {"template_id": "sr_16", "expression": "rank(assets_curr / liabilities_curr)"},
        {"template_id": "sr_17", "expression": "rank(retained_earnings / assets)"},
        {"template_id": "sr_18", "expression": "rank(working_capital / assets)"},
        # Inverted ratios (what's cheap relative to fundamentals)
        {"template_id": "sr_19", "expression": "rank(assets / cap)"},
        {"template_id": "sr_20", "expression": "rank(equity / cap)"},
        {"template_id": "sr_21", "expression": "rank(sales / cap)"},
        {"template_id": "sr_22", "expression": "rank(ebitda / cap)"},
        # Time-series rank versions (detect regime changes)
        {"template_id": "sr_23", "expression": "rank(ts_rank(liabilities / assets, 252))"},
        {"template_id": "sr_24", "expression": "rank(ts_rank(debt / assets, 252))"},
        {"template_id": "sr_25", "expression": "rank(ts_rank(equity / assets, 252))"},
        {"template_id": "sr_26", "expression": "rank(ts_zscore(liabilities / assets, 60))"},
    ],
    # v6.2.1: Fundamental / volatility ratio signals - the +152 score change pattern
    "fundamental_vol": [
        {"template_id": "fv_02", "expression": "rank(ts_rank(operating_income / (parkinson_volatility_180 + 0.001), 252))"},
        {"template_id": "fv_03", "expression": "rank(ts_rank(operating_income / (parkinson_volatility_180 + 0.001), 252)) + rank(-returns)"},
        {"template_id": "fv_04", "expression": "group_rank(operating_income / (parkinson_volatility_180 + 0.001), industry)"},
        {"template_id": "fv_05", "expression": "rank(operating_income / (parkinson_volatility_120 + 0.001))"},
        {"template_id": "fv_06", "expression": "rank(ebitda / (parkinson_volatility_180 + 0.001))"},
        {"template_id": "fv_07", "expression": "rank(cashflow_op / (parkinson_volatility_120 + 0.001))"},
        {"template_id": "fv_08", "expression": "rank(sales / (parkinson_volatility_180 + 0.001))"},
        {"template_id": "fv_09", "expression": "rank(ts_rank(ebitda / (parkinson_volatility_180 + 0.001), 252)) + rank(-returns)"},
        {"template_id": "fv_10", "expression": "rank(operating_income / (parkinson_volatility_180 + 0.001)) * rank(adv20)"},
        # Normalized by cap for cross-sectional comparability
        {"template_id": "fv_11", "expression": "rank(ts_rank(operating_income / cap, 252) * (1 / (parkinson_volatility_180 + 0.001)))"},
        {"template_id": "fv_12", "expression": "rank(ts_rank(operating_income / cap, 252)) * rank(1 / (parkinson_volatility_180 + 0.001))"},
    ],
    #  v7.1: NEW SIGNAL DIMENSIONS - break the self-correlation wall
    # These target fields that NO existing template touches, maximising chance
    # of producing alphas uncorrelated with the existing 46 submissions.

    # nws18_* event fields - 14 completely untouched fields
    # NOTE: nws18 are EVENT inputs - ts_backfill and ts_sum both fail on events.
    # Use raw field access (platform auto-aggregates events) or vec operators.
    "news_event_signal": [
        {"template_id": "ne_01", "expression": "rank(vec_avg({news_event_field}))"},
        {"template_id": "ne_02", "expression": "-rank(vec_avg({news_event_field}))"},
        {"template_id": "ne_03", "expression": "rank(ts_zscore(vec_avg({news_event_field}), {n}))"},
        {"template_id": "ne_04", "expression": "rank(ts_delta(vec_avg({news_event_field}), {n}))"},
        {"template_id": "ne_05", "expression": "ts_decay_linear(rank(vec_avg({news_event_field})), {n})"},
        {"template_id": "ne_06", "expression": "group_rank(vec_avg({news_event_field}), industry)"},
        {"template_id": "ne_07", "expression": "rank(vec_avg({news_event_field})) * rank(-returns)"},
        {"template_id": "ne_08", "expression": "rank(vec_avg({news_event_field})) * rank(adv20)"},
        {"template_id": "ne_09", "expression": "rank(vec_avg({news_event_field}) * -ts_zscore(returns, {n}))"},
        {"template_id": "ne_10", "expression": "trade_when(not(is_nan(vec_avg({news_event_field}))), rank(-returns), -1)"},
    ],

    # Underused RavenPack categories - ~50 fields the LLM never generates
    "rp_category_fresh": [
        {"template_id": "rpf_01", "expression": "rank(ts_backfill({rp_field}, 60))"},
        {"template_id": "rpf_02", "expression": "rank(ts_backfill({rp_field}, 60)) * rank(-returns)"},
        {"template_id": "rpf_03", "expression": "rank(ts_backfill({rp_field}, 60) * -ts_zscore(returns, {n}))"},
        {"template_id": "rpf_04", "expression": "ts_decay_linear(rank(ts_backfill({rp_field}, 60)), {n})"},
        {"template_id": "rpf_05", "expression": "rank(ts_delta(ts_backfill({rp_field}, 60), {n}))"},
        {"template_id": "rpf_06", "expression": "group_rank(ts_backfill({rp_field}, 60), industry)"},
        {"template_id": "rpf_07", "expression": "rank(ts_backfill({rp_field}, 60)) * rank(adv20)"},
        {"template_id": "rpf_08", "expression": "rank(ts_backfill({rp_field}, 60)) * rank(cap)"},
        {"template_id": "rpf_09", "expression": "rank(ts_backfill({rp_field}, 60) * -ts_mean((close - vwap) / vwap, {n}))"},
        {"template_id": "rpf_10", "expression": "rank(ts_zscore(ts_backfill({rp_field}, 60), {n})) + rank(-ts_mean(returns, {m}))"},
    ],

    # Derivative scores x price/vol - rate-of-change of fundamentals
    "derivative_interaction": [
        {"template_id": "di_01", "expression": "rank({derivative_field}) * rank(-returns)"},
        {"template_id": "di_02", "expression": "rank({derivative_field}) * rank(-ts_zscore(returns, {n}))"},
        {"template_id": "di_03", "expression": "rank({derivative_field}) + rank(-(close - vwap) / (vwap + 0.001))"},
        {"template_id": "di_04", "expression": "group_rank({derivative_field}, subindustry) * rank(-ts_mean(returns, {n}))"},
        {"template_id": "di_05", "expression": "rank(ts_zscore({derivative_field}, {n})) * rank(adv20)"},
        {"template_id": "di_06", "expression": "rank({derivative_field}) * rank(ts_backfill(implied_volatility_call_120, 60) / (historical_volatility_120 + 0.001))"},
        {"template_id": "di_07", "expression": "rank({derivative_field}) * rank(1 / (parkinson_volatility_180 + 0.001))"},
        {"template_id": "di_08", "expression": "ts_decay_linear(rank({derivative_field} * -ts_mean((close - vwap) / vwap, {n})), {m})"},
    ],

    # Cross-dimension: model77 x event/options - structural combinations too complex for combiner
    "cross_dimension": [
        {"template_id": "xd_01", "expression": "rank({model77_field}) * rank(ts_backfill({rp_field}, 60))"},
        {"template_id": "xd_02", "expression": "rank({model77_field}) * rank(vec_avg({news_event_field}))"},
        {"template_id": "xd_03", "expression": "rank({model77_field}) * rank({derivative_field})"},
        {"template_id": "xd_04", "expression": "rank(ts_backfill({rp_field}, 60)) * rank({derivative_field})"},
        {"template_id": "xd_05", "expression": "rank(ts_backfill({rp_field}, 60)) * rank(ts_backfill(implied_volatility_call_120, 60) - ts_backfill(implied_volatility_put_120, 60))"},
        {"template_id": "xd_06", "expression": "rank(vec_avg({news_event_field})) * rank({derivative_field}) * rank(adv20)"},
        {"template_id": "xd_07", "expression": "group_rank({model77_field}, industry) * rank(ts_backfill({rp_field}, 60))"},
        {"template_id": "xd_08", "expression": "rank({model77_field} * ts_backfill({rp_field}, 60)) + rank(-ts_mean(returns, {m}))"},
    ],

    #  v7.1: VOLATILITY-GATED TEMPLATES - rescue S=1.0-1.2 near-passers
    # trade_when(vol_condition, alpha, -1) reduces turnover and focuses on
    # high-information periods, often pushing S from 1.0-1.2 to 1.25+
    "vol_gated": [
        # Gate common alpha patterns by vol regime
        {"template_id": "vg_01", "expression": "trade_when(ts_rank(ts_std_dev(returns, 22), 252) > 0.5, rank(-returns), -1)"},
        {"template_id": "vg_02", "expression": "trade_when(ts_rank(ts_std_dev(returns, 22), 252) > 0.5, rank(-(close - vwap) / (vwap + 0.001)), -1)"},
        {"template_id": "vg_03", "expression": "trade_when(ts_rank(ts_std_dev(returns, 22), 252) > 0.5, rank(-ts_zscore(returns, {n})), -1)"},
        {"template_id": "vg_04", "expression": "trade_when(ts_rank(ts_std_dev(returns, 22), 252) > 0.5, rank({deep_field} / cap), -1)"},
        {"template_id": "vg_05", "expression": "trade_when(ts_rank(ts_std_dev(returns, 22), 252) > 0.5, rank(-ts_mean(returns, {n})) * rank(adv20), -1)"},
        {"template_id": "vg_06", "expression": "trade_when(ts_rank(ts_std_dev(returns, 22), 252) > 0.5, rank(ts_rank({deep_field} / cap, 252)), -1)"},
        {"template_id": "vg_07", "expression": "trade_when(volume > ts_mean(volume, 20), rank(-ts_zscore(returns, {n})) * rank(cap), -1)"},
        {"template_id": "vg_08", "expression": "trade_when(ts_rank(ts_std_dev(returns, 22), 252) > 0.5, group_rank(-ts_zscore(close, {n}), subindustry), -1)"},
        {"template_id": "vg_09", "expression": "trade_when(ts_rank(ts_std_dev(returns, 22), 252) > 0.5, rank({derivative_field}) * rank(-returns), -1)"},
        {"template_id": "vg_10", "expression": "trade_when(ts_rank(ts_std_dev(returns, 22), 252) > 0.55, rank(ts_backfill({rp_field}, 60)) * rank(-returns), -1)"},
    ],

    #  v7.1.1: ACCRUALS & QUALITY - academic factor zoo signals
    "accruals_quality": [
        {"template_id": "aq_01", "expression": "rank(cashflow_op / assets - operating_income / assets)"},
        {"template_id": "aq_02", "expression": "rank(ts_delta(cashflow_op / assets, 252) - ts_delta(operating_income / assets, 252))"},
        {"template_id": "aq_03", "expression": "-rank(ts_delta(assets, 252) / (assets + 0.001))"},
        {"template_id": "aq_04", "expression": "-rank(ts_delta(sharesout, 252) / (sharesout + 0.001))"},
        {"template_id": "aq_05", "expression": "rank(cashflow_op / (operating_income + 0.001))"},
        {"template_id": "aq_06", "expression": "rank(ts_corr(cashflow_op / cap, operating_income / cap, 252))"},
        {"template_id": "aq_07", "expression": "-rank(ts_zscore(assets, 252))"},
        {"template_id": "aq_08", "expression": "rank(cashflow_op / cap) - rank(operating_income / cap)"},
        {"template_id": "aq_09", "expression": "group_rank(cashflow_op / assets - operating_income / assets, industry)"},
        {"template_id": "aq_10", "expression": "rank(ts_rank(cashflow_op / assets - income / assets, 252))"},
    ],

    #  v7.1.1: IV TERM STRUCTURE - options implied vol signals
    "iv_term_structure": [
        {"template_id": "ivt_01", "expression": "rank(ts_backfill(implied_volatility_call_60, 60) / (ts_backfill(implied_volatility_call_270, 60) + 0.001))"},
        {"template_id": "ivt_02", "expression": "rank(ts_backfill(implied_volatility_call_30, 60) - ts_backfill(implied_volatility_call_120, 60))"},
        {"template_id": "ivt_03", "expression": "rank(ts_delta(ts_backfill(implied_volatility_call_60, 60) / (historical_volatility_60 + 0.001), {n}))"},
        {"template_id": "ivt_04", "expression": "rank(ts_backfill(implied_volatility_put_60, 60) / (ts_backfill(implied_volatility_call_60, 60) + 0.001) - 1)"},
        {"template_id": "ivt_05", "expression": "rank(ts_zscore(ts_backfill(implied_volatility_call_60, 60) - historical_volatility_60, {n}))"},
        {"template_id": "ivt_06", "expression": "rank(ts_backfill(implied_volatility_call_60, 60) / (historical_volatility_60 + 0.001)) * rank(-returns)"},
    ],

    # v7.2: RESEARCH-BACKED NOVEL TEMPLATES - break the self-corr wall
    # 73 submissions use 36 fields + 6 operator patterns.
    # These use 5,868 untouched fields + 10 unused operators.

    #  Correlation pipelines (NEW: ts_corr operator)
    "corr_pipeline": [
        {"template_id": "cp_01", "expression": "-ts_rank(ts_decay_linear(ts_corr(rank({fresh_est_field}), rank(returns), 60), 10), 20)"},
        {"template_id": "cp_02", "expression": "-ts_rank(ts_decay_linear(ts_corr(group_rank({fresh_fund_field}, industry), ts_rank(volume, 20), 20), 8), 15)"},
        {"template_id": "cp_03", "expression": "-ts_corr(rank({fresh_est_field}), rank({fresh_fund_field}), 120)"},
        {"template_id": "cp_04", "expression": "-ts_rank(ts_decay_linear(ts_decay_linear(ts_corr(close, volume, 10), 16), 4), 5)"},
        {"template_id": "cp_05", "expression": "-ts_corr(rank(ts_backfill({fn_field}, 60)), rank(returns), 120)"},
    ],

    #  Regression residuals (NEW: ts_regression operator)
    "regression_alpha": [
        {"template_id": "ra_01", "expression": "trade_when(ts_rank(ts_std_dev(returns, 22), 252) > 0.55, -ts_regression(returns, ts_delay(returns, 1), 120, lag=0, rettype=2), -1)"},
        {"template_id": "ra_02", "expression": "-rank(ts_regression({fresh_est_field}, ts_delay({fresh_est_field}, 20), 120, lag=0, rettype=2))"},
        {"template_id": "ra_03", "expression": "-rank(ts_regression(returns, ts_delay(rank({fresh_fund_field} / cap), 1), 60, lag=0, rettype=2))"},
        {"template_id": "ra_04", "expression": "rank(ts_regression({fresh_fund_field} / cap, ts_step(1), 252, lag=0, rettype=1))"},
    ],

    #  Accruals & earnings quality (academic anomalies)
    "earnings_quality": [
        {"template_id": "eq_01", "expression": "-group_zscore(rank((income - cashflow_op) / (assets + 0.001)), industry)"},
        {"template_id": "eq_02", "expression": "-ts_corr(cashflow_op / cap, income / cap, 252)"},
        {"template_id": "eq_03", "expression": "-group_rank(ts_delta(ts_backfill(capex / (sales + 0.001), 90), 90), industry)"},
        {"template_id": "eq_04", "expression": "-group_zscore(ts_delta(ts_delta(retained_earnings, 120), 120), sector)"},
        {"template_id": "eq_05", "expression": "group_rank(ts_backfill(rd_expense / (sales + 0.001), 90), industry)"},
    ],

    #  fn_financial quarterly (317 untouched fields)
    "fn_quarterly": [
        {"template_id": "fnq_01", "expression": "ts_rank(ts_backfill({fn_field}, 60) / cap, 252)"},
        {"template_id": "fnq_02", "expression": "group_rank(ts_backfill({fn_field}, 60) / cap, industry)"},
        {"template_id": "fnq_03", "expression": "rank(ts_delta(ts_backfill({fn_field}, 60), 60) / (ts_backfill({fn_field}, 60) + 0.001))"},
        {"template_id": "fnq_04", "expression": "-ts_corr(ts_backfill({fn_field}, 60) / cap, returns, 120)"},
        {"template_id": "fnq_05", "expression": "rank(ts_backfill({fn_field}, 60) / cap) * rank(-ts_av_diff(returns, 20))"},
        {"template_id": "fnq_06", "expression": "ts_decay_linear(group_rank(ts_backfill({fn_field}, 60) / cap, subindustry), {n})"},
        {"template_id": "fnq_07", "expression": "trade_when(ts_rank(ts_std_dev(returns, 22), 252) > 0.5, rank(ts_backfill({fn_field}, 60) / cap), -1)"},
        {"template_id": "fnq_08", "expression": "signed_power(group_rank(ts_backfill({fn_field}, 60) / cap, industry), 0.5)"},
    ],

    #  Derivative scores (24 fields, 100% untouched)
    "deriv_score": [
        {"template_id": "ds_01", "expression": "rank({deriv_field})"},
        {"template_id": "ds_02", "expression": "group_rank({deriv_field}, industry)"},
        {"template_id": "ds_03", "expression": "ts_decay_linear(rank({deriv_field}), {n})"},
        {"template_id": "ds_04", "expression": "rank({deriv_field}) * rank(-ts_av_diff(returns, 10))"},
        {"template_id": "ds_05", "expression": "trade_when(ts_rank(ts_std_dev(returns, 22), 252) > 0.5, rank({deriv_field}), -1)"},
        {"template_id": "ds_06", "expression": "signed_power(rank({deriv_field}), 0.5) * signed_power(rank(-returns), 0.5)"},
        {"template_id": "ds_07", "expression": "ts_rank(ts_delta({deriv_field}, 20), 120)"},
        {"template_id": "ds_08", "expression": "-ts_corr(rank({deriv_field}), rank(returns), 60)"},
    ],

    #  Risk beta (16 fields, 100% untouched)
    "beta_signal": [
        {"template_id": "bs_01", "expression": "-group_zscore({beta_field}, sector)"},
        {"template_id": "bs_02", "expression": "-rank({beta_field}) * rank((revenue - cogs) / (assets + 0.001))"},
        {"template_id": "bs_03", "expression": "trade_when({beta_field} < ts_mean({beta_field}, 60), rank(-returns), -1)"},
        {"template_id": "bs_04", "expression": "ts_delta(-rank({beta_field}), 20)"},
        {"template_id": "bs_05", "expression": "-ts_corr({beta_field}, returns, 120)"},
    ],

    #  Nonlinear / signed_power (NEW operator)
    "nonlinear_power": [
        {"template_id": "nl_01", "expression": "signed_power(group_rank({fresh_fund_field} / cap, industry), 0.5) * signed_power(rank(-returns), 0.5)"},
        {"template_id": "nl_02", "expression": "signed_power(rank(ts_backfill({fn_field}, 60) / cap), 0.7) * signed_power(rank({deriv_field}), 0.3)"},
        {"template_id": "nl_03", "expression": "signed_power(ts_rank({fresh_fund_field} / cap, 252), 2.0)"},
    ],

    #  Ternary regime switching (structural novelty)
    "regime_ternary": [
        {"template_id": "rt_01", "expression": "if_else(ts_mean(close, 2) < ts_mean(close, 8) - ts_std_dev(close, 8), 1, if_else(ts_mean(close, 2) > ts_mean(close, 8) + ts_std_dev(close, 8), -1, rank(-ts_delta(close, 1))))"},
        {"template_id": "rt_02", "expression": "if_else(group_rank({fresh_fund_field} / cap, industry) > 0.6, rank(-ts_delta(close, 3)), 0)"},
        {"template_id": "rt_03", "expression": "if_else(ts_delta({fresh_est_field}, 20) > 0, rank({fresh_est_field} / close), rank(-returns))"},
    ],

    #  Max/min pipeline selectors (adaptive architecture)
    "pipeline_select": [
        {"template_id": "ps_01", "expression": "max(ts_rank(ts_decay_linear(ts_corr(close, volume, 15), 5), 12), ts_rank(rank({fresh_fund_field} / cap), 60)) * -1"},
        {"template_id": "ps_02", "expression": "max(rank({deriv_field}), rank(ts_backfill({fn_field}, 60) / cap))"},
    ],

    #  Fresh fundamentals (proven patterns, fresh fields)
    "fresh_fundamental": [
        {"template_id": "ff_01", "expression": "ts_rank({fresh_fund_field} / cap, 252)"},
        {"template_id": "ff_02", "expression": "group_rank(ts_rank({fresh_fund_field} / cap, 252), industry)"},
        {"template_id": "ff_03", "expression": "rank(ts_zscore({fresh_fund_field} / cap, {n}))"},
        {"template_id": "ff_04", "expression": "rank({fresh_fund_field} / cap) * rank(-returns)"},
        {"template_id": "ff_05", "expression": "rank(ts_delta({fresh_fund_field}, {n}) / ({fresh_fund_field} + 0.001))"},
        {"template_id": "ff_06", "expression": "-rank(ts_zscore({fresh_fund_field}, {n})) + -rank(ts_mean((close - vwap) / vwap, {m}))"},
        {"template_id": "ff_07", "expression": "rank({fresh_fund_field} / cap) + rank(trade_when(ts_rank(ts_std_dev(returns, 22), 252) > 0.5, rank(-returns), -1))"},
        {"template_id": "ff_08", "expression": "group_rank({fresh_fund_field} / cap, subindustry) * rank(-ts_mean(returns, {n}))"},
        {"template_id": "ff_09", "expression": "ts_decay_linear(rank({fresh_fund_field} / cap), {n})"},
        {"template_id": "ff_10", "expression": "rank(ts_rank({fresh_fund_field} / cap, 60)) * rank(ts_rank({fresh_fund_field} / cap, 252))"},
    ],

    #  Fresh analyst estimates
    "fresh_estimates": [
        {"template_id": "fe_01", "expression": "group_rank(ts_rank({fresh_est_field} / close, 60), industry)"},
        {"template_id": "fe_02", "expression": "rank(ts_zscore({fresh_est_field} / cap, {n}))"},
        {"template_id": "fe_03", "expression": "rank(ts_delta({fresh_est_field}, 60) / ({fresh_est_field} + 0.001))"},
        {"template_id": "fe_04", "expression": "rank({fresh_est_field} / cap) * rank(-returns)"},
        {"template_id": "fe_05", "expression": "ts_decay_linear(rank(group_rank({fresh_est_field} / close, industry)), {n})"},
        {"template_id": "fe_06", "expression": "rank(ts_rank({fresh_est_field} / cap, 252)) + rank(-ts_mean(returns, {m}))"},
        {"template_id": "fe_07", "expression": "rank({fresh_est_field} / close) * rank(trade_when(ts_rank(ts_std_dev(returns, 22), 252) > 0.5, rank(-returns), -1))"},
        {"template_id": "fe_08", "expression": "group_rank(ts_zscore({fresh_est_field} / close, {n}), subindustry)"},
    ],

    #  Model77 novel patterns (EWAN ONLY - 3,238 untouched anomaly fields)
    "model77_novel": [
        {"template_id": "m7n_01", "expression": "group_zscore({model77_field}, sector)"},
        {"template_id": "m7n_02", "expression": "-ts_delta({model77_field}, 60)"},
        {"template_id": "m7n_03", "expression": "rank(ts_arg_max({model77_field}, 252)) * signed_power({model77_field}, 0.5)"},
        {"template_id": "m7n_04", "expression": "trade_when(ts_arg_min({model77_field}, 120) < 20, ts_av_diff({model77_field}, 60), -1)"},
        {"template_id": "m7n_05", "expression": "ts_quantile({model77_field}, 252)"},
        {"template_id": "m7n_06", "expression": "-ts_corr(rank({model77_field}), rank(returns), 120)"},
        {"template_id": "m7n_07", "expression": "signed_power({model77_field}, 0.5) * signed_power(rank(-returns), 0.5)"},
        {"template_id": "m7n_08", "expression": "trade_when(ts_rank(ts_std_dev(returns, 22), 252) > 0.5, rank({model77_field}), -1)"},
        {"template_id": "m7n_09", "expression": "group_rank({model77_field}, industry) * rank(-ts_av_diff(returns, 10))"},
        {"template_id": "m7n_10", "expression": "-ts_regression({model77_field}, ts_delay({model77_field}, 20), 120, lag=0, rettype=2)"},
    ],
}

#  v7.0: Dynamic field loading from datasets.py
# Fields are loaded from the team datasets Excel at startup.
# If the Excel is unavailable, built-in fallbacks are used.
from datasets import (
    get_fundamental_fields, get_deep_fundamental_fields, get_analyst_fields,
    get_sentiment_fields, get_fscore_fields, get_derivative_fields,
    get_options_windows, get_pcr_windows, get_model77_fields,
    get_news_event_fields, get_rp_underused_fields,
    get_fresh_fundamental_fields, get_fresh_fn_fields, get_fresh_estimate_fields,
)

FUNDAMENTAL_FIELDS = get_fundamental_fields()
DEEP_FUNDAMENTAL_FIELDS = get_deep_fundamental_fields()
ANALYST_FIELDS = get_analyst_fields()
SENTIMENT_FIELDS = get_sentiment_fields()
FSCORE_FIELDS = get_fscore_fields()
DERIVATIVE_FIELDS = get_derivative_fields()
OPTIONS_WINDOWS = get_options_windows()
PCR_WINDOWS = get_pcr_windows()

# v7.1: Fresh field pools - fields NOT in any existing submission
FRESH_FUND_FIELDS = get_fresh_fundamental_fields() or [
    "retained_earnings", "ebitda", "(revenue - cogs)", "income",
    "total_debt", "free_cash_flow", "rd_expense", "capex",
    "working_capital", "equity", "equity",
    "dividend / (close + 0.001)", "interest_expense", "depreciation",
]
FRESH_FN_FIELDS = get_fresh_fn_fields() or [
    "fn_oper_income_q", "sales", "ebitda", "income",
    "cash", "debt", "revenue",
    "cashflow", "cashflow_op", "capex",
]
FRESH_EST_FIELDS = get_fresh_estimate_fields() or [
    "est_ptp", "est_sales", "est_ebitda", "est_eps",
    "est_eps", "bookvalue_ps", "est_eps",
]
RISK_BETA_FIELDS = [
    "beta_last_30_days_spy", "beta_last_60_days_spy", "beta_last_90_days_spy",
    "beta_last_60_days_spy", "beta_last_360_days_spy", "beta_last_360_days_spy",
]

# v7.1: Untouched field pools for new signal dimensions
NEWS_EVENT_FIELDS = get_news_event_fields() or [
    "ts_backfill(nws18_acb, 60)", "ts_backfill(nws18_bam, 60)", "ts_backfill(nws18_bee, 60)", "ts_backfill(nws18_ber, 60)",
    "ts_backfill(nws18_event_relevance, 60)", "ts_backfill(nws18_event_similarity_days, 60)",
    "ts_backfill(nws18_ghc_lna, 60)", "ts_backfill(nws18_nip, 60)", "ts_backfill(nws18_qcm, 60)", "ts_backfill(nws18_qep, 60)",
    "ts_backfill(nws18_qmb, 60)", "ts_backfill(nws18_relevance, 60)", "ts_backfill(nws18_ssc, 60)", "ts_backfill(nws18_sse, 60)",
]
RP_UNDERUSED_FIELDS = get_rp_underused_fields() or [
    "ts_backfill(rp_css_assets, 60)", "ts_backfill(rp_css_business, 60)", "ts_backfill(rp_css_dividends, 60)", "ts_backfill(rp_css_equity, 60)",
    "ts_backfill(rp_css_insider, 60)", "ts_backfill(rp_css_labor, 60)", "ts_backfill(rp_css_mna, 60)", "ts_backfill(rp_css_product, 60)",
    "ts_backfill(rp_css_revenue, 60)", "ts_backfill(rp_css_technical, 60)",
    "ts_backfill(rp_ess_assets, 60)", "ts_backfill(rp_ess_business, 60)", "ts_backfill(rp_ess_credit, 60)", "ts_backfill(rp_ess_dividends, 60)",
    "ts_backfill(rp_ess_equity, 60)", "ts_backfill(rp_ess_insider, 60)", "ts_backfill(rp_ess_labor, 60)", "ts_backfill(rp_ess_product, 60)",
    "ts_backfill(rp_ess_revenue, 60)", "ts_backfill(rp_ess_technical, 60)",
    "ts_backfill(rp_nip_assets, 60)", "ts_backfill(rp_nip_business, 60)", "ts_backfill(rp_nip_credit, 60)", "ts_backfill(rp_nip_dividends, 60)",
    "ts_backfill(rp_nip_equity, 60)", "ts_backfill(rp_nip_insider, 60)", "ts_backfill(rp_nip_labor, 60)", "ts_backfill(rp_nip_product, 60)",
    "ts_backfill(rp_nip_revenue, 60)", "ts_backfill(rp_nip_technical, 60)",
]

# Model77 fields - curated tiers for template sampling
# The full 3,241 field pool is available to the LLM, but template {model77_field}
# sampling needs tight tiers to avoid wasting sims.
_model77_all = get_model77_fields()

# Tier 1: PROVEN high-impact fields (same as v6.2.1 - hand-curated from research)
MODEL77_TIER1_FIELDS = [
    "standardized_unexpected_earnings", "standardized_unexpected_earnings_2",
    "earnings_momentum_composite_score", "earnings_momentum_analyst_score",
    "earnings_revision_magnitude", "sales_surprise_score",
    "change_in_eps_surprise", "net_fy1_analyst_revisions",
    "three_month_fy1_eps_revision", "six_month_avg_fy1_eps_revision",
    "forward_median_earnings_yield", "normalized_earnings_yield",
    "forward_cash_flow_to_price", "ebitda / (enterprise_value + 0.001)",
    "tobins_q_ratio", "financial_statement_value_score",
    "equity_value_score", "income_statement_value_score",
    "(revenue - cogs) / (assets + 0.001)", "gross_profit_margin_ttm_2",
    "cashflow_op / (assets + 0.001)", "cash_earnings_return_on_equity",
    "return_on_invested_capital_4", "fcf_yield_multiplied_forward_roe",
    "asset_growth_rate", "one_year_change_total_assets",
    "sustainable_growth_rate", "reinvestment_rate",
    "debt / (equity + 0.001)", "credit_risk_premium_indicator",
    "twelve_month_short_interest_change",
    "value_momentum_analyst_score", "momentum_analyst_composite_score",
    "price_momentum_module_score", "fundamental_growth_module_score",
]
# Filter to only fields that actually exist in the loaded dataset
if _model77_all:
    _available = set(_model77_all)
    MODEL77_TIER1_FIELDS = [f for f in MODEL77_TIER1_FIELDS if f in _available]

# Tier 2: Secondary proven fields
MODEL77_TIER2_FIELDS = [
    "trailing_twelve_month_accruals",
    "standardized_unexpected_cash_flow", "standardized_unexpected_cashflow",
    "book_leverage_ratio_3", "interest_coverage_ratio_5",
    "yearly_change_leverage", "twelve_month_total_debt_change_2",
    "ts_std_dev(eps, 252)", "one_year_eps_growth_rate",
    "forward_two_year_eps_growth", "one_year_ahead_eps_growth",
    "one_quarter_ahead_eps_growth", "long_term_growth_estimate",
    "capex_to_total_assets", "capex / (depre_amort + 0.001)",
    "ttm_operating_cash_flow_to_price", "ttm_operating_income_to_ev",
    "ttm_sales_to_enterprise_value",
    "implied_minus_realized_volatility_2", "implied_option_volatility",
    "out_of_money_put_call_ratio",
    "industry_relative_return_4w", "industry_relative_return_5d",
    "industry_relative_book_to_market", "industry_relative_fcf_to_price",
    "cash_burn_rate", "inventory_change_avg_assets",
    "rd_expense_to_sales_2", "visibility_ratio", "treynor_ratio",
]
if _model77_all:
    MODEL77_TIER2_FIELDS = [f for f in MODEL77_TIER2_FIELDS if f in _available]

# If we have the full dataset, add remaining fields as a low-probability exploration pool
# The generator samples: 70% tier1, 25% tier2, 5% tier3 (exploration)
_curated = set(MODEL77_TIER1_FIELDS + MODEL77_TIER2_FIELDS)
MODEL77_TIER3_FIELDS = [f for f in _model77_all if f not in _curated] if _model77_all else []

MODEL77_ALL_FIELDS = MODEL77_TIER1_FIELDS + MODEL77_TIER2_FIELDS + MODEL77_TIER3_FIELDS

MODEL77_NEGATIVE_DIRECTION = {
    "asset_growth_rate", "one_year_change_total_assets",
    "trailing_twelve_month_accruals", "twelve_month_total_debt_change_2",
    "yearly_change_leverage", "debt / (equity + 0.001)",
    "credit_risk_premium_indicator", "twelve_month_short_interest_change",
    "cash_burn_rate", "book_leverage_ratio_3",
    "implied_minus_realized_volatility_2",
}

SAFE_PARAM_RANGES = {
    "n": [3, 5, 10, 20, 40, 60],
    "m": [5, 10, 20, 60],
}

FUNDAMENTAL_PARAM_RANGES = {
    "n": [60, 120, 180, 252],
    "m": [60, 120, 252],
}

# v5.9: Dataset-aware neutralization (from official Neutralisation.csv)
DATASET_NEUTRALIZATION = {
    "fundamental_value": ["INDUSTRY", "SUBINDUSTRY"],
    "quality_trend": ["INDUSTRY", "SUBINDUSTRY"],
    "size_value": ["INDUSTRY", "SUBINDUSTRY"],
    "expanded_fundamental": ["INDUSTRY", "SUBINDUSTRY"],
    "fundamental": ["INDUSTRY", "SUBINDUSTRY"],
    "earnings_momentum": ["INDUSTRY", "NONE"],
    "analyst_sentiment": ["INDUSTRY", "SUBINDUSTRY"],
    "analyst_estimates": ["INDUSTRY", "SUBINDUSTRY"],
    "fundamental_scores": ["SUBINDUSTRY", "INDUSTRY", "MARKET", "SECTOR"],
    "model77_anomaly": ["INDUSTRY", "SUBINDUSTRY", "MARKET", "SECTOR"],
    "model77_combo": ["INDUSTRY", "SUBINDUSTRY", "MARKET"],
    "news_sentiment": ["SUBINDUSTRY", "INDUSTRY"],
    "options_vol": ["MARKET", "SECTOR"],
    "mean_reversion": ["MARKET", "SECTOR", "NONE"],
    "cross_sectional": ["SUBINDUSTRY", "MARKET"],
    "liquidity_scaled": ["MARKET", "SECTOR"],
    "conditional": ["MARKET", "SECTOR"],
    "vol_adjusted": ["MARKET", "SECTOR"],
    "momentum": ["MARKET", "SECTOR"],
    "volume_flow": ["MARKET", "SECTOR"],
    "price_vol_corr": ["MARKET", "SECTOR"],
    "volatility": ["MARKET", "SECTOR"],
    "intraday": ["MARKET", "SECTOR"],
    "vol_regime": ["MARKET", "NONE"],
    "relationship": ["SUBINDUSTRY", "INDUSTRY"],
    "risk_beta": ["MARKET", "INDUSTRY"],
    "combo_factor": ["MARKET", "INDUSTRY", "SUBINDUSTRY"],
    "wq_proven": ["INDUSTRY", "SUBINDUSTRY", "SECTOR", "MARKET"],
    "fn_financial": ["INDUSTRY", "SUBINDUSTRY", "MARKET"],
    "fundamental_vol": ["INDUSTRY", "SUBINDUSTRY", "MARKET"],
    "simple_ratio": ["SUBINDUSTRY", "INDUSTRY", "MARKET", "SECTOR"],
    # v7.0: Added missing families (were falling back to DEFAULT_NEUTRALIZATIONS)
    "vector_data": ["SUBINDUSTRY", "MARKET"],
    "supply_chain": ["SUBINDUSTRY", "INDUSTRY"],
    "ravenpack_cat": ["SUBINDUSTRY", "MARKET", "INDUSTRY"],
    "options_analytics": ["MARKET", "SECTOR", "INDUSTRY"],
    "hist_vol": ["MARKET", "SECTOR"],
    "fscore": ["INDUSTRY", "SUBINDUSTRY", "MARKET"],
    "risk_metrics": ["MARKET", "INDUSTRY", "SUBINDUSTRY"],
    "intraday_pattern": ["SECTOR", "MARKET"],
    "analyst_deep": ["INDUSTRY", "SUBINDUSTRY"],
    "social_scalar": ["SUBINDUSTRY", "MARKET"],
    "wild_combos": ["MARKET", "INDUSTRY", "SUBINDUSTRY"],
    "tutorial_proven": ["MARKET", "INDUSTRY", "SECTOR"],
    "high_sharpe": ["SUBINDUSTRY", "INDUSTRY", "MARKET"],
    # v7.1: New signal dimension families
    "news_event_signal": ["SUBINDUSTRY", "MARKET", "INDUSTRY"],
    "rp_category_fresh": ["SUBINDUSTRY", "MARKET", "INDUSTRY"],
    "derivative_interaction": ["INDUSTRY", "SUBINDUSTRY", "MARKET"],
    "cross_dimension": ["INDUSTRY", "SUBINDUSTRY", "MARKET"],
    "vol_gated": ["MARKET", "SECTOR", "NONE"],
    # v7.1.1: Academic factor zoo + IV term structure
    "accruals_quality": ["INDUSTRY", "SUBINDUSTRY", "MARKET"],
    "iv_term_structure": ["MARKET", "SECTOR", "INDUSTRY"],
    # v7.2: Research-backed novel families
    "corr_pipeline": ["MARKET", "INDUSTRY", "SUBINDUSTRY"],
    "regression_alpha": ["MARKET", "SECTOR", "NONE"],
    "earnings_quality": ["INDUSTRY", "SUBINDUSTRY", "MARKET"],
    "fn_quarterly": ["INDUSTRY", "SUBINDUSTRY", "MARKET"],
    "deriv_score": ["INDUSTRY", "MARKET", "SECTOR", "SUBINDUSTRY"],
    "beta_signal": ["MARKET", "SECTOR", "NONE"],
    "nonlinear_power": ["INDUSTRY", "MARKET", "SUBINDUSTRY"],
    "regime_ternary": ["MARKET", "SECTOR", "NONE"],
    "pipeline_select": ["MARKET", "INDUSTRY", "SUBINDUSTRY"],
    "fresh_fundamental": ["INDUSTRY", "SUBINDUSTRY", "MARKET"],
    "fresh_estimates": ["INDUSTRY", "SUBINDUSTRY", "MARKET"],
    "model77_novel": ["INDUSTRY", "SUBINDUSTRY", "MARKET", "SECTOR"],
}


# v7.2.4: Delay-0 specialist mini-universe templates
# These are deliberately short-horizon and are sampled with delay=0 settings
# only. They are kept separate from the Delay-1 combiner/evolver pools.
DELAY0_TEMPLATES = {
    "delay0_open_gap_reversal": [
        {"template_id": "d0_gap_01", "expression": "rank(-(open - ts_delay(close, 1)) / (ts_delay(close, 1) + 0.001))"},
        {"template_id": "d0_gap_02", "expression": "group_rank(-(open - ts_delay(close, 1)) / (ts_delay(close, 1) + 0.001), subindustry)"},
        {"template_id": "d0_gap_03", "expression": "rank(-ts_zscore((open - ts_delay(close, 1)) / (ts_delay(close, 1) + 0.001), 20))"},
    ],
    "delay0_close_vwap_dislocation": [
        {"template_id": "d0_vwap_01", "expression": "rank((vwap - close) / (close + 0.001))"},
        {"template_id": "d0_vwap_02", "expression": "group_rank((vwap - close) / (close + 0.001), industry)"},
        {"template_id": "d0_vwap_03", "expression": "rank(-ts_zscore((close - vwap) / (vwap + 0.001), 20))"},
        {"template_id": "d0_vwap_04", "expression": "rank(ts_rank((vwap - close) / (close + 0.001), 5))"},
    ],
    "delay0_range_position": [
        {"template_id": "d0_rng_01", "expression": "rank((high - close) / (high - low + 0.001))"},
        {"template_id": "d0_rng_02", "expression": "rank(-(close - low) / (high - low + 0.001))"},
        {"template_id": "d0_rng_03", "expression": "group_rank((vwap - close) / (high - low + 0.001), subindustry)"},
        {"template_id": "d0_rng_04", "expression": "rank(-ts_zscore((close - low) / (high - low + 0.001), 10))"},
    ],
    "delay0_volume_shock": [
        {"template_id": "d0_vol_01", "expression": "rank(-returns * rank(volume / (adv20 + 0.001)))"},
        {"template_id": "d0_vol_02", "expression": "rank(ts_delta(volume, 1) / (adv20 + 0.001)) * rank(-returns)"},
        {"template_id": "d0_vol_03", "expression": "trade_when(volume > ts_mean(volume, 5), rank(-returns), -1)"},
        {"template_id": "d0_vol_04", "expression": "rank(-ts_zscore(returns, 5) * rank(volume / (adv20 + 0.001)))"},
    ],
    "delay0_liquidity_pressure": [
        {"template_id": "d0_liq_01", "expression": "rank(-returns * rank(adv20))"},
        {"template_id": "d0_liq_02", "expression": "rank((vwap - close) / (close + 0.001)) * rank(adv20)"},
        {"template_id": "d0_liq_03", "expression": "group_rank(-returns * rank(volume / (adv20 + 0.001)), industry)"},
    ],
    "delay0_options_intraday": [
        {"template_id": "d0_opt_01", "expression": "rank(ts_backfill(implied_volatility_call_30 - implied_volatility_put_30, 20)) * rank(-returns)"},
        {"template_id": "d0_opt_02", "expression": "rank(ts_delta(implied_volatility_mean_30, 5)) * rank((vwap - close) / (close + 0.001))"},
        {"template_id": "d0_opt_03", "expression": "rank(ts_backfill(call_breakeven_60 / (close + 0.001) - 1, 20)) * rank(-returns)"},
    ],
    "delay0_news_reaction": [
        {"template_id": "d0_news_01", "expression": "rank(ts_decay_linear(ts_backfill(rp_css_mna, 20), 3)) * rank(-returns)"},
        {"template_id": "d0_news_02", "expression": "rank(ts_decay_linear(ts_backfill(rp_css_business, 20), 3)) * rank(-returns)"},
        {"template_id": "d0_news_03", "expression": "rank(ts_decay_linear(ts_backfill(news_atr_ratio, 20), 3)) * rank((vwap - close) / (close + 0.001))"},
        {"template_id": "d0_news_04", "expression": "rank(ts_backfill(snt_social_value, 20)) * rank(-returns)"},
    ],
    "delay0_risk_intraday": [
        {"template_id": "d0_risk_01", "expression": "trade_when(ts_rank(ts_std_dev(returns, 22), 252) > 0.5, rank(-returns), -1)"},
        {"template_id": "d0_risk_02", "expression": "rank(-returns) * rank(beta_last_60_days_spy)"},
        {"template_id": "d0_risk_03", "expression": "rank((vwap - close) / (close + 0.001)) * rank(-beta_last_60_days_spy)"},
    ],
}
TEMPLATE_LIBRARY.update(DELAY0_TEMPLATES)

# v7.2.7: NEW EXCELLENT TEMPLATE FAMILIES
# Targets the saturation problem by introducing structurally orthogonal alphas.
# The portfolio is dominated by `rank(ts_backfill(X)) * rank(-returns)` shapes.
# These families use DIFFERENT mathematical foundations, more likely to
# clear self-correlation against existing submissions even when fields overlap.
#
# Eight new family clusters covering ~70 templates:
#   1. ts_regression rettypes 0/1/3/4 - slope/intercept/predicted/y-mean
#      (existing portfolio only uses rettype=2). Each rettype = different signal shape.
#   2. Vector aggregations - vec_avg/vec_sum on news/sentiment vector fields,
#      structurally distinct from time-series operators.
#   3. Group-conditional regimes - trade_when() on group_rank thresholds,
#      sparse selective signals uncorrelated with always-on alphas.
#   4. Multi-timeframe consensus - sign-agreement gating, high-conviction sparse.
#   5. Rank stability - rewards stocks with stable ranking, new consistency axis.
#   6. Alternative operator combinations - min/max/diff selectors instead of */+.
#   7. ts_covariance - unnormalized co-movement (different from ts_corr).
#   8. ts_product - geometric/multiplicative dynamics.
V727_NEW_TEMPLATES = {

    #  1. REGRESSION RETTYPES 0/1/3/4
    "regression_slope": [
        {"template_id": "rgs_01", "expression": "rank(ts_regression(close, ts_step(20), 60, lag=0, rettype=0))"},
        {"template_id": "rgs_02", "expression": "rank(-ts_regression(returns, ts_mean(returns, 20), 60, lag=0, rettype=0))"},
        {"template_id": "rgs_03", "expression": "rank(ts_regression(volume, ts_step(20), 60, lag=0, rettype=0)) * rank(-returns)"},
        {"template_id": "rgs_04", "expression": "rank(ts_regression(vwap / (close + 0.001), ts_step(20), 60, lag=0, rettype=0))"},
        {"template_id": "rgs_05", "expression": "rank(ts_regression(ts_backfill({field}, 60), ts_step(20), 60, lag=0, rettype=0))"},
        {"template_id": "rgs_06", "expression": "rank(-ts_regression(close, ts_mean(close, 60), 120, lag=0, rettype=0))"},
        {"template_id": "rgs_07", "expression": "group_rank(ts_regression(close, ts_step(20), 40, lag=0, rettype=0), industry)"},
    ],
    "regression_intercept": [
        {"template_id": "rgi_01", "expression": "rank(-ts_regression(close, ts_step(20), 60, lag=0, rettype=1))"},
        {"template_id": "rgi_02", "expression": "rank(ts_regression(returns, ts_mean(returns, 20), 60, lag=0, rettype=1))"},
        {"template_id": "rgi_03", "expression": "rank(ts_regression(vwap, ts_step(20), 60, lag=0, rettype=1))"},
        {"template_id": "rgi_04", "expression": "rank(ts_regression(close, ts_step(60), 120, lag=0, rettype=1)) * rank(-returns)"},
        {"template_id": "rgi_05", "expression": "group_rank(-ts_regression(close, ts_step(40), 60, lag=0, rettype=1), industry)"},
    ],
    "regression_predicted": [
        {"template_id": "rgp_01", "expression": "rank(close - ts_regression(close, ts_step(20), 40, lag=0, rettype=3))"},
        {"template_id": "rgp_02", "expression": "rank(-(returns - ts_regression(returns, ts_mean(returns, 20), 60, lag=0, rettype=3)))"},
        {"template_id": "rgp_03", "expression": "rank(vwap - ts_regression(vwap, ts_step(20), 40, lag=0, rettype=3))"},
        {"template_id": "rgp_04", "expression": "rank(-ts_regression(close, ts_decay_linear(close, 30), 30, lag=0, rettype=3))"},
        {"template_id": "rgp_05", "expression": "rank(ts_backfill({field}, 60) - ts_regression(ts_backfill({field}, 60), ts_step(20), 40, lag=0, rettype=3))"},
        {"template_id": "rgp_06", "expression": "group_rank(close - ts_regression(close, ts_step(20), 40, lag=0, rettype=3), industry)"},
    ],
    "regression_ymean": [
        {"template_id": "rgy_01", "expression": "rank(close - ts_regression(close, ts_step(20), 60, lag=0, rettype=4))"},
        {"template_id": "rgy_02", "expression": "rank(returns - ts_regression(returns, ts_step(10), 30, lag=0, rettype=4))"},
        {"template_id": "rgy_03", "expression": "rank(-ts_regression(close, ts_step(20), 120, lag=0, rettype=4)) * rank(-returns)"},
    ],

    #  2. VECTOR AGGREGATION (hardcoded known-good vector fields)
    "vector_news_aggregation": [
        {"template_id": "vna_01", "expression": "rank(ts_decay_linear(vec_avg(nws18_bam), 10))"},
        {"template_id": "vna_02", "expression": "rank(ts_zscore(vec_avg(nws18_bee), 60))"},
        {"template_id": "vna_03", "expression": "rank(vec_sum(nws18_qep) - ts_mean(vec_sum(nws18_qep), 20))"},
        {"template_id": "vna_04", "expression": "rank(vec_avg(nws18_ssc)) * rank(-returns)"},
        {"template_id": "vna_05", "expression": "group_rank(ts_decay_linear(vec_avg(nws18_ber), 10), industry)"},
        {"template_id": "vna_06", "expression": "rank(ts_delta(vec_avg(nws18_bam), 5))"},
        {"template_id": "vna_07", "expression": "rank(-ts_corr(vec_avg(nws18_bee), returns, 20))"},
        {"template_id": "vna_08", "expression": "rank(ts_zscore(vec_avg(nws18_qep), 60)) * rank(volume / (adv20 + 0.001))"},
    ],
    "vector_sentiment_aggregation": [
        {"template_id": "vsa_01", "expression": "rank(vec_avg(scl12_sentvec) - ts_mean(vec_avg(scl12_sentvec), 20))"},
        {"template_id": "vsa_02", "expression": "rank(ts_zscore(vec_sum(scl12_sentvec), 40))"},
        {"template_id": "vsa_03", "expression": "rank(vec_avg(scl12_sentvec)) * rank(-returns)"},
        {"template_id": "vsa_04", "expression": "group_zscore(ts_decay_linear(vec_avg(scl12_alltype_sentvec), 8), industry)"},
        {"template_id": "vsa_05", "expression": "rank(ts_delta(vec_avg(scl12_alltype_sentvec), 10))"},
        {"template_id": "vsa_06", "expression": "rank(ts_corr(vec_avg(scl12_sentvec), volume, 20))"},
    ],

    #  3. GROUP-CONDITIONAL REGIMES
    "group_conditional_high_volume": [
        {"template_id": "gch_01", "expression": "trade_when(group_rank(volume, industry) > 0.7, rank(-returns), -1)"},
        {"template_id": "gch_02", "expression": "trade_when(group_rank(volume / (adv20 + 0.001), industry) > 0.8, rank(-ts_mean(returns, 5)), -1)"},
        {"template_id": "gch_03", "expression": "trade_when(group_rank(volume, subindustry) > 0.6, rank(ts_backfill({field}, 60)), -1)"},
        {"template_id": "gch_04", "expression": "trade_when(group_rank(volume, industry) > 0.8, group_zscore(returns, industry), -1)"},
    ],
    "group_conditional_high_momentum": [
        {"template_id": "gcm_01", "expression": "trade_when(group_rank(ts_mean(returns, 20), industry) > 0.7, rank(-ts_mean(returns, 5)), -1)"},
        {"template_id": "gcm_02", "expression": "trade_when(group_rank(returns, sector) < 0.3, rank({field}), -1)"},
        {"template_id": "gcm_03", "expression": "trade_when(group_rank(ts_std_dev(returns, 22), industry) > 0.7, rank(-returns), -1)"},
        {"template_id": "gcm_04", "expression": "trade_when(group_rank(close / ts_mean(close, 60), industry) > 0.6, rank(-returns), -1)"},
    ],
    "group_conditional_low_volatility": [
        {"template_id": "gcl_01", "expression": "trade_when(group_rank(ts_std_dev(returns, 22), industry) < 0.3, rank({field}), -1)"},
        {"template_id": "gcl_02", "expression": "trade_when(group_rank(ts_std_dev(returns, 60), sector) < 0.2, rank(-returns), -1)"},
        {"template_id": "gcl_03", "expression": "trade_when(group_rank(historical_volatility_60, industry) < 0.3, rank(ts_backfill({field}, 60)), -1)"},
    ],

    #  4. MULTI-TIMEFRAME CONSENSUS
    "multi_timeframe_consensus": [
        {"template_id": "mtc_01", "expression": "trade_when(sign(ts_delta(close, 5)) == sign(ts_delta(close, 20)), rank(-returns), -1)"},
        {"template_id": "mtc_02", "expression": "trade_when(sign(ts_mean(returns, 5)) == sign(ts_mean(returns, 60)), rank(-ts_mean(returns, 5)), -1)"},
        {"template_id": "mtc_03", "expression": "rank(sign(ts_delta(close, 5)) + sign(ts_delta(close, 20)) + sign(ts_delta(close, 60)))"},
        {"template_id": "mtc_04", "expression": "trade_when(sign(ts_zscore(volume, 10)) == sign(ts_zscore(volume, 60)), rank(-returns), -1)"},
        {"template_id": "mtc_05", "expression": "rank(sign(ts_delta({field}, 20)) * sign(ts_delta({field}, 60)))"},
        {"template_id": "mtc_06", "expression": "trade_when(and(ts_rank(returns, 5) > 0.7, ts_rank(returns, 60) > 0.7), rank(-returns), -1)"},
    ],

    #  5. RANK STABILITY
    "rank_stability": [
        {"template_id": "rks_01", "expression": "rank(-ts_std_dev(rank({field}), 60))"},
        {"template_id": "rks_02", "expression": "rank(-ts_std_dev(rank(returns), 40)) * rank(-returns)"},
        {"template_id": "rks_03", "expression": "rank(-ts_std_dev(group_rank({field}, industry), 60))"},
        {"template_id": "rks_04", "expression": "rank(-ts_std_dev(rank(volume), 30)) * rank(-ts_mean(returns, 5))"},
        {"template_id": "rks_05", "expression": "rank(ts_corr(rank({field}), rank(ts_delay({field}, 5)), 60))"},
    ],

    #  6. ALT COMBO MIN/MAX/DIFF SELECTORS
    "alt_combo_min_max": [
        {"template_id": "acm_01", "expression": "rank(min(rank({field}), rank(-returns)))"},
        {"template_id": "acm_02", "expression": "rank(max(rank({field}), rank(-ts_mean(returns, 5))))"},
        {"template_id": "acm_03", "expression": "rank(rank({field}) - rank(-returns))"},
        {"template_id": "acm_04", "expression": "rank(-min(rank(returns), rank(-ts_delta(close, 20))))"},
        {"template_id": "acm_05", "expression": "if_else(rank({field}) > 0.5, rank(-returns), -rank(-returns))"},
        {"template_id": "acm_06", "expression": "rank(min(group_rank({field}, industry), group_rank(-returns, industry)))"},
    ],

    #  7. TS_COVARIANCE (rarely used, unnormalized co-movement)
    "ts_covariance_signals": [
        {"template_id": "tcv_01", "expression": "rank(-ts_covariance(returns, volume / (adv20 + 0.001), 60))"},
        {"template_id": "tcv_02", "expression": "rank(ts_covariance(close, vwap, 40))"},
        {"template_id": "tcv_03", "expression": "rank(-ts_covariance(returns, ts_backfill({field}, 60), 60))"},
        {"template_id": "tcv_04", "expression": "group_rank(ts_covariance(returns, returns, 60), industry)"},
        {"template_id": "tcv_05", "expression": "rank(ts_covariance(close, ts_mean(close, 20), 40))"},
    ],

    #  8. TS_PRODUCT (geometric/compounding signals)
    "ts_product_signals": [
        {"template_id": "tpr_01", "expression": "rank(-(ts_product(1 + returns, 20) - 1))"},
        {"template_id": "tpr_02", "expression": "rank(ts_product(1 + returns, 60) - ts_product(1 + returns, 20))"},
        {"template_id": "tpr_03", "expression": "rank(-(ts_product(1 + returns, 5) - 1)) * rank({field})"},
    ],
}
TEMPLATE_LIBRARY.update(V727_NEW_TEMPLATES)

# Neutralization options for new families
V727_NEUTRALIZATION = {fam: ["MARKET", "INDUSTRY", "SUBINDUSTRY", "NONE"] for fam in V727_NEW_TEMPLATES}
DATASET_NEUTRALIZATION.update({
    "delay0_open_gap_reversal": ["MARKET", "INDUSTRY", "SUBINDUSTRY", "NONE"],
    "delay0_close_vwap_dislocation": ["MARKET", "INDUSTRY", "SUBINDUSTRY", "NONE"],
    "delay0_range_position": ["MARKET", "INDUSTRY", "SUBINDUSTRY", "NONE"],
    "delay0_volume_shock": ["MARKET", "INDUSTRY", "SUBINDUSTRY", "NONE"],
    "delay0_liquidity_pressure": ["MARKET", "INDUSTRY", "SUBINDUSTRY", "NONE"],
    "delay0_options_intraday": ["MARKET", "INDUSTRY", "SUBINDUSTRY", "NONE"],
    "delay0_news_reaction": ["MARKET", "INDUSTRY", "SUBINDUSTRY", "NONE"],
    "delay0_risk_intraday": ["MARKET", "INDUSTRY", "SUBINDUSTRY", "NONE"],
})
DATASET_NEUTRALIZATION.update(V727_NEUTRALIZATION)

# v7.2: Merge research-backed mega template library (880 templates)
try:
    from research_templates import (
        RESEARCH_TEMPLATES, RESEARCH_NEUTRALIZATIONS, EWAN_ONLY_FAMILIES
    )
    TEMPLATE_LIBRARY.update(RESEARCH_TEMPLATES)
    NEUTRALIZATION_OPTIONS = RESEARCH_NEUTRALIZATIONS  # Available for generator
    DATASET_NEUTRALIZATION.update(RESEARCH_NEUTRALIZATIONS)
    _n_research = sum(len(v) for v in RESEARCH_TEMPLATES.values())
    print(f"[TEMPLATES] Merged {len(RESEARCH_TEMPLATES)} research families ({_n_research} templates)")
except ImportError:
    print("[TEMPLATES] research_templates.py not found - running without research library")

# v7.2.7-D0: Merge D=0 v727 hand-picked templates (40 templates from research brief)
try:
    from delay0_v727_templates import (
        DELAY0_V727_TEMPLATES, DELAY0_V727_NEUTRALIZATION,
        DELAY0_V727_UNIVERSE, DELAY0_V727_DECAY,
    )
    TEMPLATE_LIBRARY.update(DELAY0_V727_TEMPLATES)
    DATASET_NEUTRALIZATION.update(DELAY0_V727_NEUTRALIZATION)
    _n_d0v7 = sum(len(v) for v in DELAY0_V727_TEMPLATES.values())
    print(f"[TEMPLATES] Merged {len(DELAY0_V727_TEMPLATES)} v727-D0 families ({_n_d0v7} templates)")
except ImportError:
    print("[TEMPLATES] delay0_v727_templates.py not found")

# v7.2.7-D0: D0_ONLY_MODE - strip all non-D0 templates
# When config.D0_ONLY_MODE is True, the bot should generate ONLY d=0 alphas.
# We accomplish that by removing every family that is NOT prefixed with
# "delay0_" or "d0v7_". Generator/bot then picks only from the surviving families.
def _is_d0_family(name: str) -> bool:
    """A family is a D0 family if it's a delay0_* or d0v7_* family."""
    return name.startswith("delay0_") or name.startswith("d0v7_")

try:
    import config as _cfg
    _d0_only = getattr(_cfg, "D0_ONLY_MODE", False)
except Exception:
    _d0_only = False

if _d0_only:
    _kept = {k: v for k, v in TEMPLATE_LIBRARY.items() if _is_d0_family(k)}
    _stripped_count = len(TEMPLATE_LIBRARY) - len(_kept)
    _kept_template_count = sum(len(v) for v in _kept.values())
    TEMPLATE_LIBRARY = _kept
    print(f"[TEMPLATES] D0_ONLY_MODE - stripped {_stripped_count} non-D0 families. "
          f"Kept {len(_kept)} D0 families ({_kept_template_count} templates)")
