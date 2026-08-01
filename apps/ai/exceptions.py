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


class NoApplicantsError(Exception):
    """Screening requested for a post with zero applicants → HTTP 409."""


class JobPostNotFoundError(Exception):
    """Screening requested for a job post id that does not exist → HTTP 404."""


class ScreeningPermissionError(Exception):
    """Requester neither owns the job post nor is an admin → HTTP 403."""
