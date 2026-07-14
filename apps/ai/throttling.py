"""AI-specific throttle classes (rates in DEFAULT_THROTTLE_RATES)."""
from rest_framework.throttling import UserRateThrottle


class AIRateThrottle(UserRateThrottle):
    """Per-user ceiling for LLM-backed endpoints — protects the Gemini bill."""
    scope = 'ai'
