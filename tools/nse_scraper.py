import os
import sys
import json

# Standard path fix to run the script directly from this directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.initialize_kite import get_authenticated_client

class ZerodhaDataIngestion:
    """
    Handles data ingestion from Zerodha Kite Connect v3.
    """
    def __init__(self):
        try:
            self.kite = get_authenticated_client()
            self._load_nse_instruments()
        except Exception as e:
            print(f"Error during ZerodhaDataIngestion initialization: {e}")
            raise e

    def _load_nse_instruments(self):
        """
        Syncs active symbols by calling self.kite.instruments("NSE")
        and maps symbols (like 'INFY') to their internal numerical instrument tokens.
        """
        try:
            print("Syncing active NSE instruments from Zerodha...")
            instruments = self.kite.instruments("NSE")
            self.symbol_to_token = {}
            for inst in instruments:
                tradingsymbol = inst.get('tradingsymbol')
                token = inst.get('instrument_token')
                if tradingsymbol and token:
                    self.symbol_to_token[tradingsymbol.upper()] = token
            print(f"Sync complete. Successfully mapped {len(self.symbol_to_token)} active symbols.")
        except Exception as e:
            print(f"Error syncing NSE instruments: {e}")
            self.symbol_to_token = {}

    def fetch_fundamental_payload(self, symbol):
        """
        Cleans the symbol, retrieves its instrument token, requests quote data,
        and constructs a structured payload dictionary matching downstream keys.
        """
        try:
            # Clean symbol (uppercase, strip whitespaces, remove '.NS' suffix)
            cleaned_symbol = symbol.strip().upper()
            if cleaned_symbol.endswith('.NS'):
                cleaned_symbol = cleaned_symbol[:-3]

            token_id = self.symbol_to_token.get(cleaned_symbol)
            if not token_id:
                raise ValueError(f"Instrument token not found for symbol: {cleaned_symbol}")

            print(f"Fetching quote for {cleaned_symbol} (Token ID: {token_id})...")
            quote_res = self.kite.quote(token_id)
            
            if not quote_res:
                raise ValueError(f"No quote data returned for token: {token_id}")

            # Extract quote data (handle string, integer, or EXCHANGE:SYMBOL key formats)
            data = None
            for key in [token_id, str(token_id), f"NSE:{cleaned_symbol}"]:
                if key in quote_res:
                    data = quote_res[key]
                    break
            if not data:
                data = list(quote_res.values())[0]

            last_price = data.get('last_price')
            volume = data.get('volume')
            ohlc = data.get('ohlc')  # Contains open, high, low, close

            # Structure payload for math engine & orchestrator compatibility
            payload = {
                'symbol': cleaned_symbol,
                'companyName': None,  # Legacy field placeholder
                'lastPrice': last_price,
                'last_price': last_price,
                'volume': volume,
                'ohlc': ohlc,
                'pdSectorInd': None,  # Legacy field placeholder
                'pdSectorPe': None,   # Legacy field placeholder
                'ownership_metrics': None  # Temporary placeholder for downstream stability
            }
            return payload

        except Exception as e:
            print(f"Error executing fetch_fundamental_payload for '{symbol}': {e}")
            # Return a defensive fallback dictionary to prevent downstream pipeline crashes
            return {
                'symbol': symbol,
                'companyName': None,
                'lastPrice': None,
                'last_price': None,
                'volume': None,
                'ohlc': None,
                'pdSectorInd': None,
                'pdSectorPe': None,
                'ownership_metrics': None,
                'error': str(e)
            }

if __name__ == '__main__':
    try:
        print("Starting test execution block...")
        ingestion = ZerodhaDataIngestion()
        
        test_symbol = 'INFY'
        print(f"\nRunning fetch_fundamental_payload for '{test_symbol}'...")
        payload = ingestion.fetch_fundamental_payload(test_symbol)
        
        print("\nResult Payload:")
        print(json.dumps(payload, indent=4))
    except Exception as e:
        print(f"\nExecution failed: {e}")
