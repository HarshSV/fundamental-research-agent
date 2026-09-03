import os
import json
import datetime
import webbrowser
import requests
from urllib.parse import urlencode, urlparse, parse_qs
from dotenv import load_dotenv

AUTH_URL = "https://api.upstox.com/v2/login/authorization/dialog"
TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"
BASE_URL = "https://api.upstox.com/v2"


def _login_url(api_key, redirect_uri):
    params = {
        "response_type": "code",
        "client_id": api_key,
        "redirect_uri": redirect_uri,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def get_authenticated_client():
    """
    Returns an authenticated requests.Session with the Upstox bearer token set,
    plus the resolved base URL. Uses daily token caching to avoid repeated login
    prompts, mirroring tools/initialize_kite.py's pattern.
    """
    load_dotenv()

    api_key = os.getenv("UPSTOX_API_KEY")
    api_secret = os.getenv("UPSTOX_API_SECRET")
    redirect_uri = os.getenv("UPSTOX_REDIRECT_URI", "https://127.0.0.1")

    if not api_key or not api_secret:
        raise ValueError("Please configure UPSTOX_API_KEY and UPSTOX_API_SECRET in your root .env file.")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    cache_path = os.path.join(script_dir, "upstox_token_cache.json")

    access_token = None
    current_date = datetime.date.today().isoformat()

    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r") as f:
                cache_data = json.load(f)
            if cache_data.get("date") == current_date and cache_data.get("access_token"):
                access_token = cache_data["access_token"]
                print("Found active Upstox access token cached for today.")
        except Exception as e:
            print(f"Warning: Could not read Upstox token cache: {e}")

    session = requests.Session()

    if access_token:
        session.headers.update({
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        })
        return session

    # Trigger login flow if cache is missing, expired, or invalid
    login_url = _login_url(api_key, redirect_uri)
    print(f"Please login here to authorize:\n{login_url}\n")
    try:
        webbrowser.open(login_url)
    except Exception:
        pass

    redirected_url = input(
        "After approving, paste the FULL redirected URL (or just the 'code' param) here: "
    ).strip()

    if redirected_url.startswith("http"):
        parsed = urlparse(redirected_url)
        code = parse_qs(parsed.query).get("code", [None])[0]
    else:
        code = redirected_url

    if not code:
        raise ValueError("Could not extract authorization code from input.")

    resp = requests.post(
        TOKEN_URL,
        headers={
            "accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "code": code,
            "client_id": api_key,
            "client_secret": api_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
    )
    if not resp.ok:
        print(f"Upstox token exchange failed ({resp.status_code}): {resp.text}")
    resp.raise_for_status()
    token_data = resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        raise ValueError(f"No access_token in Upstox response: {token_data}")

    with open(cache_path, "w") as f:
        json.dump({"access_token": access_token, "date": current_date}, f, indent=4)
    print("Upstox authenticated and token cached successfully.")

    session.headers.update({
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    })
    return session
