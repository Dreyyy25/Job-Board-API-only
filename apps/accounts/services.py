"""Service layer for the accounts app.

Business logic for register/login/logout. Views translate domain
exceptions into HTTP responses via the exception-to-HTTP map pinned
in the Tier 2 spec. The view never imports simplejwt — the service
wraps TokenError into InvalidTokenError so the abstraction holds.
"""
import hashlib
import logging

from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from .models import UserAccount

_security_logger = logging.getLogger('django.security')


def _email_hash(email):
    """Return a 16-hex-char SHA-256 of a normalized email for security logs.

    Keeps raw emails out of logs (GDPR-friendly default) while preserving
    forensic correlation: a single attacker hammering one account still
    shows as one hash. Empty/missing email hashes to a constant prefix —
    a spike of that value signals bot traffic without a body.
    """
    normalized = (email or '').strip().lower().encode()
    return hashlib.sha256(normalized).hexdigest()[:16]


class InvalidCredentialsError(Exception):
    """Raised by login_user when email is unknown or password is wrong."""


class InvalidTokenError(Exception):
    """Raised by logout_user when the refresh token is invalid/expired."""


def _mint_tokens(user):
    refresh = RefreshToken.for_user(user)
    refresh['user_id'] = str(user.id)
    refresh['email'] = user.email
    refresh['user_type'] = user.user_type
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }


@transaction.atomic
def register_user(email, password, user_type, **extra):
    """Create a user and return (user_with_profile_prefetched, tokens_dict).

    Password policy is enforced here so shell/test callers that bypass
    the DRF serializer still hit Django's validators. Raises
    django.core.exceptions.ValidationError on weak passwords; the view
    translates this into a DRF 400.

    Profile creation is handled by the post_save signal (Tier 1). The
    returned user is re-fetched via with_profile() so callers can
    access user.seeker_profile / user.company_profile without an extra
    query.
    """
    validate_password(
        password,
        user=UserAccount(email=email, user_type=user_type),
    )
    user = UserAccount.objects.create_user(
        email=email, password=password, user_type=user_type, **extra,
    )
    user = UserAccount.objects.with_profile().get(pk=user.pk)
    return user, _mint_tokens(user)


def login_user(email, password):
    """Return (user, tokens_dict). Raise InvalidCredentialsError on failure.

    Logs a WARNING to django.security on failure, keyed by a 16-char
    SHA-256 prefix of the attempted email rather than the plaintext.
    """
    try:
        user = UserAccount.objects.get(email=email)
    except UserAccount.DoesNotExist:
        _security_logger.warning(
            'Failed login attempt for email_hash=%s', _email_hash(email),
        )
        raise InvalidCredentialsError()
    if not user.check_password(password):
        _security_logger.warning(
            'Failed login attempt for email_hash=%s', _email_hash(email),
        )
        raise InvalidCredentialsError()
    user.last_login = timezone.now()
    user.save(update_fields=['last_login'])
    return user, _mint_tokens(user)


def logout_user(refresh_token):
    """Blacklist the refresh token; raise InvalidTokenError on bad token."""
    if not refresh_token:
        raise InvalidTokenError('refresh token required')
    try:
        RefreshToken(refresh_token).blacklist()
    except TokenError as e:
        raise InvalidTokenError(str(e)) from e
