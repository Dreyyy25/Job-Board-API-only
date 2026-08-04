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


class ConversationNotFoundError(Exception):
    """Chat thread missing, malformed, or not owned by the requester → HTTP 404.

    Not-owned deliberately returns 404 rather than 403: a 403 would confirm
    that someone else's conversation id exists.
    """


class AgentLimitExceededError(Exception):
    """Chat agent hit its per-turn call bound or wall-clock deadline → HTTP 504.

    Retryable: the NEXT turn on this thread may well succeed.
    """


class ConversationExhaustedError(Exception):
    """Conversation reached its lifetime model-call ceiling → HTTP 409.

    Distinct from AgentLimitExceededError because it is NOT retryable: the
    thread-limit counter is checkpointed, so every future turn on this thread
    raises too. The user must start a new conversation.
    """
