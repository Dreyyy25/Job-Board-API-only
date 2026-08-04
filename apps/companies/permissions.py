"""
Custom permission classes for the companies app
"""

from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsCompanyOwnerOrAdmin(BasePermission):
    """
    Permission for company profiles:
    - Company owners can manage their own company
    - Admins can manage all companies
    - Authenticated users can read all companies
    """

    def has_permission(self, request, view):
        """Allow authenticated users to read, but only company owners/admins to write"""
        # Read permissions for authenticated users
        if request.method in SAFE_METHODS:
            return request.user and request.user.is_authenticated

        # Write permissions require authentication
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        """
        Object-level permission:
        - Everyone can read
        - Admins can modify any company
        - Company owners can only modify their own company
        """
        # Read permissions for everyone
        if request.method in SAFE_METHODS:
            return True

        # Admins can modify anything
        if request.user.is_staff or request.user.is_superuser:
            return True

        # Company owners can only modify their own company
        return obj.user_account.id == request.user.id


class IsCompanyOwner(BasePermission):
    """
    Strict permission - only the company owner can access.
    No admin override. Used for sensitive company data.
    """

    def has_permission(self, request, view):
        """Require authentication"""
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        """Only the company owner can access"""
        return obj.user_account.id == request.user.id


class IsCompanyOwnerForImages(BasePermission):
    """
    Permission for company images:
    - Company owners can manage their company's images
    - Admins can manage all images
    - Everyone can view images
    """

    def has_permission(self, request, view):
        """Allow authenticated users to read, but only company owners/admins to write"""
        # Read permissions for everyone
        if request.method in SAFE_METHODS:
            return True

        # Write permissions require authentication
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        """
        Object-level permission:
        - Everyone can read
        - Admins can modify any image
        - Company owners can only modify their company's images
        """
        # Read permissions for everyone
        if request.method in SAFE_METHODS:
            return True

        # Admins can modify anything
        if request.user.is_staff or request.user.is_superuser:
            return True

        # Company owners can only modify their own company's images
        return obj.company.user_account.id == request.user.id


class IsAdminOrReadOnly(BasePermission):
    """
    Permission for reference data (BusinessStream):
    - Everyone can read
    - Only admins can create/update/delete
    """

    def has_permission(self, request, view):
        """
        Read permissions for everyone,
        Write permissions only for admins
        """
        # Read permissions for everyone
        if request.method in SAFE_METHODS:
            return True

        # Write permissions only for admins
        return request.user and (request.user.is_staff or request.user.is_superuser)
