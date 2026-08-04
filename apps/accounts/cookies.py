"""Refresh-token cookie helpers.

HTTP concerns (setting/clearing cookies on a response) live here rather
than in services.py, which never touches request/response objects. Both
functions read their attributes from settings.AUTH_REFRESH_COOKIE /
settings.AUTH_REFRESH_COOKIE_SECURE so prod can flip attributes (e.g.
``secure``) without a code change.
"""

from django.conf import settings


def set_refresh_cookie(response, refresh_token: str) -> None:
    """Set the refresh token as an httpOnly cookie on `response`."""
    cookie = settings.AUTH_REFRESH_COOKIE
    response.set_cookie(
        cookie["NAME"],
        refresh_token,
        max_age=cookie["MAX_AGE"],
        path=cookie["PATH"],
        httponly=cookie["HTTPONLY"],
        samesite=cookie["SAMESITE"],
        secure=settings.AUTH_REFRESH_COOKIE_SECURE,
    )


def delete_refresh_cookie(response) -> None:
    """Clear the refresh token cookie on `response`.

    Must pass the same path and samesite used to set it, or the browser
    won't recognize it as the same cookie and it won't be removed.
    """
    cookie = settings.AUTH_REFRESH_COOKIE
    response.delete_cookie(
        cookie["NAME"],
        path=cookie["PATH"],
        samesite=cookie["SAMESITE"],
    )
