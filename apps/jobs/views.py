from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    inline_serializer,
)
from rest_framework import serializers as drf_serializers
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from apps.accounts.authentication import CustomJWTAuthentication
from . import services
from .filters import JobPostFilter
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


_ApplyRequestSerializer = inline_serializer(
    name='ApplyForJobRequest',
    fields={
        'user_account': drf_serializers.UUIDField(
            help_text='Must match the authenticated user; preserves the existing API contract.',
        ),
        'job_post': drf_serializers.UUIDField(),
        'cover_letter': drf_serializers.CharField(
            required=False, allow_blank=True,
        ),
    },
)

_ApplyResponseSerializer = inline_serializer(
    name='ApplyForJobResponse',
    fields={
        'message': drf_serializers.CharField(),
        'data': JobPostActivitySerializer(),
    },
)

_JobsErrorSerializer = inline_serializer(
    name='JobsError', fields={'error': drf_serializers.CharField()},
)


class BurstRateThrottle(UserRateThrottle):
    """Per-user burst ceiling for write-heavy endpoints.

    Inherits UserRateThrottle so anonymous requests are not burst-throttled
    (get_cache_key returns None for anon). Anon traffic is bounded by the
    default AnonRateThrottle (100/day).
    """
    scope = 'burst'

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
    - Authenticated users (companies) can create locations
    - Admins can manage all locations
    """
    queryset = JobLocation.objects.all()
    serializer_class = JobLocationSerializer
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]


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
    # Layered: anon ceiling + per-user daily + per-user burst.
    # Order matters only for the response header DRF sets on 429.
    throttle_classes = [AnonRateThrottle, UserRateThrottle, BurstRateThrottle]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = JobPostFilter
    search_fields = ['job_title', 'job_description', 'company__company_name']
    ordering_fields = ['created_at', 'salary_max', 'salary_min', 'deadline_date']
    ordering = ['-created_at']

    def get_queryset(self):
        """Admins → all; company → their own (published + drafts); else → published."""
        qs = JobPost.objects.with_related()
        user = self.request.user
        if user.is_staff or user.is_superuser:
            return qs
        if user.is_authenticated and user.user_type == 'company':
            return qs.for_company(user)
        return qs.published()
    
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
        """Admins → all; seekers → own; company → applications to their jobs; else → none."""
        qs = JobPostActivity.objects.with_related()
        user = self.request.user
        if user.is_staff or user.is_superuser:
            return qs
        if user.user_type == 'job_seeker':
            return qs.for_user(user)
        if user.user_type == 'company':
            return qs.for_company(user)
        return qs.none()


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
        """Admins → all; company → their jobs' skills; else → published-job skills."""
        qs = JobPostSkillSet.objects.with_related()
        user = self.request.user
        if user.is_staff or user.is_superuser:
            return qs
        if user.is_authenticated and user.user_type == 'company':
            return qs.for_company(user)
        return qs.for_published_jobs()


@extend_schema(
    request=_ApplyRequestSerializer,
    responses={
        201: _ApplyResponseSerializer,
        400: _JobsErrorSerializer,
        403: _JobsErrorSerializer,
        404: _JobsErrorSerializer,
        429: OpenApiResponse(description='Burst-throttled (60/min)'),
    },
    tags=['jobs'],
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([AnonRateThrottle, UserRateThrottle, BurstRateThrottle])
def apply_for_job(request):
    """Apply for a job. Seekers only; cannot apply twice."""
    try:
        activity = services.apply_for_job(
            request.user,
            request.data.get('job_post'),
            cover_letter=request.data.get('cover_letter', ''),
            user_account_id=request.data.get('user_account'),
        )
    except services.InvalidApplicantError as e:
        return Response({'error': str(e)}, status=status.HTTP_403_FORBIDDEN)
    except services.JobNotAvailableError:
        return Response({'error': 'Job not found or not available'},
                        status=status.HTTP_404_NOT_FOUND)
    except services.AlreadyAppliedError:
        return Response({'error': 'You have already applied for this job'},
                        status=status.HTTP_400_BAD_REQUEST)

    return Response({
        'message': 'Application submitted successfully',
        'data': JobPostActivitySerializer(activity).data,
    }, status=status.HTTP_201_CREATED)


@extend_schema(
    responses={
        200: JobPostActivitySerializer(many=True),
        403: _JobsErrorSerializer,
        404: _JobsErrorSerializer,
    },
    tags=['jobs'],
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def job_applications(request, job_id):
    """Applications for a job. Admins and the job's company owner only."""
    try:
        apps_qs = services.applications_for_job(request.user, job_id)
    except services.JobNotFoundError:
        return Response({'error': 'Job not found'},
                        status=status.HTTP_404_NOT_FOUND)
    except services.DashboardPermissionError as e:
        return Response({'error': str(e)}, status=status.HTTP_403_FORBIDDEN)
    return Response(JobPostActivitySerializer(apps_qs, many=True).data)


@extend_schema(
    responses={
        200: JobPostActivitySerializer(many=True),
        403: _JobsErrorSerializer,
    },
    tags=['jobs'],
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_applications(request, user_id):
    """Applications by a user. Self or admin only."""
    try:
        apps_qs = services.applications_for_user(request.user, user_id)
    except services.DashboardPermissionError as e:
        return Response({'error': str(e)}, status=status.HTTP_403_FORBIDDEN)
    return Response(JobPostActivitySerializer(apps_qs, many=True).data)