"""Small helpers: flexible key lookup, hashing, time parsing."""

import hashlib
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

_SALT = "41-vibecheck"


def h(value: Any) -> str:
    """Short one-way id. Used for session and turn ids so raw ids never reach a report."""
    return hashlib.sha256((_SALT + str(value)).encode("utf-8", "replace")).hexdigest()[:12]


def make_hasher(salt: str):
    """Same as h() but with a caller-chosen salt, so ids hashed under different salts cannot be linked to each
    other. The CLI keeps h() and its fixed salt, so its output does not change."""
    def hasher(value: Any) -> str:
        return hashlib.sha256((salt + str(value)).encode("utf-8", "replace")).hexdigest()[:12]
    return hasher


def to_int(v: Any) -> Optional[int]:
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None


def pick(d: dict, keys: Iterable[str]) -> Any:
    """First present key. Supports dotted paths into nested dicts ("cache_read.input_tokens")."""
    for k in keys:
        if k in d:
            return d[k]
        if "." in k:
            cur: Any = d
            ok = True
            for part in k.split("."):
                if isinstance(cur, dict) and part in cur:
                    cur = cur[part]
                else:
                    ok = False
                    break
            if ok:
                return cur
    return None


def pick_int(d: dict, keys: Iterable[str]) -> Optional[int]:
    return to_int(pick(d, keys))


def parse_ts(v: Any) -> Optional[float]:
    """ISO 8601 string, unix seconds, ms or ns to unix seconds."""
    if v is None:
        return None
    if isinstance(v, (int, float)) or (isinstance(v, str) and v.strip().lstrip("-").isdigit()):
        x = float(v)
        if x > 1e17:
            return x / 1e9
        if x > 1e14:
            return x / 1e6
        if x > 1e11:
            return x / 1e3
        return x
    if isinstance(v, str):
        s = v.strip().replace("Z", "+00:00")
        if "." in s:  # trim fractional seconds to 6 digits for fromisoformat on 3.9/3.10
            head, _, rest = s.partition(".")
            frac = ""
            i = 0
            while i < len(rest) and rest[i].isdigit():
                frac += rest[i]
                i += 1
            s = head + "." + (frac[:6] or "0") + rest[i:]
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    return None
