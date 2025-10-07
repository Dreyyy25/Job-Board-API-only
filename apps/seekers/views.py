from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.accounts.authentication import CustomJWTAuthentication
from .models import SeekerProfile, EducationData, ExperienceData, SkillSet, SeekerSkillSet
from .serializers import (
    SeekerProfileSerializer, EducationDataSerializer, 
    ExperienceDataSerializer, SkillSetSerializer, SeekerSkillSetSerializer
)
from .permissions import (
    IsSeekerOwnerOrAdmin,
    IsAdminOrReadOnly,
    CanManageSeekerSkills
)

# Create your views here.
class SeekerProfileViewSet(viewsets.ModelViewSet):
    """
    API for job seeker profiles.
    - Job seekers can create and manage their own profile
    - Companies can view seeker profiles (to evaluate applicants)
    - Admins can manage all profiles
    """
    queryset = SeekerProfile.objects.all()
    serializer_class = SeekerProfileSerializer
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsSeekerOwnerOrAdmin]
    
    def get_queryset(self):
        """
        Filter queryset based on user:
        - Admins see all profiles
        - Job seekers see only their own profile
        - Companies see all active seeker profiles
        """
        user = self.request.user
        
        if user.is_staff or user.is_superuser:
            return SeekerProfile.objects.all()
        elif user.user_type == 'job_seeker':
            return SeekerProfile.objects.filter(user_account=user)
        elif user.user_type == 'company':
            # Companies can view all seeker profiles
            return SeekerProfile.objects.all()
        else:
            return SeekerProfile.objects.none()
    
    def perform_create(self, serializer):
        """Automatically assign the current user as the profile owner"""
        serializer.save(user_account=self.request.user)


class EducationDataViewSet(viewsets.ModelViewSet):
    """
    API for education records.
    - Job seekers can manage their own education data
    - Companies can view education data (to evaluate applicants)
    - Admins can manage all education data
    """
    queryset = EducationData.objects.all()
    serializer_class = EducationDataSerializer
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsSeekerOwnerOrAdmin]
    
    def get_queryset(self):
        """
        Filter queryset based on user:
        - Admins see all education data
        - Job seekers see only their own education
        - Companies see all education data
        """
        user = self.request.user
        
        if user.is_staff or user.is_superuser:
            return EducationData.objects.all()
        elif user.user_type == 'job_seeker':
            return EducationData.objects.filter(user_account=user)
        elif user.user_type == 'company':
            return EducationData.objects.all()
        else:
            return EducationData.objects.none()
    
    def perform_create(self, serializer):
        """Automatically assign the current user"""
        serializer.save(user_account=self.request.user)


class ExperienceDataViewSet(viewsets.ModelViewSet):
    """
    API for work experience records.
    - Job seekers can manage their own experience data
    - Companies can view experience data (to evaluate applicants)
    - Admins can manage all experience data
    """
    queryset = ExperienceData.objects.all()
    serializer_class = ExperienceDataSerializer
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsSeekerOwnerOrAdmin]
    
    def get_queryset(self):
        """
        Filter queryset based on user:
        - Admins see all experience data
        - Job seekers see only their own experience
        - Companies see all experience data
        """
        user = self.request.user
        
        if user.is_staff or user.is_superuser:
            return ExperienceData.objects.all()
        elif user.user_type == 'job_seeker':
            return ExperienceData.objects.filter(user_account=user)
        elif user.user_type == 'company':
            return ExperienceData.objects.all()
        else:
            return ExperienceData.objects.none()
    
    def perform_create(self, serializer):
        """Automatically assign the current user"""
        serializer.save(user_account=self.request.user)


class SkillSetViewSet(viewsets.ModelViewSet):
    """
    API for managing the master list of skills.
    - Everyone can view available skills
    - Only admins can create/update/delete skills
    """
    queryset = SkillSet.objects.all()
    serializer_class = SkillSetSerializer
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAdminOrReadOnly]


class SeekerSkillSetViewSet(viewsets.ModelViewSet):
    """
    API for seeker skills with proficiency levels.
    - Job seekers can manage their own skills
    - Companies can view seeker skills (to evaluate applicants)
    - Admins can manage all seeker skills
    """
    queryset = SeekerSkillSet.objects.all()
    serializer_class = SeekerSkillSetSerializer
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [CanManageSeekerSkills]
    
    def get_queryset(self):
        """
        Filter queryset based on user:
        - Admins see all skills
        - Job seekers see only their own skills
        - Companies see all seeker skills
        """
        user = self.request.user
        
        if user.is_staff or user.is_superuser:
            return SeekerSkillSet.objects.all()
        elif user.user_type == 'job_seeker':
            return SeekerSkillSet.objects.filter(user_account=user)
        elif user.user_type == 'company':
            return SeekerSkillSet.objects.all()
        else:
            return SeekerSkillSet.objects.none()
    
    def perform_create(self, serializer):
        """Automatically assign the current user"""
        serializer.save(user_account=self.request.user)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def seeker_dashboard(request, user_id):
    """
    Get all seeker data for dashboard.
    - Job seekers can access their own dashboard
    - Admins can access any seeker dashboard
    - Companies can view seeker dashboards (for applicant evaluation)
    """
    # Security check: verify user can access this dashboard
    user = request.user
    is_owner = str(user.id) == str(user_id)
    is_admin = user.is_staff or user.is_superuser
    is_company = user.user_type == 'company'
    
    # Only owner, admin, or company can access
    if not (is_owner or is_admin or is_company):
        return Response({
            'error': 'You do not have permission to access this dashboard'
        }, status=status.HTTP_403_FORBIDDEN)
    
    try:
        profile = SeekerProfile.objects.get(user_account_id=user_id)
        education = EducationData.objects.filter(user_account_id=user_id)
        experience = ExperienceData.objects.filter(user_account_id=user_id)
        skills = SeekerSkillSet.objects.filter(user_account_id=user_id)
        
        return Response({
            'profile': SeekerProfileSerializer(profile).data,
            'education': EducationDataSerializer(education, many=True).data,
            'experience': ExperienceDataSerializer(experience, many=True).data,
            'skills': SeekerSkillSetSerializer(skills, many=True).data,
        })
    except SeekerProfile.DoesNotExist:
        return Response({
            'error': 'Profile not found'
        }, status=status.HTTP_404_NOT_FOUND)