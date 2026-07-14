"""Shared throttle classes.

Subclassing UserRateThrottle means anonymous requests are not throttled by
these classes (get_cache_key returns None for anon) — anon traffic stays
bounded by the default AnonRateThrottle. Rates live in
REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'] keyed by `scope`.
"""
from rest_framework.throttling import UserRateThrottle


class BurstRateThrottle(UserRateThrottle):
    """Per-user burst ceiling for write-heavy endpoints."""
    scope = 'burst'
