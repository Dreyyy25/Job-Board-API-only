from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import SeekerProfile, EducationData, ExperienceData, SkillSet, SeekerSkillSet
from .serializers import (
    SeekerProfileSerializer, EducationDataSerializer, 
    ExperienceDataSerializer, SkillSetSerializer, SeekerSkillSetSerializer
)

# Create your views here.
class SeekerProfileViewSet(viewsets.ModelViewSet):
    """API for job seeker profiles"""
    queryset = SeekerProfile.objects.all()
    serializer_class = SeekerProfileSerializer

class EducationDataViewSet(viewsets.ModelViewSet):
    """API for education records"""
    queryset = EducationData.objects.all()
    serializer_class = EducationDataSerializer

class ExperienceDataViewSet(viewsets.ModelViewSet):
    """API for work experience records"""
    queryset = ExperienceData.objects.all()
    serializer_class = ExperienceDataSerializer

class SkillSetViewSet(viewsets.ModelViewSet):
    """API for managing skills"""
    queryset = SkillSet.objects.all()
    serializer_class = SkillSetSerializer

class SeekerSkillSetViewSet(viewsets.ModelViewSet):
    """API for seeker skills with proficiency levels"""
    queryset = SeekerSkillSet.objects.all()
    serializer_class = SeekerSkillSetSerializer

@api_view(['GET'])
def seeker_dashboard(request, user_id):
    """Get all seeker data for dashboard"""
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
        return Response({'error': 'Profile not found'}, status=404)