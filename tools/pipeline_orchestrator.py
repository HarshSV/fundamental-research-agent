import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import yfinance as yf

def compute_roce(ticker):
    """Attempt to compute an approximate ROCE from financial statements."""
    try:
        bs = ticker.balance_sheet
        inc = ticker.income_stmt
        
        if bs.empty or inc.empty:
            return None
            
        current_bs = bs.iloc[:, 0]
        current_inc = inc.iloc[:, 0]
        
        ebit = current_inc.get('EBIT', current_inc.get('Operating Income'))
        total_assets = current_bs.get('Total Assets')
        current_liabilities = current_bs.get('Current Liabilities')
        
        if ebit and total_assets and current_liabilities:
            capital_employed = total_assets - current_liabilities
            if capital_employed > 0:
                return float(ebit / capital_employed)
    except:
        pass
    return None

def run_stock_pipeline(symbol):
    try:
        # Standardize symbol for NSE
        symbol_ns = symbol.upper() + '.NS' if not symbol.endswith('.NS') else symbol.upper()
        ticker = yf.Ticker(symbol_ns)
        info = ticker.info
        
        results = {'symbol': symbol.upper()}
        
        # 1. F-01/F-05/F-13: Revenue and Net Income YoY growth
        net_profit_growth_yoy = None
        revenue_growth_yoy = None
        try:
            q_inc = ticker.quarterly_income_stmt
            if not q_inc.empty and q_inc.shape[1] >= 5:
                curr_q = q_inc.iloc[:, 0]
                yoy_q = q_inc.iloc[:, 4]
                
                ni_curr = curr_q.get('Net Income', 0)
                ni_yoy = yoy_q.get('Net Income', 0)
                if ni_yoy:
                    net_profit_growth_yoy = float(((ni_curr - ni_yoy) / abs(ni_yoy)) * 100)
                    
                rev_curr = curr_q.get('Total Revenue', 0)
                rev_yoy = yoy_q.get('Total Revenue', 0)
                if rev_yoy:
                    revenue_growth_yoy = float(((rev_curr - rev_yoy) / abs(rev_yoy)) * 100)
        except Exception:
            pass
            
        results['F-01_F-05_F-13_Trend'] = {
            'net_profit_growth_yoy': net_profit_growth_yoy,
            'revenue_growth_yoy': revenue_growth_yoy
        }
        
        # 2. F-02/F-06: Ratio & Margin Analysis
        gross_margin = info.get('grossMargins')
        op_margin = info.get('operatingMargins')
        profit_margin = info.get('profitMargins')
        results['F-02_F-06_Margins'] = {
            'grossMargins': gross_margin,
            'operatingMargins': op_margin,
            'profitMargins': profit_margin
        }
        
        # 3. F-03: Valuation Metrics
        trailing_pe = info.get('trailingPE')
        price_to_book = info.get('priceToBook')
        price_to_sales = info.get('priceToSalesTrailing12Months')
        ev_to_ebitda = info.get('enterpriseToEbitda')
        results['F-03_Valuation'] = {
            'trailingPE': trailing_pe,
            'priceToBook': price_to_book,
            'priceToSalesTrailing12Months': price_to_sales,
            'enterpriseToEbitda': ev_to_ebitda
        }
        
        # 4. F-07: Return Ratios
        roe = info.get('returnOnEquity')
        roce = compute_roce(ticker)
        results['F-07_Return_Ratios'] = {
            'returnOnEquity': roe,
            'ROCE': roce
        }
        
        # 5. F-08: Debt Analysis
        debt_to_equity = info.get('debtToEquity')
        results['F-08_Debt'] = {
            'debtToEquity': debt_to_equity
        }
        
        # 6. F-19: Business Quality Scoring
        bq_score = 0
        
        # Positive profit growth (+20)
        if net_profit_growth_yoy is not None and net_profit_growth_yoy > 0:
            bq_score += 20
            
        # Operating margin > 15% (+20)
        if op_margin is not None and op_margin > 0.15:
            bq_score += 20
            
        # Trailing PE < 25 (+20)
        if trailing_pe is not None and trailing_pe > 0 and trailing_pe < 25:
            bq_score += 20
            
        # ROE > 15% (+20)
        if roe is not None and roe > 0.15:
            bq_score += 20
            
        # Debt-to-Equity < 1 (+20)
        # yfinance typically returns debtToEquity as a percentage (e.g. 45 means 45%)
        # So a ratio < 1 is equivalent to debtToEquity < 100 in yfinance convention
        if debt_to_equity is not None and debt_to_equity < 100:
            bq_score += 20
            
        results['F-19_Business_Quality'] = {
            'composite_score': bq_score
        }
        
        # 7. Ownership Metrics (F-10, F-11, F-12)
        held_percent_insiders = info.get('heldPercentInsiders')
        held_percent_institutions = info.get('heldPercentInstitutions')
        
        # yfinance info rarely contains explicit pledge metrics, gracefully defaulting to None
        promoter_pledges = info.get('promoterPledges', None)
        
        results['ownership_metrics'] = {
            'F-10_heldPercentInsiders': held_percent_insiders,
            'F-11_promoterPledges': promoter_pledges,
            'F-12_heldPercentInstitutions': held_percent_institutions
        }
        
        return results
    except Exception as e:
        return {'error': f'Pipeline failed: {str(e)}'}

if __name__ == '__main__':
    print("Running Full Comprehensive Fundamental Pipeline for 'INFY'...\n")
    result = run_stock_pipeline('INFY')
    print(json.dumps(result, indent=4))
