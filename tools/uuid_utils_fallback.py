"""A stand-in for the `uuid_utils` package when its compiled file cannot be loaded.

langchain_core imports `uuid_utils.compat.uuid7` only to make time-ordered ids for tracing. On this PC Windows Application Control
sometimes blocks that package's compiled file (`_uuid_utils.cp314-win_amd64.pyd`: "An Application Control policy has blocked this file"),
and then `import app` fails and the whole backend stays down. When the real package imports, nothing changes. When it does not, this
module registers a small pure-Python `uuid_utils` (RFC 9562 version 7 ids built from the clock and `os.urandom`) so the backend starts.
The blocked file is never loaded or worked around: only the one function langchain needs is replaced."""
from __future__ import annotations

import os
import sys
import time
import types
import uuid


def _uuid7(timestamp: int | None = None, nanos: int | None = None) -> uuid.UUID:
    """A version 7 UUID: 48-bit Unix time in milliseconds, then random bits (version and variant set). `timestamp` is whole seconds
    and `nanos` the nanoseconds within that second, as uuid_utils takes them; both None means now."""
    if timestamp is None:
        ms = time.time_ns() // 1_000_000
    else:
        ms = int(timestamp) * 1000 + int(nanos or 0) // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")
    value = (ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76                          # version 7
    value |= ((rand >> 62) & 0xFFF) << 64       # 12 random bits
    value |= 0b10 << 62                         # RFC variant
    value |= rand & ((1 << 62) - 1)             # 62 random bits
    return uuid.UUID(int=value)


def install() -> bool:
    """Register the stand-in unless the real `uuid_utils` loads. True when the stand-in was installed."""
    try:
        import uuid_utils.compat  # noqa: F401
        return False
    except ImportError:
        pass
    for name in [m for m in sys.modules if m == "uuid_utils" or m.startswith("uuid_utils.")]:
        del sys.modules[name]                   # drop a half-imported package
    pkg = types.ModuleType("uuid_utils")
    compat = types.ModuleType("uuid_utils.compat")
    compat.uuid7 = _uuid7
    compat.__all__ = ["uuid7"]
    pkg.compat = compat
    pkg.uuid7 = _uuid7
    sys.modules["uuid_utils"] = pkg
    sys.modules["uuid_utils.compat"] = compat
    print("[startup] uuid_utils is blocked by Application Control here; using the pure-Python uuid7 stand-in.", flush=True)
    return True


install()
