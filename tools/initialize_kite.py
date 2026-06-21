import os
import json
import datetime
from dotenv import load_dotenv
from kiteconnect import KiteConnect

def get_authenticated_client():
    """
    Initializes and returns an authenticated KiteConnect client.
    Uses daily token caching to avoid repeated login prompts.
    """
    # Load .env variables from workspace root
    load_dotenv()
    
    API_KEY = os.getenv('KITE_API_KEY')
    API_SECRET = os.getenv('KITE_API_SECRET')
    
    if not API_KEY or not API_SECRET or API_KEY == "your_api_key_here" or API_SECRET == "your_api_secret_here":
        raise ValueError("Please configure KITE_API_KEY and KITE_API_SECRET in your root .env file.")
        
    kite = KiteConnect(api_key=API_KEY)
    
    # Path for cached token
    cache_filename = 'token_cache.json'
    script_dir = os.path.dirname(os.path.abspath(__file__))
    script_dir_cache = os.path.join(script_dir, cache_filename)
    
    # Look for cache in current directory first, fall back to script's directory
    cache_path = cache_filename if os.path.exists(cache_filename) else script_dir_cache
    
    access_token = None
    current_date = datetime.date.today().isoformat()
    
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r') as f:
                cache_data = json.load(f)
            
            # Ensure the token belongs to today's date
            if cache_data.get('date') == current_date and cache_data.get('access_token'):
                access_token = cache_data['access_token']
                print("Found active access token cached for today.")
        except Exception as e:
            print(f"Warning: Could not read token cache: {e}")
            
    if access_token:
        try:
            kite.set_access_token(access_token)
            return kite
        except Exception as e:
            print(f"Warning: Failed to set access token from cache: {e}. Re-authenticating...")
            
    # Trigger login flow if cache is missing, expired, or invalid
    print(f"Please login here to generate your request token:\n{kite.login_url()}\n")
    request_token = input("Enter the request token from redirect URL: ").strip()
    
    try:
        session = kite.generate_session(request_token, secret=API_SECRET)
        access_token = session.get('access_token')
        if not access_token:
            raise ValueError("No access_token found in session response.")
            
        kite.set_access_token(access_token)
        
        # Cache token for the day
        cache_data = {
            'access_token': access_token,
            'date': current_date
        }
        with open(cache_path, 'w') as f:
            json.dump(cache_data, f, indent=4)
        print("Kite authenticated and token cached successfully.")
        return kite
    except Exception as e:
        print(f"Authentication failed: {e}")
        raise e
