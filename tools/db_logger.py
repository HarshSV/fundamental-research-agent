import os
import csv
from datetime import datetime

class StockDatabaseLogger:
    """
    Handles logging stock analysis parameters to the user's custom database
    file 'exports_my_stocks.csv' in the workspace root directory.
    """
    
    FILE_NAME = "exports_my_stocks.csv"
    HEADERS = [
        "Timestamp", "Symbol", "Company Name", "Price", "Quality Score", 
        "PE Ratio", "PB Ratio", "PS Ratio", "EV/EBITDA", "FCF Yield", 
        "Debt to Equity", "Interest Coverage", "Forensic Risk", "Moat Status", "Verdict"
    ]

    @classmethod
    def log_research(cls, state_data: dict):
        """
        Extracts metrics from state_data and appends a row to the CSV database.
        """
        try:
            # 1. Extract values dynamically
            calc = state_data.get("calculated_metrics", {}) or {}
            val = calc.get("F-03_Valuation_Metrics", {}) or {}
            solv = calc.get("F-08_Solvency_Metrics", {}) or {}
            qual = state_data.get("qualitative_analysis", {}) or {}
            parsed_json = qual.get("parsed_json", {}) or {}
            
            f16 = parsed_json.get("F-16", {}) or {}
            f20 = parsed_json.get("F-20", {}) or {}

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            symbol = state_data.get("symbol", "UNKNOWN")
            company_name = calc.get("company_name") or symbol
            
            price = val.get("last_price")
            quality_score = state_data.get("business_score", 0)
            
            pe = val.get("PE")
            pb = val.get("PB")
            ps = val.get("PS")
            ev_ebitda = val.get("EV_EBITDA")
            
            # Format FCF Yield as percentage if present
            fcf_yield = val.get("FCF_Yield")
            if fcf_yield is not None:
                try:
                    fcf_yield = f"{float(fcf_yield) * 100:.2f}%"
                except:
                    pass
            
            debt_to_equity = solv.get("debt_to_equity")
            interest_coverage = solv.get("interest_coverage")
            
            forensic_risk = f16.get("risk_level", "Low")
            moat_status = f20.get("moat_strength", "None")
            verdict = state_data.get("verdict", "PENDING")

            # Helper to format floats safely
            def clean_float(v):
                if v is None or v == "":
                    return "N/A"
                try:
                    return f"{float(v):.2f}"
                except:
                    return str(v)

            row_data = [
                timestamp,
                symbol,
                company_name,
                clean_float(price),
                str(quality_score),
                clean_float(pe),
                clean_float(pb),
                clean_float(ps),
                clean_float(ev_ebitda),
                clean_float(fcf_yield) if fcf_yield is not None else "N/A",
                clean_float(debt_to_equity),
                clean_float(interest_coverage),
                str(forensic_risk),
                str(moat_status),
                str(verdict)
            ]

            # 2. Check if file exists, write header if new
            file_exists = os.path.exists(cls.FILE_NAME)
            
            # Open file in append mode with newline='' for clean windows line endings
            with open(cls.FILE_NAME, mode="a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if not file_exists:
                    print(f"[Database] Creating new database file: {cls.FILE_NAME}")
                    writer.writerow(cls.HEADERS)
                
                writer.writerow(row_data)
                print(f"[Database] Successfully appended search log for {symbol} to {cls.FILE_NAME}")

        except Exception as e:
            print(f"[Database Error] Failed to log stock research to CSV: {e}")

if __name__ == "__main__":
    # Local check run
    test_state = {
        "symbol": "INFY",
        "business_score": 85,
        "verdict": "STRUCTURAL_ANALYSIS_COMPLETE",
        "calculated_metrics": {
            "company_name": "Infosys Limited",
            "F-03_Valuation_Metrics": {
                "last_price": 1600.0,
                "PE": 25.0,
                "PB": 8.5,
                "PS": 5.2,
                "EV_EBITDA": 18.0,
                "FCF_Yield": 0.045
            },
            "F-08_Solvency_Metrics": {
                "debt_to_equity": 0.1,
                "interest_coverage": 45.0
            }
        },
        "qualitative_analysis": {
            "parsed_json": {
                "F-16": {"risk_level": "Low"},
                "F-20": {"moat_strength": "Wide"}
            }
        }
    }
    print("Testing StockDatabaseLogger...")
    StockDatabaseLogger.log_research(test_state)
