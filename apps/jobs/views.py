from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Q
from apps.accounts.authentication import CustomJWTAuthentication
from .models import JobType, JobLocation, JobPost, JobPostActivity, JobPostSkillSet
from .serializers import (
    JobTypeSerializer, JobLocationSerializer, JobPostSerializer,
    JobPostActivitySerializer, JobPostSkillSetSerializer
)
from .permissions import (
    IsAdminOrReadOnly,
    IsJobPosterOrAdmin,
    IsApplicantOrCompanyOrAdmin,
    CanManageJobSkills
)

# Create your views here.
class JobTypeViewSet(viewsets.ModelViewSet):
    """
    API for job types (Full-time, Part-time, etc.).
    - Everyone can view job types
    - Only admins can create/update/delete job types
    """
    queryset = JobType.objects.all()
    serializer_class = JobTypeSerializer
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAdminOrReadOnly]


class JobLocationViewSet(viewsets.ModelViewSet):
    """
    API for job locations.
    - Everyone can view locations
    - Only admins can create/update/delete locations
    """
    queryset = JobLocation.objects.all()
    serializer_class = JobLocationSerializer
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAdminOrReadOnly]


class JobPostViewSet(viewsets.ModelViewSet):
    """
    API for job posts with search functionality.
    - Everyone can view published, active jobs
    - Company owners can create and manage their own job posts
    - Admins can manage all job posts
    """
    queryset = JobPost.objects.filter(is_published=True, is_active=True)
    serializer_class = JobPostSerializer
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsJobPosterOrAdmin]
    
    def get_queryset(self):
        """
        Filter queryset based on user type:
        - Admins see all jobs
        - Company users see their own jobs (including unpublished)
        - Others see only published, active jobs
        """
        user = self.request.user
        queryset = JobPost.objects.all()
        
        # Admins see everything
        if user.is_staff or user.is_superuser:
            pass  # Return all jobs
        # Company users see their own jobs
        elif user.is_authenticated and user.user_type == 'company':
            queryset = queryset.filter(company__user_account=user)
        # Others see only published, active jobs
        else:
            queryset = queryset.filter(is_published=True, is_active=True)
        
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
    
    def perform_create(self, serializer):
        """
        Automatically assign the job to the company of the current user.
        Only company-type users should be creating jobs.
        """
        if self.request.user.user_type != 'company':
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only company users can create job posts")
        
        # Get the company profile for this user
        from apps.companies.models import Company
        try:
            company = Company.objects.get(user_account=self.request.user)
            serializer.save(company=company)
        except Company.DoesNotExist:
            from rest_framework.exceptions import ValidationError
            raise ValidationError("You must create a company profile before posting jobs")


class JobPostActivityViewSet(viewsets.ModelViewSet):
    """
    API for job applications.
    - Job seekers can view and manage their own applications
    - Company owners can view applications to their jobs
    - Admins can view all applications
    """
    queryset = JobPostActivity.objects.all()
    serializer_class = JobPostActivitySerializer
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsApplicantOrCompanyOrAdmin]
    
    def get_queryset(self):
        """
        Filter queryset based on user:
        - Admins see all applications
        - Job seekers see only their applications
        - Company users see applications to their jobs
        """
        user = self.request.user
        
        if user.is_staff or user.is_superuser:
            return JobPostActivity.objects.all()
        elif user.user_type == 'job_seeker':
            return JobPostActivity.objects.filter(user_account=user)
        elif user.user_type == 'company':
            return JobPostActivity.objects.filter(job_post__company__user_account=user)
        else:
            return JobPostActivity.objects.none()


class JobPostSkillSetViewSet(viewsets.ModelViewSet):
    """
    API for job skill requirements.
    - Everyone can view skills for published jobs
    - Company owners can manage skills for their job posts
    - Admins can manage all skills
    """
    queryset = JobPostSkillSet.objects.all()
    serializer_class = JobPostSkillSetSerializer
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [CanManageJobSkills]
    
    def get_queryset(self):
        """
        Filter queryset based on user:
        - Admins see all skills
        - Company users see skills for their jobs
        - Others see skills for published jobs
        """
        user = self.request.user
        
        if user.is_staff or user.is_superuser:
            return JobPostSkillSet.objects.all()
        elif user.is_authenticated and user.user_type == 'company':
            return JobPostSkillSet.objects.filter(job_post__company__user_account=user)
        else:
            return JobPostSkillSet.objects.filter(job_post__is_published=True)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def apply_for_job(request):
    """
    Apply for a job.
    - Only job seekers can apply
    - Cannot apply for the same job twice
    """
    # Verify user is a job seeker
    if request.user.user_type != 'job_seeker':
        return Response({
            'error': 'Only job seekers can apply for jobs'
        }, status=status.HTTP_403_FORBIDDEN)
    
    user_id = request.data.get('user_account')
    job_id = request.data.get('job_post')
    
    # Security check: verify user is applying for themselves
    if str(request.user.id) != str(user_id):
        return Response({
            'error': 'You can only apply for jobs for yourself'
        }, status=status.HTTP_403_FORBIDDEN)
    
    # Check if already applied
    if JobPostActivity.objects.filter(user_account_id=user_id, job_post_id=job_id).exists():
        return Response({
            'error': 'You have already applied for this job'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    # Verify the job exists and is active
    try:
        job = JobPost.objects.get(id=job_id, is_published=True, is_active=True)
    except JobPost.DoesNotExist:
        return Response({
            'error': 'Job not found or not available'
        }, status=status.HTTP_404_NOT_FOUND)
    
    serializer = JobPostActivitySerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response({
            'message': 'Application submitted successfully',
            'data': serializer.data
        }, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def job_applications(request, job_id):
    """
    Get all applications for a specific job.
    - Company owners can view applications to their jobs
    - Admins can view all applications
    """
    try:
        job = JobPost.objects.get(id=job_id)
    except JobPost.DoesNotExist:
        return Response({
            'error': 'Job not found'
        }, status=status.HTTP_404_NOT_FOUND)
    
    # Security check: verify user can access these applications
    if not (request.user.is_staff or request.user.is_superuser or 
            job.company.user_account.id == request.user.id):
        return Response({
            'error': 'You do not have permission to view these applications'
        }, status=status.HTTP_403_FORBIDDEN)
    
    applications = JobPostActivity.objects.filter(job_post_id=job_id)
    serializer = JobPostActivitySerializer(applications, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_applications(request, user_id):
    """
    Get all applications by a specific user.
    - Users can view their own applications
    - Admins can view any user's applications
    """
    # Security check: verify user can access these applications
    if not (request.user.is_staff or request.user.is_superuser or 
            str(request.user.id) == str(user_id)):
        return Response({
            'error': 'You do not have permission to view these applications'
        }, status=status.HTTP_403_FORBIDDEN)
    
    applications = JobPostActivity.objects.filter(user_account_id=user_id)
    serializer = JobPostActivitySerializer(applications, many=True)
    return Response(serializer.data)