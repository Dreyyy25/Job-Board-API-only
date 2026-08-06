"""
Custom permission classes for the jobs app
"""

from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsJobPosterOrAdmin(BasePermission):
    """
    Permission for job posts:
    - Everyone can view published jobs
    - Company owners can create and manage their own job posts
    - Admins can manage all job posts
    """

    def has_permission(self, request, view):
        """
        Read permissions for everyone,
        Write permissions for authenticated company users
        """
        # Read permissions for everyone
        if request.method in SAFE_METHODS:
            return True

        # Write permissions require authentication
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        """
        Object-level permission:
        - Everyone can read published jobs
        - Admins can modify any job
        - Company owners can only modify their own company's jobs
        """
        # Read permissions for published jobs
        if request.method in SAFE_METHODS:
            return obj.is_published

        # Admins can modify anything
        if request.user.is_staff or request.user.is_superuser:
            return True

        # Company owners can only modify their company's jobs
        return obj.company.user_account.id == request.user.id


class IsApplicantOrCompanyOrAdmin(BasePermission):
    """
    Permission for job applications:
    - Job seekers can view and manage their own applications
    - Company owners can view applications to their jobs
    - Admins can view all applications
    """

    def has_permission(self, request, view):
        """Require authentication for all operations"""
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        """
        Object-level permission:
        - Admins can access all applications
        - Job seekers can access their own applications
        - Company owners can access applications to their job posts
        """
        # Admins can access everything
        if request.user.is_staff or request.user.is_superuser:
            return True

        # Job seekers can access their own applications
        if obj.user_account.id == request.user.id:
            return True

        # Company owners can access applications to their jobs
        if obj.job_post.company.user_account.id == request.user.id:
            # Company can view but not delete applications
            if request.method == 'DELETE':
                return False
            return True

        return False


class IsApplicant(BasePermission):
    """
    Strict permission - only the job seeker who applied can access.
    Used for withdrawing applications.
    """

    def has_permission(self, request, view):
        """Require authentication"""
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        """Only the applicant can access"""
        return obj.user_account.id == request.user.id


class IsAdminOrReadOnly(BasePermission):
    """
    Permission for reference data (JobType, JobLocation):
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


class CanManageJobLocations(BasePermission):
    """
    Permission for job locations:
    - Everyone (including anonymous) can view locations
    - Company users or admins can create locations
    - Only admins can update/delete locations -- JobLocation has no owner
      FK, so ownership can't be checked object-by-object, and it's
      `on_delete=CASCADE` into JobPost (and from there into
      JobPostActivity), so admin-only is the only safe write rule for
      PUT/PATCH/DELETE without a model change.
    """

    def has_permission(self, request, view):
        """
        Read permissions for everyone.
        Create permissions for authenticated company users or admins.
        Update/delete permissions for admins only.
        """
        # Read permissions for everyone
        if request.method in SAFE_METHODS:
            return True

        # All other methods require authentication
        if not (request.user and request.user.is_authenticated):
            return False

        # Admins can do anything
        if request.user.is_staff or request.user.is_superuser:
            return True

        # Non-admins may only create, and only as a company user
        if request.method == 'POST':
            return request.user.user_type == 'company'

        # PUT/PATCH/DELETE: admins only (handled above)
        return False


class CanManageJobSkills(BasePermission):
    """
    Permission for job skill requirements:
    - Everyone can view required skills for published jobs
    - Company owners can manage skills for their job posts
    - Admins can manage all skills
    """

    def has_permission(self, request, view):
        """
        Read permissions for everyone,
        Write permissions for authenticated users
        """
        # Read permissions for everyone
        if request.method in SAFE_METHODS:
            return True

        # Write permissions require authentication
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        """
        Object-level permission:
        - Everyone can read skills for published jobs
        - Admins can modify any skills
        - Company owners can only modify skills for their jobs
        """
        # Read permissions for published jobs
        if request.method in SAFE_METHODS:
            return obj.job_post.is_published

        # Admins can modify anything
        if request.user.is_staff or request.user.is_superuser:
            return True

        # Company owners can only modify skills for their jobs
        return obj.job_post.company.user_account.id == request.user.id
