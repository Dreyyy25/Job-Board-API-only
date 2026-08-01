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


class IsCompanyUserOrAdmin(BasePermission):
    """Company-type users plus admins. Unauthenticated → 401 via DRF.

    Folds the is_staff/is_superuser bypass into the class, per the
    IsJobPosterOrAdmin house pattern. Object-level ownership is NOT checked
    here: @api_view function views have no get_object hook, so the service
    raises ScreeningPermissionError for a post the requester does not own.
    """

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and (user.user_type == 'company' or user.is_staff or user.is_superuser)
        )
