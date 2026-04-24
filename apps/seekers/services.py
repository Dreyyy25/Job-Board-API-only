"""Service layer for the seekers app."""
from .models import EducationData, ExperienceData, SeekerProfile, SeekerSkillSet


class ProfileNotFoundError(Exception):
    """Raised when the requested seeker profile doesn't exist."""


class DashboardPermissionError(Exception):
    """Raised when the requester isn't allowed to view the dashboard."""


def build_seeker_dashboard(requester, user_id):
    """Return a dashboard dict for the given user_id.

    Access rules:
    - Admins can access any dashboard.
    - The owner can access their own.
    - Company users can access any dashboard (for applicant evaluation).
    """
    is_owner = str(requester.id) == str(user_id)
    is_admin = requester.is_staff or requester.is_superuser
    is_company = getattr(requester, 'user_type', None) == 'company'

    if not (is_owner or is_admin or is_company):
        raise DashboardPermissionError(
            'You do not have permission to access this dashboard'
        )

    try:
        profile = SeekerProfile.objects.with_related().get(user_account_id=user_id)
    except SeekerProfile.DoesNotExist:
        raise ProfileNotFoundError('Profile not found')

    # Lazy imports keep the service module independent of DRF's serializer layer.
    from .serializers import (
        EducationDataSerializer,
        ExperienceDataSerializer,
        SeekerProfileSerializer,
        SeekerSkillSetSerializer,
    )
    education = EducationData.objects.for_user(profile.user_account).with_related()
    experience = ExperienceData.objects.for_user(profile.user_account).with_related()
    skills = SeekerSkillSet.objects.for_user(profile.user_account).with_related()

    return {
        'profile': SeekerProfileSerializer(profile).data,
        'education': EducationDataSerializer(education, many=True).data,
        'experience': ExperienceDataSerializer(experience, many=True).data,
        'skills': SeekerSkillSetSerializer(skills, many=True).data,
    }
