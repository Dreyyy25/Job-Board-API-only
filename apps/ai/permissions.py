"""Permission classes for AI endpoints."""
from rest_framework.permissions import BasePermission


class IsCompanyUser(BasePermission):
    """Company-type users only. Unauthenticated → 401 via DRF."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.user_type == 'company'
        )


class IsSeekerUser(BasePermission):
    """Job-seeker-type users only. Unauthenticated → 401 via DRF."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.user_type == 'job_seeker'
        )
