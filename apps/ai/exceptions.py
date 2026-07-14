"""Domain exceptions for AI features. Views map these 1:1 to HTTP statuses."""


class AIProviderError(Exception):
    """Gemini unreachable / provider 5xx after one retry → HTTP 502."""


class AIQuotaExceededError(Exception):
    """Provider-side quota exhausted (distinct from local throttle) → HTTP 429."""


class AIResponseInvalidError(Exception):
    """Model output failed schema validation after one retry → HTTP 502."""


class CompanyProfileMissingError(Exception):
    """Company-type user has no Company row (e.g. deleted after signup) → HTTP 400."""


class InvalidResumeFileError(Exception):
    """Resume upload rejected: wrong type, over size cap, unreadable, or
    not exactly one of text/file → HTTP 400."""
