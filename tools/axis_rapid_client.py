"""
Axis Direct RAPID API client - the ONLY live-market-data provider for the
live-charts feature (tools/axis_feed_ws.py). Not used by, and does not
touch, the existing Angel One (tools/angel_scraper.py, tools/market_price.py)
or Upstox (tools/upstox_client.py) paths - those remain solely for the
ratio-dependent live price (P/E, P/B, etc.) and are a separate concern.

Implements the hybrid encryption RAPID requires on every call:
  1. A random 16-byte AES secret_key is generated per session.
  2. secret_key is RSA-OAEP(SHA-256) encrypted with Axis's public key
     (fetched via the Handshake API) -> sent as the x-api-encryption-key
     header.
  3. Every request payload is AES-256-GCM encrypted with that same
     secret_key before being sent; every response is decrypted with it.

Credentials (AXIS_API_CLIENT_ID, AXIS_AUTHORIZATION_KEY,
AXIS_OAUTH_CLIENT_SECRET) are not yet provisioned - this module is wired
and ready to activate the moment Axis Securities issues them, but every
network call will raise ValueError until the corresponding env var is set.
"""

import os
import base64
import requests
from dotenv import load_dotenv

from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PROD_HOSTS = {
    "oauth": "https://welcome-api.axisdirect.in/oauth/token",
    "handshake": "https://welcome-api.axisdirect.in/oauth/handshake",
    "feed_ws": "wss://raterefresh.axisdirect.in",
}
UAT_HOSTS = {
    "oauth": "https://welcome.apigw.uat.asldt.com/oauth/token",
    "handshake": "https://welcome.apigw.uat.asldt.com/oauth/handshake",
    "feed_ws": "wss://sender-feed-api.uat.asldt.com",
}


def _hosts():
    load_dotenv()
    return PROD_HOSTS if os.getenv("AXIS_ENV", "uat").lower() == "prod" else UAT_HOSTS


def _require_creds():
    load_dotenv()
    client_id = os.getenv("AXIS_API_CLIENT_ID")
    auth_key = os.getenv("AXIS_AUTHORIZATION_KEY")
    client_secret = os.getenv("AXIS_OAUTH_CLIENT_SECRET")
    if not client_id or not auth_key or not client_secret:
        raise ValueError(
            "Axis RAPID API not configured. Set AXIS_API_CLIENT_ID, "
            "AXIS_AUTHORIZATION_KEY and AXIS_OAUTH_CLIENT_SECRET in the "
            "root .env file (see .env.example)."
        )
    return client_id, auth_key, client_secret


def generate_secret_key():
    """16 random bytes as a hex string - the AES-256 key used for this session."""
    return os.urandom(16).hex()


def encrypt_aes(payload: str, secret_key: str) -> str:
    """AES-256-GCM encrypt `payload` with `secret_key` (hex string).

    Returns "<nonce_b64>.<tag_b64>.<ciphertext_b64>", matching the format
    Axis's own sample decryptor expects.
    """
    key_bytes = secret_key.encode()
    aesgcm = AESGCM(key_bytes)
    nonce = os.urandom(12)  # AESGCM default/standard nonce size
    ct_and_tag = aesgcm.encrypt(nonce, payload.encode(), None)
    ciphertext, tag = ct_and_tag[:-16], ct_and_tag[-16:]
    return ".".join(
        base64.b64encode(part).decode()
        for part in (nonce, tag, ciphertext)
    )


def decrypt_aes(encoded_payload: str, secret_key: str) -> str:
    """Inverse of encrypt_aes - decrypts a RAPID API response body."""
    key_bytes = secret_key.encode()
    encoded_nonce, encoded_tag, encoded_ciphertext = encoded_payload.split(".")
    nonce = base64.b64decode(encoded_nonce)
    tag = base64.b64decode(encoded_tag)
    ciphertext = base64.b64decode(encoded_ciphertext)
    aesgcm = AESGCM(key_bytes)
    plaintext = aesgcm.decrypt(nonce, ciphertext + tag, None)
    return plaintext.decode()


def encrypt_rsa(secret_key: str, public_key_pem_body: str) -> str:
    """RSA-OAEP(SHA-256) encrypt `secret_key` with Axis's public key.

    `public_key_pem_body` is the raw base64 body Axis returns from the
    Handshake API (no PEM header/footer) - this wraps it into PEM.
    """
    pem = f"-----BEGIN PUBLIC KEY-----\n{public_key_pem_body}\n-----END PUBLIC KEY-----"
    key = serialization.load_pem_public_key(pem.encode())
    encrypted = key.encrypt(
        secret_key.encode(),
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return base64.b64encode(encrypted).decode()


def get_handshake_public_key():
    """Calls the Handshake API to obtain Axis's current RSA public key.

    Not yet exercised end-to-end (no credentials to test against) - the
    response shape is inferred from the docs and may need adjusting once
    Axis provisions real access.
    """
    client_id, auth_key, _ = _require_creds()
    resp = requests.post(
        _hosts()["handshake"],
        headers={
            "Authorization": auth_key,
            "X-API-Client-Id": client_id,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("publicKey") or data.get("public_key")


def get_oauth_token():
    """Fetches the partner OAuth token, encrypting the request per RAPID's
    hybrid scheme. Raises ValueError if credentials aren't configured yet.
    """
    client_id, auth_key, client_secret = _require_creds()
    secret_key = generate_secret_key()
    public_key = get_handshake_public_key()
    api_encryption_key = encrypt_rsa(secret_key, public_key)

    resp = requests.post(
        _hosts()["oauth"],
        headers={
            "Authorization": auth_key,
            "X-API-Client-Id": client_id,
            "x-api-encryption-key": api_encryption_key,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=15,
    )
    resp.raise_for_status()
    body = resp.json()
    if "encrypted" in body:
        body = decrypt_aes(body["encrypted"], secret_key)
    return body, secret_key
