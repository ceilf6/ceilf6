"""Trusted proxy client IP extraction and atomic comment rate limiting."""

from __future__ import annotations

import hashlib
import ipaddress
import math
import os
import threading
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager

from django.conf import settings
from django.core.cache import caches
from django.core.cache.backends.base import BaseCache
from django.core.cache.backends.filebased import FileBasedCache
from django.core.files import locks
from django.http import HttpRequest
from django.http.request import split_domain_port

_PROCESS_LOCK = threading.Lock()


def _normalize_ip(raw_ip: str) -> str | None:
    """Validate and canonicalize IPv4/IPv6 (with optional `:port` or `[v6]:port`)."""
    candidate = raw_ip.strip()
    if not candidate:
        return None

    domain, port = split_domain_port(candidate)
    if domain and port:
        try:
            port_num = int(port)
        except ValueError:
            return None
        if not (1 <= port_num <= 65535):
            return None
        if domain.startswith("[") and domain.endswith("]"):
            candidate = domain[1:-1]
        else:
            candidate = domain
    elif candidate.startswith("[") and candidate.endswith("]"):
        candidate = candidate[1:-1]

    try:
        parsed = ipaddress.ip_address(candidate)
    except ValueError:
        return None

    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped is not None:
        return str(parsed.ipv4_mapped)
    return str(parsed)


def get_client_ip(request: HttpRequest) -> str:
    """Extract trusted client IP aligned with `settings.ALLAUTH_TRUSTED_PROXY_COUNT`."""
    remote_ip = _normalize_ip(str(request.META.get("REMOTE_ADDR", "") or ""))
    trusted_proxy_count = int(getattr(settings, "ALLAUTH_TRUSTED_PROXY_COUNT", 0) or 0)
    raw_xff = str(request.META.get("HTTP_X_FORWARDED_FOR", "") or "").strip()

    if trusted_proxy_count <= 0 or not raw_xff:
        return remote_ip or "unknown"

    raw_hops = [part.strip() for part in raw_xff.split(",")]
    if len(raw_hops) < trusted_proxy_count:
        return remote_ip or "unknown"

    normalized = _normalize_ip(raw_hops[-trusted_proxy_count])
    if normalized is not None:
        return normalized
    return remote_ip or "unknown"


def _build_cache_key(scope: str, subject: str, window: int) -> str:
    digest = hashlib.sha256(subject.encode("utf-8")).hexdigest()[:32]
    return f"comments_rl_{scope}_{digest}_{window}"


def _sorted_rules(raw_rules: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    return sorted(
        ((int(limit), int(window)) for limit, window in raw_rules),
        key=lambda pair: pair[1],
    )


@contextmanager
def _rate_limit_lock(backend: BaseCache) -> Iterator[None]:
    with _PROCESS_LOCK:
        if isinstance(backend, FileBasedCache):
            os.makedirs(backend._dir, exist_ok=True)
            lock_path = os.path.join(backend._dir, ".comments_ratelimit.lock")
            with open(lock_path, "a+b") as lock_file:
                locks.lock(lock_file, locks.LOCK_EX)
                try:
                    yield
                finally:
                    locks.unlock(lock_file)
        else:
            yield


def _unpack_bucket_entry(entry: object, *, now: float, window: int) -> tuple[int, float]:
    if (
        isinstance(entry, tuple)
        and len(entry) == 2
        and isinstance(entry[0], int)
        and not isinstance(entry[0], bool)
        and isinstance(entry[1], (int, float))
        and not isinstance(entry[1], bool)
        and float(entry[1]) > now
    ):
        return entry[0], float(entry[1])
    return 0, float(now + window)


def consume_comment_rate_limit(
    request: HttpRequest, *, user_id: int | None
) -> tuple[bool, int]:
    """Atomically check and consume all applicable buckets (all-or-nothing)."""
    limits_cfg = getattr(settings, "COMMENT_RATE_LIMITS", None) or {}
    if not limits_cfg:
        return True, 0

    client_ip = get_client_ip(request)
    buckets: list[tuple[str, str, int, int]] = []
    if user_id is None:
        for limit, window in _sorted_rules(limits_cfg.get("guest_ip", ())):
            buckets.append(("guest_ip", client_ip, limit, window))
    else:
        for limit, window in _sorted_rules(limits_cfg.get("member_user", ())):
            buckets.append(("member_user", str(user_id), limit, window))
        for limit, window in _sorted_rules(limits_cfg.get("member_ip", ())):
            buckets.append(("member_ip", client_ip, limit, window))

    if not buckets:
        return True, 0

    backend = caches["default"]
    with _rate_limit_lock(backend):
        now = time.time()
        staged: dict[str, tuple[int, float]] = {}
        for scope, subject, limit, window in buckets:
            if window <= 0:
                continue
            if limit <= 0:
                return False, max(1, window)

            cache_key = _build_cache_key(scope, subject, window)
            if cache_key in staged:
                current_count, exp_ts = staged[cache_key]
            else:
                current_count, exp_ts = _unpack_bucket_entry(
                    backend.get(cache_key), now=now, window=window
                )

            if current_count + 1 > limit:
                retry_after = max(1, min(window, math.ceil(exp_ts - now)))
                return False, retry_after

            staged[cache_key] = (current_count + 1, exp_ts)

        for cache_key, (next_count, exp_ts) in staged.items():
            ttl = max(1, math.ceil(exp_ts - now))
            backend.set(cache_key, (next_count, exp_ts), timeout=ttl)

    return True, 0
