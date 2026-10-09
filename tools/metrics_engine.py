import os
import sys
import pandas as pd
import numpy as np

# Reconstruct pandas DataFrame from serialized dictionary
def dict_to_df(serialized_dict):
    if not serialized_dict:
        return pd.DataFrame()
    try:
        df = pd.DataFrame(serialized_dict)
        # Ensure rows are sorted if possible, columns are dates
        return df
    except Exception as e:
        print(f"[metrics_engine] Warning parsing DataFrame: {e}")
        return pd.DataFrame()

# Robust row extraction helper
def get_row_series(df, row_names):
    if df.empty:
        return None, []
    for row_name in row_names:
        for idx in df.index:
            if str(idx).strip().lower() == row_name.lower():
                row_idx = df.index.get_loc(idx)
                if isinstance(row_idx, slice):
                    row_data = df.iloc[row_idx.start]
                elif isinstance(row_idx, (list, tuple)) or (hasattr(row_idx, 'dtype') and row_idx.dtype == bool):
                    matching_indices = np.where(row_idx)[0]
                    if len(matching_indices) > 0:
                        row_data = df.iloc[matching_indices[0]]
                    else:
                        continue
                else:
                    row_data = df.iloc[row_idx]
                
                res = []
                for val in row_data:
                    if pd.isna(val):
                        res.append(None)
                    else:
                        try:
                            res.append(float(val))
                        except ValueError:
                            res.append(None)
                # Sort columns by date if they represent dates
                cols = [str(col) for col in df.columns]
                return res, cols
    return None, []

# Extract the most recent value from row names
def get_latest_value(df, row_names):
    series, dates = get_row_series(df, row_names)
    if series:
        # Columns in yfinance are typically newest first, but let's be careful.
        # Let's inspect the dates. If dates are sorted descending, index 0 is latest.
        # Typically yfinance is newest first (e.g. 2024-03-31, 2023-03-31, 2022-03-31)
        # Let's check if the first date is indeed the latest.
        if len(dates) > 1 and dates[0] < dates[-1]:
            # Ascending dates, so latest is the last element
            return series[-1]
        return series[0]
    return None

class FundamentalMetricsEngine:
    """
    Computes mathematical metrics F-01 to F-20 for a given stock
    based on raw financial statements data and broker info dictionary.
    """
    
    @staticmethod
    def calculate_all_metrics(raw_data: dict) -> dict:
        symbol = raw_data.get('symbol', 'UNKNOWN')
        info = raw_data.get('info', {}) or {}
        
        # Load serialized dataframes
        arrays = raw_data.get('financial_arrays', {}) or {}
        inc_df = dict_to_df(arrays.get('income_stmt'))
        bs_df = dict_to_df(arrays.get('balance_sheet'))
        cf_df = dict_to_df(arrays.get('cash_flow'))
        
        q_inc_df = dict_to_df(arrays.get('quarterly_income_stmt'))
        q_bs_df = dict_to_df(arrays.get('quarterly_balance_sheet'))
        q_cf_df = dict_to_df(arrays.get('quarterly_cash_flow'))

        # Fetch yfinance fallback info if raw_data contains direct LTP/Volume info
        ltp = raw_data.get('lastPrice')
        volume = raw_data.get('volume')
        ohlc = raw_data.get('ohlc', {}) or {}

        # -------------------------------------------------------------
        # F-01: Normalized Financial Statements (5Y / 12Q Series)
        # -------------------------------------------------------------
        statements_5y = {}
        statements_12q = {}
        
        # Helper to construct statement dictionary
        def extract_statement_grid(df_stmt):
            if df_stmt.empty:
                return {}
            grid = {}
            for col in df_stmt.columns:
                col_str = str(col)[:10]  # Format as YYYY-MM-DD
                grid[col_str] = {}
                for idx in df_stmt.index:
                    val = df_stmt.loc[idx, col]
                    if isinstance(val, pd.Series):
                        val = val.iloc[0]
                    grid[col_str][str(idx)] = float(val) if pd.notna(val) and not isinstance(val, str) else None
            return grid

        statements_5y['income_stmt'] = extract_statement_grid(inc_df)
        statements_5y['balance_sheet'] = extract_statement_grid(bs_df)
        statements_5y['cash_flow'] = extract_statement_grid(cf_df)
        
        statements_12q['income_stmt'] = extract_statement_grid(q_inc_df)
        statements_12q['balance_sheet'] = extract_statement_grid(q_bs_df)
        statements_12q['cash_flow'] = extract_statement_grid(q_cf_df)

        # -------------------------------------------------------------
        # F-02: Ratio analysis (ROE, ROCE, EBITDA Margin, Asset Turnover)
        # -------------------------------------------------------------
        ratios_annual = []
        if not inc_df.empty and not bs_df.empty:
            cols = list(inc_df.columns)
            for i, col in enumerate(cols):
                col_str = str(col)[:10]
                # Reconstruct matching BS column index
                # BS and Income statement might not have identical columns, so match by year/month if possible
                bs_col = None
                for c in bs_df.columns:
                    if str(c)[:7] == col_str[:7]:
                        bs_col = c
                        break
                if bs_col is None and i < len(bs_df.columns):
                    bs_col = bs_df.columns[i]
                
                if bs_col is not None:
                    try:
                        # Pull items
                        net_income = get_latest_value(inc_df[[col]], ['Net Income', 'Net Income Common Stockholders'])
                        revenue = get_latest_value(inc_df[[col]], ['Total Revenue', 'Revenue'])
                        ebitda = get_latest_value(inc_df[[col]], ['EBITDA', 'Normalized EBITDA'])
                        ebit = get_latest_value(inc_df[[col]], ['EBIT', 'Operating Income'])
                        
                        total_assets = get_latest_value(bs_df[[bs_col]], ['Total Assets'])
                        curr_liab = get_latest_value(bs_df[[bs_col]], ['Current Liabilities', 'Total Current Liabilities'])
                        equity = get_latest_value(bs_df[[bs_col]], ['Stockholders Equity', 'Total Equity Gross Minor Interest', 'Common Stock Equity'])
                        
                        roe = (net_income / equity) if net_income and equity else None
                        
                        capital_employed = (total_assets - curr_liab) if total_assets and curr_liab else None
                        roce = (ebit / capital_employed) if ebit and capital_employed and capital_employed > 0 else None
                        
                        ebitda_margin = (ebitda / revenue) if ebitda and revenue else None
                        asset_turnover = (revenue / total_assets) if revenue and total_assets else None
                        
                        ratios_annual.append({
                            'date': col_str,
                            'ROE': roe,
                            'ROCE': roce,
                            'EBITDA_Margin': ebitda_margin,
                            'Asset_Turnover': asset_turnover
                        })
                    except Exception as err:
                        print(f"[metrics_engine] Error computing ratios for {col_str}: {err}")

        # -------------------------------------------------------------
        # F-03: Valuation metrics
        # -------------------------------------------------------------
        # Try to pull standard valuation metrics or calculate from recent financials
        latest_rev = get_latest_value(inc_df, ['Total Revenue', 'Revenue'])
        latest_pat = get_latest_value(inc_df, ['Net Income', 'Net Income Common Stockholders'])
        latest_ebitda = get_latest_value(inc_df, ['EBITDA', 'Normalized EBITDA'])
        latest_equity = get_latest_value(bs_df, ['Stockholders Equity', 'Total Equity Gross Minor Interest', 'Common Stock Equity'])
        latest_debt = get_latest_value(bs_df, ['Total Debt', 'Long Term Debt'])
        latest_cash = get_latest_value(bs_df, ['Cash And Cash Equivalents', 'Cash Cash Equivalents And Short Term Investments'])
        
        cfo = get_latest_value(cf_df, ['Operating Cash Flow', 'Cash Flow From Continuing Operating Activities', 'Net Cash Provided By Operating Activities'])
        capex = get_latest_value(cf_df, ['Capital Expenditure', 'Net PPE Purchase And Sale', 'Purchase Of PPE'])
        if capex is not None:
            capex = abs(capex)
        else:
            capex = 0.0
            
        fcf = (cfo - capex) if cfo is not None else None

        # Resolve values from info or metrics
        market_cap = raw_data.get('marketCap') or (info.get('marketCap') if hasattr(info, 'get') else None)
        shares_outstanding = info.get('sharesOutstanding') or info.get('impliedSharesOutstanding') or (raw_data.get('sharesOutstanding') if hasattr(info, 'get') else None)
        
        if not market_cap and ltp and shares_outstanding:
            market_cap = ltp * shares_outstanding
        elif not shares_outstanding and market_cap and ltp and ltp > 0:
            shares_outstanding = market_cap / ltp

        pe = info.get('trailingPE') or info.get('forwardPE')
        if not pe:
            if market_cap and latest_pat and latest_pat > 0:
                pe = market_cap / latest_pat
            elif ltp and shares_outstanding and latest_pat and shares_outstanding > 0 and latest_pat > 0:
                pe = ltp / (latest_pat / shares_outstanding)
            
        pb = info.get('priceToBook')
        if not pb:
            if market_cap and latest_equity and latest_equity > 0:
                pb = market_cap / latest_equity
            elif ltp and shares_outstanding and latest_equity and shares_outstanding > 0 and latest_equity > 0:
                pb = ltp / (latest_equity / shares_outstanding)
            
        ps = info.get('priceToSalesTrailing12Months') or info.get('priceToSales')
        if not ps:
            if market_cap and latest_rev and latest_rev > 0:
                ps = market_cap / latest_rev
            elif ltp and shares_outstanding and latest_rev and shares_outstanding > 0 and latest_rev > 0:
                ps = ltp / (latest_rev / shares_outstanding)

        # EV = Market Cap + Debt - Cash
        ev = None
        if market_cap:
            debt_val = latest_debt or 0.0
            cash_val = latest_cash or 0.0
            ev = market_cap + debt_val - cash_val
            
        ev_to_ebitda = info.get('enterpriseToEbitda') or info.get('evToEbitda')
        if not ev_to_ebitda and ev and latest_ebitda and latest_ebitda > 0:
            ev_to_ebitda = ev / latest_ebitda
            
        fcf_yield = None
        if market_cap and market_cap > 0:
            if fcf is not None:
                fcf_yield = fcf / market_cap
            elif cfo is not None:
                fcf_yield = cfo / market_cap

        valuation_metrics = {
            'last_price': ltp,
            'PE': pe,
            'PB': pb,
            'PS': ps,
            'EV_EBITDA': ev_to_ebitda,
            'FCF_Yield': fcf_yield,
            'MarketCap': market_cap,
            'SharesOutstanding': shares_outstanding
        }

        # -------------------------------------------------------------
        # F-05: Revenue/Profit Growth Trends
        # -------------------------------------------------------------
        growth_trends = []
        rev_series, rev_dates = get_row_series(inc_df, ['Total Revenue', 'Revenue'])
        pat_series, pat_dates = get_row_series(inc_df, ['Net Income', 'Net Income Common Stockholders'])
        
        # Sort ascending by date to calculate growth
        if rev_series and len(rev_series) > 1:
            # Re-sort if sorted newest first
            if rev_dates[0] > rev_dates[-1]:
                rev_series = rev_series[::-1]
                pat_series = pat_series[::-1]
                rev_dates = rev_dates[::-1]
                
            for k in range(1, len(rev_series)):
                rev_yoy = None
                pat_yoy = None
                
                prev_rev = rev_series[k-1]
                curr_rev = rev_series[k]
                if prev_rev and curr_rev and prev_rev > 0:
                    rev_yoy = (curr_rev - prev_rev) / prev_rev
                    
                prev_pat = pat_series[k-1]
                curr_pat = pat_series[k]
                if prev_pat and curr_pat and prev_pat != 0:
                    pat_yoy = (curr_pat - prev_pat) / abs(prev_pat)
                    
                growth_trends.append({
                    'date': str(rev_dates[k])[:10],
                    'revenue_growth_yoy': rev_yoy,
                    'pat_growth_yoy': pat_yoy
                })

        # Calculate CAGR (Compound Annual Growth Rate)
        cagr_3y_rev = None
        cagr_3y_pat = None
        if rev_series and len(rev_series) >= 4:
            # 3 year CAGR requires 4 consecutive annual data points
            start_rev = rev_series[-4]
            end_rev = rev_series[-1]
            if start_rev and end_rev and start_rev > 0 and end_rev > 0:
                cagr_3y_rev = (end_rev / start_rev) ** (1/3) - 1
                
            start_pat = pat_series[-4]
            end_pat = pat_series[-1]
            if start_pat and end_pat and start_pat > 0 and end_pat > 0:
                cagr_3y_pat = (end_pat / start_pat) ** (1/3) - 1

        # F-05 extension: growth acceleration (2nd-derivative of revenue growth)
        growth_acceleration = None
        velocity_tag = "STEADY"
        if len(growth_trends) >= 2:
            last_g = growth_trends[-1].get('revenue_growth_yoy')
            prev_g = growth_trends[-2].get('revenue_growth_yoy')
            if last_g is not None and prev_g is not None:
                growth_acceleration = last_g - prev_g
                if growth_acceleration > 0.02:
                    velocity_tag = "ACCELERATING"
                elif growth_acceleration < -0.02:
                    velocity_tag = "DECELERATING"

        growth_summary = {
            'growth_trends': growth_trends,
            'cagr_3y_revenue': cagr_3y_rev,
            'cagr_3y_pat': cagr_3y_pat,
            'revenue_growth_acceleration': growth_acceleration,
            'growth_velocity_tag': velocity_tag
        }

        # -------------------------------------------------------------
        # F-06: Margin Analysis
        # -------------------------------------------------------------
        margins_annual = []
        if not inc_df.empty:
            cols = list(inc_df.columns)
            # Ensure chronological order (oldest first) for trending
            if len(cols) > 1 and str(cols[0]) > str(cols[-1]):
                cols = cols[::-1]
                
            for col in cols:
                col_str = str(col)[:10]
                try:
                    revenue = get_latest_value(inc_df[[col]], ['Total Revenue', 'Revenue'])
                    gross_profit = get_latest_value(inc_df[[col]], ['Gross Profit'])
                    ebitda = get_latest_value(inc_df[[col]], ['EBITDA', 'Normalized EBITDA'])
                    ebit = get_latest_value(inc_df[[col]], ['EBIT', 'Operating Income'])
                    pat = get_latest_value(inc_df[[col]], ['Net Income', 'Net Income Common Stockholders'])
                    
                    gross_margin = (gross_profit / revenue) if gross_profit and revenue else None
                    ebitda_margin = (ebitda / revenue) if ebitda and revenue else None
                    ebit_margin = (ebit / revenue) if ebit and revenue else None
                    pat_margin = (pat / revenue) if pat and revenue else None
                    
                    margins_annual.append({
                        'date': col_str,
                        'gross_margin': gross_margin,
                        'ebitda_margin': ebitda_margin,
                        'ebit_margin': ebit_margin,
                        'pat_margin': pat_margin
                    })
                except Exception as err:
                    print(f"[metrics_engine] Error computing margins for {col_str}: {err}")

        # Margin status tags
        margin_status = "STABLE"
        if len(margins_annual) >= 2:
            latest_ebit_m = margins_annual[-1].get('ebit_margin')
            prev_ebit_m = margins_annual[-2].get('ebit_margin')
            if latest_ebit_m is not None and prev_ebit_m is not None:
                diff = latest_ebit_m - prev_ebit_m
                if diff > 0.01:
                    margin_status = "IMPROVING"
                elif diff < -0.01:
                    margin_status = "DETERIORATING"

        margin_analysis = {
            'margins_annual': margins_annual,
            'margin_status_tag': margin_status
        }

        # -------------------------------------------------------------
        # F-08: Debt & Solvency analysis
        # -------------------------------------------------------------
        debt_to_equity = None
        net_debt_to_ebitda = None
        interest_coverage = None
        
        # An unavailable debt / cash figure is UNKNOWN, never zero: the ratio is withheld (None) instead of being computed on 0.
        if latest_equity and latest_equity > 0 and latest_debt is not None:
            debt_to_equity = latest_debt / latest_equity
            
        if latest_ebitda and latest_ebitda > 0 and latest_debt is not None and latest_cash is not None:
            net_debt = latest_debt - latest_cash
            net_debt_to_ebitda = net_debt / latest_ebitda
            
        interest_exp = get_latest_value(inc_df, ['Interest Expense', 'Interest Expense Value'])
        ebit_val = get_latest_value(inc_df, ['EBIT', 'Operating Income'])
        if interest_exp and interest_exp > 0 and ebit_val:
            interest_coverage = ebit_val / interest_exp
            
        solvency_metrics = {
            'debt_to_equity': debt_to_equity,
            'net_debt_to_ebitda': net_debt_to_ebitda,
            'interest_coverage': interest_coverage,
            'total_debt': latest_debt,
            'cash_equivalents': latest_cash
        }

        # -------------------------------------------------------------
        # F-09: Cash Flow Conversion
        # -------------------------------------------------------------
        cfo_to_pat = None
        if latest_pat and latest_pat != 0 and cfo:
            cfo_to_pat = cfo / latest_pat
            
        cash_flow_conversion = {
            'CFO': cfo,
            'Capex': capex,
            'FCF': fcf,
            'CFO_to_PAT': cfo_to_pat
        }

        # -------------------------------------------------------------
        # F-10, F-11, F-12: Ownership & Promoter Pledge Metrics
        # Real data sourced from NSE (tools/shareholding_scraper). yfinance is a
        # secondary fallback. Nothing here is fabricated: when a figure cannot be
        # sourced it is left as None and flagged so the UI shows "awaiting filing"
        # rather than a placeholder number.
        # -------------------------------------------------------------
        shareholding = raw_data.get('shareholding', {}) or {}
        own_data = raw_data.get('ownership_metrics', {}) or {}

        held_insiders = info.get('heldPercentInsiders') or own_data.get('F-10_heldPercentInsiders') or own_data.get('heldPercentInsiders')
        promoter_pledges = info.get('promoterPledges') or own_data.get('F-11_promoterPledges') or own_data.get('promoterPledges')
        held_institutions = info.get('heldPercentInstitutions') or own_data.get('F-12_heldPercentInstitutions') or own_data.get('heldPercentInstitutions')

        # Normalize any yfinance 0-1 fractions to a 0-100 percentage scale
        if held_insiders is not None and held_insiders <= 1.0:
            held_insiders *= 100.0
        if promoter_pledges is not None and promoter_pledges <= 1.0:
            promoter_pledges *= 100.0
        if held_institutions is not None and held_institutions <= 1.0:
            held_institutions *= 100.0

        # Prefer the real NSE figures; fall back to yfinance; else None (not faked)
        real_promoter = shareholding.get('promoter_holding_pct')
        real_pledge = shareholding.get('promoter_pledge_pct')
        real_inst = shareholding.get('institutional_holding_pct')
        real_public = shareholding.get('public_holding_pct')

        promoter_stake = real_promoter if real_promoter is not None else held_insiders
        promoter_pledge = real_pledge if real_pledge is not None else promoter_pledges
        fii_dii_stake = real_inst if real_inst is not None else held_institutions

        public_stake = real_public
        if public_stake is None and promoter_stake is not None:
            public_stake = round(max(100.0 - promoter_stake - (fii_dii_stake or 0.0), 0.0), 2)

        ownership_metrics = {
            'promoter_stake': promoter_stake,
            'promoter_pledge_of_stake': promoter_pledge,
            'fii_dii_stake': fii_dii_stake,
            'public_stake': public_stake,
            # provenance + freshness for the UI
            'data_source': shareholding.get('source', 'fallback'),
            'as_of_quarter': shareholding.get('as_of_quarter'),
            'pledge_status': shareholding.get('pledge_status', 'unavailable'),
            'num_shares_pledged': shareholding.get('num_shares_pledged'),
            # F-10/F-12: separate FII & DII stakes (REAL, Screener)
            'fii_stake': shareholding.get('fii_stake'),
            'dii_stake': shareholding.get('dii_stake'),
            # REAL multi-quarter history for ownership / promoter / FII-DII trends
            'ownership_history': shareholding.get('ownership_history', []),
            # F-12: real market-wide FII/DII net flows (Rs Cr, latest session)
            'market_fii_dii': shareholding.get('market_fii_dii', []),
            'fund_flows': shareholding.get('fund_flows', []),
            'concall_links': shareholding.get('concall_links', []),
        }

        # -------------------------------------------------------------
        # F-13: Quarterly Results (YoY & QoQ Trends)
        # -------------------------------------------------------------
        quarterly_analysis = []
        if not q_inc_df.empty:
            q_cols = list(q_inc_df.columns)
            # Re-sort to chronological oldest first
            if len(q_cols) > 1 and str(q_cols[0]) > str(q_cols[-1]):
                q_cols = q_cols[::-1]
                
            for j in range(len(q_cols)):
                col_str = str(q_cols[j])[:10]
                try:
                    rev_q = get_latest_value(q_inc_df[[q_cols[j]]], ['Total Revenue', 'Revenue'])
                    pat_q = get_latest_value(q_inc_df[[q_cols[j]]], ['Net Income', 'Net Income Common Stockholders'])
                    ebit_q = get_latest_value(q_inc_df[[q_cols[j]]], ['EBIT', 'Operating Income'])
                    
                    qoq_growth = None
                    if j > 0:
                        prev_rev_q = get_latest_value(q_inc_df[[q_cols[j-1]]], ['Total Revenue', 'Revenue'])
                        if prev_rev_q and rev_q and prev_rev_q > 0:
                            qoq_growth = (rev_q - prev_rev_q) / prev_rev_q
                            
                    yoy_growth = None
                    if j >= 4:
                        prev_yoy_rev_q = get_latest_value(q_inc_df[[q_cols[j-4]]], ['Total Revenue', 'Revenue'])
                        if prev_yoy_rev_q and rev_q and prev_yoy_rev_q > 0:
                            yoy_growth = (rev_q - prev_yoy_rev_q) / prev_yoy_rev_q
                            
                    quarterly_analysis.append({
                        'quarter': col_str,
                        'revenue': rev_q,
                        'pat': pat_q,
                        'ebit_margin': (ebit_q / rev_q) if ebit_q and rev_q else None,
                        'qoq_revenue_growth': qoq_growth,
                        'yoy_revenue_growth': yoy_growth
                    })
                except Exception as err:
                    print(f"[metrics_engine] Error in quarterly slice {col_str}: {err}")

        # -------------------------------------------------------------
        # F-13 (extension): Quarterly results beat/miss + PEAD signal
        # -------------------------------------------------------------
        results_signal = {}
        if len(quarterly_analysis) >= 1:
            latest_q = quarterly_analysis[-1]
            year_ago_q = quarterly_analysis[-5] if len(quarterly_analysis) >= 5 else None

            pat_yoy = None
            if year_ago_q is not None:
                curr_pat = latest_q.get('pat')
                prev_pat = year_ago_q.get('pat')
                if curr_pat is not None and prev_pat not in (None, 0):
                    pat_yoy = (curr_pat - prev_pat) / abs(prev_pat)

            rev_yoy = latest_q.get('yoy_revenue_growth')
            op_margin_curr = latest_q.get('ebit_margin')
            op_margin_prev = year_ago_q.get('ebit_margin') if year_ago_q else None

            try:
                from tools.pead_engine import calculate_pead_score
                pead = calculate_pead_score({
                    'net_profit_growth_yoy': (pat_yoy * 100) if pat_yoy is not None else 0,
                    'revenue_growth_yoy': (rev_yoy * 100) if rev_yoy is not None else 0,
                    'op_margin_current': (op_margin_curr * 100) if op_margin_curr is not None else 0,
                    'op_margin_yoy': (op_margin_prev * 100) if op_margin_prev is not None else 0,
                })
            except Exception as pead_err:
                print(f"[metrics_engine] PEAD scoring failed: {pead_err}")
                pead = {'pead_score': 0, 'action_tag': 'REJECT'}

            # Beat / Inline / Miss judged on YoY profit momentum
            beat_miss = "INLINE"
            if pat_yoy is not None:
                if pat_yoy > 0.10:
                    beat_miss = "BEAT"
                elif pat_yoy < 0:
                    beat_miss = "MISS"

            results_signal = {
                'latest_quarter': latest_q.get('quarter'),
                'revenue_yoy': rev_yoy,
                'pat_yoy': pat_yoy,
                'op_margin_current': op_margin_curr,
                'op_margin_year_ago': op_margin_prev,
                'beat_miss': beat_miss,
                'pead_score': pead.get('pead_score', 0),
                'action_tag': pead.get('action_tag', 'REJECT')
            }

        # -------------------------------------------------------------
        # F-18: Intrinsic Value / Reverse DCF Sensitivity
        # -------------------------------------------------------------
        base_fcf = fcf if fcf and fcf > 0 else (latest_pat * 0.8 if latest_pat and latest_pat > 0 else (market_cap * 0.04 if market_cap else 100000000))
        
        # Sensitivity settings
        growth_rates = [0.05, 0.08, 0.10, 0.12, 0.15]
        discount_rates = [0.09, 0.10, 0.11, 0.12, 0.13]
        
        # Convert an enterprise DCF value into a per-share figure. Robust to a
        # missing price feed or share count (returns None instead of crashing).
        def _dcf_per_share(value, ltp_multiplier=1.0):
            if shares_outstanding and shares_outstanding > 0:
                return value / shares_outstanding
            if market_cap and market_cap > 0 and ltp is not None:
                return ltp * (value / market_cap)
            if ltp is not None:
                return ltp * ltp_multiplier
            return None

        dcf_matrix = {}
        for r in discount_rates:
            dcf_matrix[f"{int(r*100)}%"] = {}
            for g in growth_rates:
                val = calculate_dcf_value(base_fcf, g, r, 0.045)
                dcf_matrix[f"{int(r*100)}%"][f"{int(g*100)}%"] = _dcf_per_share(val)

        # Core DCF scenarios (Bull / Base / Bear)
        dcf_scenarios = {
            'Bear_Value': _dcf_per_share(calculate_dcf_value(base_fcf, 0.05, 0.11, 0.04), 0.7),
            'Base_Value': _dcf_per_share(calculate_dcf_value(base_fcf, 0.10, 0.11, 0.04), 1.0),
            'Bull_Value': _dcf_per_share(calculate_dcf_value(base_fcf, 0.15, 0.11, 0.04), 1.3),
            'Discount_Rate': 0.11,
            'Terminal_Growth_Rate': 0.04,
            'Base_FCF': base_fcf
        }

        # -------------------------------------------------------------
        # F-19: Business Quality Score (Weighted Composite Score)
        # -------------------------------------------------------------
        # Return 0-100 indicators based on multiple conditions
        bq_score = 0
        rules = []
        
        # Rule 1: ROCE (weight 20)
        latest_roce = ratios_annual[-1].get('ROCE') if ratios_annual else None
        if latest_roce is not None:
            if latest_roce > 0.20:
                bq_score += 20
                rules.append("High ROCE (>20%): +20")
            elif latest_roce > 0.15:
                bq_score += 15
                rules.append("Healthy ROCE (>15%): +15")
            elif latest_roce > 0.10:
                bq_score += 10
                rules.append("Moderate ROCE (>10%): +10")
            else:
                rules.append("Low ROCE (<10%): +0")
        else:
            rules.append("ROCE Unavailable: +0")
            
        # Rule 2: Profit margins (weight 20)
        latest_ebit_margin = margins_annual[-1].get('ebit_margin') if margins_annual else None
        if latest_ebit_margin is not None:
            if latest_ebit_margin > 0.20:
                bq_score += 20
                rules.append("High Operating Margin (>20%): +20")
            elif latest_ebit_margin > 0.12:
                bq_score += 15
                rules.append("Healthy Operating Margin (>12%): +15")
            elif latest_ebit_margin > 0.08:
                bq_score += 10
                rules.append("Moderate Operating Margin (>8%): +10")
            else:
                rules.append("Low Operating Margin (<8%): +0")
        else:
            rules.append("Operating Margin Unavailable: +0")

        # Rule 3: Debt Leverage (weight 20)
        if debt_to_equity is not None:
            if debt_to_equity < 0.3:
                bq_score += 20
                rules.append("Very Low Debt/Equity (<0.3): +20")
            elif debt_to_equity < 0.7:
                bq_score += 15
                rules.append("Low Debt/Equity (<0.7): +15")
            elif debt_to_equity < 1.2:
                bq_score += 10
                rules.append("Moderate Debt/Equity (<1.2): +10")
            else:
                rules.append("High Debt/Equity (>1.2): +0")
        else:
            bq_score += 15
            rules.append("Debt/Equity Unavailable (Assumed low debt): +15")

        # Rule 4: Cash Flow Quality (CFO/PAT) (weight 20)
        if cfo_to_pat is not None:
            if cfo_to_pat > 1.0:
                bq_score += 20
                rules.append("Excellent CFO/PAT conversion (>1.0): +20")
            elif cfo_to_pat > 0.8:
                bq_score += 15
                rules.append("Good CFO/PAT conversion (>0.8): +15")
            elif cfo_to_pat > 0.5:
                bq_score += 10
                rules.append("Moderate CFO/PAT conversion (>0.5): +10")
            else:
                rules.append("Poor CFO/PAT conversion (<0.5): +0")
        else:
            rules.append("CFO/PAT Unavailable: +0")

        # Rule 5: Growth Trends (YoY Net Profit growth) (weight 20)
        latest_pat_growth = growth_trends[-1].get('pat_growth_yoy') if growth_trends else None
        if latest_pat_growth is not None:
            if latest_pat_growth > 0.15:
                bq_score += 20
                rules.append("High Profit Growth (>15% YoY): +20")
            elif latest_pat_growth > 0.05:
                bq_score += 15
                rules.append("Moderate Profit Growth (>5% YoY): +15")
            elif latest_pat_growth > -0.05:
                bq_score += 10
                rules.append("Stable Profit Growth (+/-5% YoY): +10")
            else:
                rules.append("Deteriorating Profit Growth (<-5% YoY): +0")
        else:
            rules.append("Growth Trend Unavailable: +0")

        business_quality = {
            'composite_score': bq_score,
            'scoring_rationale_chips': rules
        }

        # -------------------------------------------------------------
        # Aggregate Output Payload
        # -------------------------------------------------------------
        return {
            'symbol': symbol,
            # PROVENANCE: this payload is the legacy research-report engine computed from third-party statement data
            # (yfinance / Angel / Screener scrape), NOT from the filed Annual Report. Its definitions (closing balances,
            # provider 'EBIT'/'Total Debt' fields) intentionally differ from the audited 68-ratio engine (tools/ratio_contract.py).
            '_engine': {'name': 'legacy_research_report', 'data_source': 'third_party_statements',
                        'audited_ratio_engine': 'tools/ratio_contract.py (Quantitative Analysis, 68 ratios)'},
            'F-01_Financial_Statements': {
                'annual': statements_5y,
                'quarterly': statements_12q
            },
            'F-02_Ratio_Analysis': ratios_annual,
            'F-03_Valuation_Metrics': valuation_metrics,
            'F-05_Growth_Summary': growth_summary,
            'F-06_Margin_Analysis': margin_analysis,
            'F-08_Solvency_Metrics': solvency_metrics,
            'F-09_Cash_Flow_Conversion': cash_flow_conversion,
            'F-10_F-11_F-12_Ownership': ownership_metrics,
            'F-13_Quarterly_Analysis': quarterly_analysis,
            'F-13_Results_Signal': results_signal,
            'F-18_Reverse_DCF': {
                'scenarios': dcf_scenarios,
                'sensitivity_matrix': dcf_matrix
            },
            'F-19_Business_Quality': business_quality
        }

def calculate_dcf_value(fcf, growth_rate, discount_rate, terminal_growth_rate, terminal_years=10):
    if fcf is None or fcf <= 0:
        return 0.0
    pv_fcf = 0.0
    current_fcf = fcf
    for year in range(1, terminal_years + 1):
        current_fcf *= (1 + growth_rate)
        pv_fcf += current_fcf / ((1 + discount_rate) ** year)
    
    # Terminal Value
    terminal_value = (current_fcf * (1 + terminal_growth_rate)) / (discount_rate - terminal_growth_rate)
    pv_terminal_value = terminal_value / ((1 + discount_rate) ** terminal_years)
    
    return pv_fcf + pv_terminal_value

if __name__ == '__main__':
    # Local check script
    import json
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    print("Testing FundamentalMetricsEngine with fallback info...")
    from tools.angel_scraper import AngelDataScraper
    scraper = AngelDataScraper()
    raw = scraper.fetch_fundamental_payload('INFY')
    metrics = FundamentalMetricsEngine.calculate_all_metrics(raw)
    print("\nCalculated composite score:", metrics.get('F-19_Business_Quality', {}).get('composite_score'))
    print("DCF base scenarios:", metrics.get('F-18_Reverse_DCF', {}).get('scenarios'))
