"""
Custom permission classes for the seekers app
"""
from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsSeekerOwnerOrAdmin(BasePermission):
    """
    Permission for job seeker profiles and related data:
    - Job seekers can manage their own profile
    - Admins can manage all profiles
    - Company users can view seeker profiles (for applications)
    """
    
    def has_permission(self, request, view):
        """
        Read permissions for authenticated users (companies need to view applicants),
        Write permissions for job seekers and admins
        """
        # Require authentication
        if not (request.user and request.user.is_authenticated):
            return False
        
        # Read permissions for all authenticated users
        if request.method in SAFE_METHODS:
            return True
        
        # Write permissions for job seekers and admins
        return request.user.user_type == 'job_seeker' or request.user.is_staff or request.user.is_superuser
    
    def has_object_permission(self, request, view, obj):
        """
        Object-level permission:
        - Admins can access everything
        - Job seekers can only access their own data
        - Companies can view (but not modify) seeker profiles
        """
        # Admins can do anything
        if request.user.is_staff or request.user.is_superuser:
            return True
        
        # Determine the user_account based on object type
        if hasattr(obj, 'user_account'):
            owner_id = obj.user_account.id
        else:
            # For SeekerProfile, user_account is the primary key
            owner_id = obj.user_account_id
        
        # Job seekers can manage their own data
        if owner_id == request.user.id:
            return True
        
        # Companies can view (but not modify) seeker data
        if request.user.user_type == 'company' and request.method in SAFE_METHODS:
            return True
        
        return False


class IsSeekerOwner(BasePermission):
    """
    Strict permission - only the job seeker owner can access.
    No admin override. Used for highly sensitive seeker data.
    """
    
    def has_permission(self, request, view):
        """Require job seeker authentication"""
        return (request.user and request.user.is_authenticated and 
                request.user.user_type == 'job_seeker')
    
    def has_object_permission(self, request, view, obj):
        """Only the seeker owner can access"""
        if hasattr(obj, 'user_account'):
            return obj.user_account.id == request.user.id
        else:
            # For SeekerProfile
            return obj.user_account_id == request.user.id


class IsAdminOrReadOnly(BasePermission):
    """
    Permission for reference data (SkillSet):
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


class CanManageSeekerSkills(BasePermission):
    """
    Permission for seeker skill assignments:
    - Job seekers can manage their own skills
    - Companies can view seeker skills
    - Admins can manage all skills
    """
    
    def has_permission(self, request, view):
        """Require authentication"""
        return request.user and request.user.is_authenticated
    
    def has_object_permission(self, request, view, obj):
        """
        Object-level permission:
        - Admins can do anything
        - Job seekers can manage their own skills
        - Companies can view skills
        """
        # Admins can do anything
        if request.user.is_staff or request.user.is_superuser:
            return True
        
        # Job seekers can manage their own skills
        if obj.user_account.id == request.user.id:
            return True
        
        # Companies can view skills
        if request.user.user_type == 'company' and request.method in SAFE_METHODS:
            return True
        
        return False
