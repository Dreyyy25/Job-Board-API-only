from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.accounts.authentication import CustomJWTAuthentication
from . import services
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
        """Admins/companies → all; seekers → own; else → none."""
        qs = SeekerProfile.objects.with_related()
        user = self.request.user
        if user.is_staff or user.is_superuser or user.user_type == 'company':
            return qs
        if user.user_type == 'job_seeker':
            return qs.filter(user_account=user)
        return qs.none()
    
    def perform_create(self, serializer):
        """Automatically assign the current user as the profile owner.

        After Tier 1's signal, every job_seeker user has an auto-created
        SeekerProfile. Pre-check existence and 400 rather than letting
        the OneToOne IntegrityError turn into a 500.
        """
        from rest_framework.exceptions import ValidationError
        if SeekerProfile.objects.filter(user_account=self.request.user).exists():
            raise ValidationError(
                {'detail': 'Profile already exists. Use PATCH to update.'}
            )
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
        """Admins/companies → all; seekers → own; else → none."""
        qs = EducationData.objects.with_related()
        user = self.request.user
        if user.is_staff or user.is_superuser or user.user_type == 'company':
            return qs
        if user.user_type == 'job_seeker':
            return qs.for_user(user)
        return qs.none()
    
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
        """Admins/companies → all; seekers → own; else → none."""
        qs = ExperienceData.objects.with_related()
        user = self.request.user
        if user.is_staff or user.is_superuser or user.user_type == 'company':
            return qs
        if user.user_type == 'job_seeker':
            return qs.for_user(user)
        return qs.none()
    
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
        """Admins/companies → all; seekers → own; else → none."""
        qs = SeekerSkillSet.objects.with_related()
        user = self.request.user
        if user.is_staff or user.is_superuser or user.user_type == 'company':
            return qs
        if user.user_type == 'job_seeker':
            return qs.for_user(user)
        return qs.none()
    
    def perform_create(self, serializer):
        """Automatically assign the current user"""
        serializer.save(user_account=self.request.user)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def seeker_dashboard(request, user_id):
    """Get all seeker data for dashboard. Owner/admin/company."""
    try:
        data = services.build_seeker_dashboard(request.user, user_id)
    except services.DashboardPermissionError as e:
        return Response({'error': str(e)}, status=status.HTTP_403_FORBIDDEN)
    except services.ProfileNotFoundError as e:
        return Response({'error': str(e)}, status=status.HTTP_404_NOT_FOUND)
    return Response(data)