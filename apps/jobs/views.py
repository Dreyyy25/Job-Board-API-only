from rest_framework import viewsets, status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.db.models import Q
from .models import JobType, JobLocation, JobPost, JobPostActivity, JobPostSkillSet
from .serializers import (
    JobTypeSerializer, JobLocationSerializer, JobPostSerializer,
    JobPostActivitySerializer, JobPostSkillSetSerializer
)

# Create your views here.
class JobTypeViewSet(viewsets.ModelViewSet):
    """API for job types"""
    queryset = JobType.objects.all()
    serializer_class = JobTypeSerializer

class JobLocationViewSet(viewsets.ModelViewSet):
    """API for job locations"""
    queryset = JobLocation.objects.all()
    serializer_class = JobLocationSerializer

class JobPostViewSet(viewsets.ModelViewSet):
    """API for job posts with search functionality"""
    queryset = JobPost.objects.filter(is_published=True, is_active=True)
    serializer_class = JobPostSerializer
    
    def get_queryset(self):
        queryset = JobPost.objects.filter(is_published=True, is_active=True)
        
        # Search functionality
        search = self.request.query_params.get('search', None)
        if search:
            queryset = queryset.filter(
                Q(job_title__icontains=search) |
                Q(job_description__icontains=search)
            )
        
        # Filter by location
        city = self.request.query_params.get('city', None)
        if city:
            queryset = queryset.filter(job_location__city__icontains=city)
            
        return queryset

class JobPostActivityViewSet(viewsets.ModelViewSet):
    """API for job applications"""
    queryset = JobPostActivity.objects.all()
    serializer_class = JobPostActivitySerializer

class JobPostSkillSetViewSet(viewsets.ModelViewSet):
    """API for job skill requirements"""
    queryset = JobPostSkillSet.objects.all()
    serializer_class = JobPostSkillSetSerializer

@api_view(['POST'])
def apply_for_job(request):
    """Apply for a job"""
    user_id = request.data.get('user_account')
    job_id = request.data.get('job_post')
    
    # Check if already applied
    if JobPostActivity.objects.filter(user_account_id=user_id, job_post_id=job_id).exists():
        return Response({
            'error': 'You have already applied for this job'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    serializer = JobPostActivitySerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response({
            'message': 'Application submitted successfully'
        }, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
def job_applications(request, job_id):
    """Get all applications for a specific job"""
    applications = JobPostActivity.objects.filter(job_post_id=job_id)
    serializer = JobPostActivitySerializer(applications, many=True)
    return Response(serializer.data)

@api_view(['GET'])
def user_applications(request, user_id):
    """Get all applications by a specific user"""
    applications = JobPostActivity.objects.filter(user_account_id=user_id)
    serializer = JobPostActivitySerializer(applications, many=True)
    return Response(serializer.data)