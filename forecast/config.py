"""Single source of truth for forecasting constants. Nothing here is symbol-specific."""
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.environ.get("FORECAST_DATA_DIR", os.path.join(ROOT, "data", "forecast"))
DB_PATH = os.path.join(DATA_DIR, "market.db")
MODEL_DIR = os.path.join(DATA_DIR, "models")

INTERVAL = "5m"
BAR_SECONDS = 300
ANGEL_INTERVAL = {"5m": "FIVE_MINUTE", "1m": "ONE_MINUTE", "15m": "FIFTEEN_MINUTE", "1d": "ONE_DAY"}

IST_OFFSET_SEC = 19800
SESSION_OPEN_MIN = 9 * 60 + 15        # minutes after midnight IST
SESSION_CLOSE_MIN = 15 * 60 + 30      # last bar starts 15:25
BARS_PER_SESSION = 75                  # (15:30-09:15)/5m

# Only the first 72 slots (09:15 .. 15:10 bar starts) are trusted: since 2026-08-03 the provider's
# 15:15/15:20/15:25 bars are missing or flat zero-volume, cause unverified. Sessions must have ALL 72.
USABLE_SLOTS = 72

HORIZONS = (1, 2, 3, 4, 5)
SEQ_LEN = 24     # GRU input window (bars)

# Angel getCandleData truncates SILENTLY above ~100 calendar days for 5m (measured).
CHUNK_DAYS = 90
FEATURE_VERSION = "f1"
