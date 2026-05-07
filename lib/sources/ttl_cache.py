"""
On-disk TTL cache for on-demand pipeline fetches.

Design:
  - Key-value store backed by JSON files under cfg.DATA_CACHE.
  - TTL is checked via os.path.getmtime — avoids datetime arithmetic
    and timezone-aware/naive mixing issues on Windows.
  - Thread-safe: one threading.Lock per cache key. APScheduler fires
    prices and sentiment jobs on overlapping interval schedules; concurrent
    writes to the same cache key without locking can produce partial JSON
    on Windows (no atomic write guarantee without explicit tmp→rename).

Usage:
    from lib.sources.ttl_cache import get_cached, set_cached, is_fresh

    # Check before fetching
    if is_fresh("da_bulletins", cfg.TTL_PRICES):
        return get_cached("da_bulletins")

    data = fetch_from_source()
    set_cached("da_bulletins", data)
    return data

    # Or use the helper that wraps the pattern:
    data = get_or_fetch("da_bulletins", cfg.TTL_PRICES, fetch_fn)

Key naming:
    Use lowercase_underscored strings — e.g. "da_bulletins", "psa_cpi".
    Keys map directly to filenames: DATA_CACHE / f"{key}.json"
    Keys must not contain path separators or whitespace.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

import config as cfg

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lock registry — one lock per cache key, created lazily
# ---------------------------------------------------------------------------

_locks: dict[str, threading.Lock] = {}
_registry_lock = threading.Lock()


def _get_lock(key: str) -> threading.Lock:
    """Return (or create) the per-key lock. Thread-safe via _registry_lock."""
    with _registry_lock:
        if key not in _locks:
            _locks[key] = threading.Lock()
        return _locks[key]


# ---------------------------------------------------------------------------
# Path helper
# ---------------------------------------------------------------------------

def _cache_path(key: str) -> Path:
    """Resolve the on-disk path for a given cache key."""
    if "/" in key or "\\" in key or " " in key:
        raise ValueError(
            f"Cache key must not contain path separators or whitespace: {key!r}"
        )
    return cfg.DATA_CACHE / f"{key}.json"


# ---------------------------------------------------------------------------
# Core read / write
# ---------------------------------------------------------------------------

def is_fresh(key: str, ttl_seconds: int | float) -> bool:
    """
    Return True if the cached file for `key` exists and is younger than
    `ttl_seconds`. Uses os.path.getmtime — no datetime arithmetic.

    Thread-safe: acquires the per-key lock before stat.
    """
    path = _cache_path(key)
    lock = _get_lock(key)
    with lock:
        if not path.exists():
            return False
        age = time.time() - os.path.getmtime(path)
        fresh = age < ttl_seconds
        logger.debug(
            "Cache '%s': age=%.0fs ttl=%ss fresh=%s", key, age, ttl_seconds, fresh
        )
        return fresh


def get_cached(key: str) -> Optional[Any]:
    """
    Read and deserialise the JSON cache file for `key`.
    Returns None if the file does not exist or cannot be parsed.
    Thread-safe: acquires the per-key lock before read.
    """
    path = _cache_path(key)
    lock = _get_lock(key)
    with lock:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Cache read failed for key='%s': %s", key, exc)
            return None


def set_cached(key: str, data: Any) -> None:
    """
    Serialise `data` to JSON and write atomically to the cache file.

    Atomic write pattern (tmp → rename) prevents partial reads by
    concurrent processes or threads that hold a read lock after this
    function's lock is released.

    Thread-safe: acquires the per-key lock for the full write sequence.
    Raises on serialisation failure (don't cache un-serialisable objects).
    """
    path = _cache_path(key)
    tmp_path = path.with_suffix(".json.tmp")
    lock = _get_lock(key)

    path.parent.mkdir(parents=True, exist_ok=True)

    payload = json.dumps(data, ensure_ascii=False, default=str)
    with lock:
        try:
            tmp_path.write_text(payload, encoding="utf-8")
            # os.replace is atomic on POSIX; on Windows it replaces atomically
            # within the same filesystem (DATA_CACHE is always local here).
            os.replace(tmp_path, path)
            logger.debug("Cache '%s' written (%d bytes).", key, len(payload))
        except OSError as exc:
            logger.error("Cache write failed for key='%s': %s", key, exc)
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise


def invalidate(key: str) -> None:
    """
    Delete the cache file for `key`. No-op if it does not exist.
    Thread-safe: acquires the per-key lock before unlink.
    """
    path = _cache_path(key)
    lock = _get_lock(key)
    with lock:
        if path.exists():
            path.unlink()
            logger.info("Cache '%s' invalidated.", key)


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------

def get_or_fetch(
    key: str,
    ttl_seconds: int | float,
    fetch_fn: Callable[[], Any],
) -> Any:
    """
    Return cached data if fresh, otherwise call fetch_fn(), cache the
    result, and return it.

    This is the primary public interface for on-demand fetchers in pipelines:

        data = get_or_fetch("da_bulletins", cfg.TTL_PRICES, fetch_da_bulletins)

    If fetch_fn raises, the exception propagates — no stale fallback.
    Stale fallback would silently return outdated data, which is worse than
    a pipeline run recording an 'error' status in pipeline_runs.

    Concurrency note (CF-V6-005):
        The per-key locks in is_fresh and set_cached prevent data corruption,
        but there is no outer lock spanning is_fresh → fetch_fn → set_cached.
        In a narrow race window, two concurrent callers may both see a cache
        miss and each invoke fetch_fn independently. set_cached is atomic and
        last-write-wins — no corruption results. Callers must tolerate
        fetch_fn being invoked more than once concurrently per key.
    """
    if is_fresh(key, ttl_seconds):
        cached = get_cached(key)
        if cached is not None:
            logger.info("Cache hit for key='%s'.", key)
            return cached
        # File was fresh per mtime but read failed (race or corruption) —
        # fall through to fetch.
        logger.warning(
            "Cache '%s' was fresh but unreadable — re-fetching.", key
        )

    logger.info("Cache miss for key='%s' — fetching.", key)
    data = fetch_fn()
    set_cached(key, data)
    return data