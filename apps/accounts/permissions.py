"""
Custom permission classes for the accounts app
"""

from rest_framework.permissions import BasePermission


class IsOwnerOrAdmin(BasePermission):
    """
    Custom permission to only allow users to access their own account,
    or allow admins to access all accounts.

    - Authenticated users can access their own account
    - Staff and superusers can access all accounts
    """

    def has_permission(self, request, view):
        """
        Check if user is authenticated
        """
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        """
        Object-level permission check:
        - Admins (staff/superuser) can access any account
        - Regular users can only access their own account
        """
        # Admins can access all accounts
        if request.user.is_staff or request.user.is_superuser:
            return True

        # Users can only access their own account
        return obj.id == request.user.id


class IsOwner(BasePermission):
    """
    Permission that only allows users to access their own objects.
    Stricter than IsOwnerOrAdmin - doesn't allow admin override.
    """

    def has_permission(self, request, view):
        """Check if user is authenticated"""
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        """Users can only access their own objects"""
        return obj.id == request.user.id


class IsAdminOrReadOnly(BasePermission):
    """
    Permission that allows read access to everyone,
    but write access only to admins.
    """

    def has_permission(self, request, view):
        """
        Read permissions allowed for any request,
        Write permissions only for admins
        """
        from rest_framework import permissions

        # Read permissions for everyone
        if request.method in permissions.SAFE_METHODS:
            return True

        # Write permissions only for admins
        return request.user and (request.user.is_staff or request.user.is_superuser)
