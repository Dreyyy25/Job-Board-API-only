"""Thin dispatchers: validate input, call the service, translate exceptions."""
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

from jobApp.throttling import BurstRateThrottle

from . import services
from .throttling import AIRateThrottle
from .exceptions import (
    AIProviderError,
    AIQuotaExceededError,
    AIResponseInvalidError,
    CompanyProfileMissingError,
    InvalidResumeFileError,
    JobPostNotFoundError,
    NoApplicantsError,
    ScreeningPermissionError,
)
from .permissions import IsCompanyUser, IsCompanyUserOrAdmin, IsSeekerUser
from .serializers import JobPostAssistRequestSerializer, ResumeImportRequestSerializer

_AIErrorSerializer = inline_serializer(
    name='AIError', fields={'error': drf_serializers.CharField()},
)

_SuggestedSkillSerializer = inline_serializer(
    name='SuggestedSkill',
    fields={
        'skill_set_id': drf_serializers.UUIDField(),
        'skill_name': drf_serializers.CharField(),
        'skill_level': drf_serializers.CharField(),
        'is_required': drf_serializers.BooleanField(),
    },
)

_JobPostDraftSerializer = inline_serializer(
    name='JobPostDraftResponse',
    fields={
        'job_title': drf_serializers.CharField(),
        'job_description': drf_serializers.CharField(),
        # inline_serializer returns an instance; recover the class to build the many=True list
        'suggested_skills': type(_SuggestedSkillSerializer)(many=True),
    },
)


@extend_schema(
    request=JobPostAssistRequestSerializer,
    responses={
        200: _JobPostDraftSerializer,
        400: _AIErrorSerializer,
        401: _AIErrorSerializer,
        403: _AIErrorSerializer,
        429: _AIErrorSerializer,
        502: _AIErrorSerializer,
    },
    tags=['ai'],
)
@api_view(['POST'])
@permission_classes([IsCompanyUser])
@throttle_classes([AnonRateThrottle, UserRateThrottle, BurstRateThrottle, AIRateThrottle])
def job_post_assist(request):
    """Draft a job post from rough notes. Returns a draft — creates nothing."""
    serializer = JobPostAssistRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        draft = services.generate_job_post_draft(
            request.user,
            notes=serializer.validated_data['notes'],
            job_type=serializer.validated_data.get('job_type_id'),
            location_hint=serializer.validated_data.get('location_hint', ''),
        )
    except CompanyProfileMissingError:
        return Response(
            {'error': 'You must complete your company profile before using the AI writer'},
            status=status.HTTP_400_BAD_REQUEST)
    except AIQuotaExceededError:
        return Response({'error': 'AI provider quota exceeded — try again later'},
                        status=status.HTTP_429_TOO_MANY_REQUESTS)
    except (AIProviderError, AIResponseInvalidError):
        return Response({'error': 'AI provider unavailable — try again later'},
                        status=status.HTTP_502_BAD_GATEWAY)
    return Response(draft)


_EducationEntrySerializer = inline_serializer(
    name='ResumeEducationEntry',
    fields={
        'institute_university_name': drf_serializers.CharField(),
        'degree_type': drf_serializers.CharField(allow_null=True),
        'field_of_study': drf_serializers.CharField(allow_blank=True),
        'academic_details': drf_serializers.CharField(allow_blank=True),
        'percentage': drf_serializers.FloatField(allow_null=True),
        'start_date': drf_serializers.CharField(allow_null=True),
        'end_date': drf_serializers.CharField(allow_null=True),
    },
)

_ExperienceEntrySerializer = inline_serializer(
    name='ResumeExperienceEntry',
    fields={
        'company_name': drf_serializers.CharField(),
        'position': drf_serializers.CharField(),
        'description': drf_serializers.CharField(allow_blank=True),
        'job_location_city': drf_serializers.CharField(allow_blank=True),
        'job_location_country': drf_serializers.CharField(allow_blank=True),
        'start_date': drf_serializers.CharField(allow_null=True),
        'end_date': drf_serializers.CharField(allow_null=True),
    },
)

_ResumeSkillSerializer = inline_serializer(
    name='ResumeSkillOut',
    fields={
        'skill_set_id': drf_serializers.UUIDField(),
        'skill_name': drf_serializers.CharField(),
        'skill_level': drf_serializers.CharField(),
    },
)

_ResumeImportResponseSerializer = inline_serializer(
    name='ResumeImportResponse',
    fields={
        # inline_serializer returns an instance; recover the class to build the many=True list
        'education': type(_EducationEntrySerializer)(many=True),
        'experience': type(_ExperienceEntrySerializer)(many=True),
        'skills': type(_ResumeSkillSerializer)(many=True),
        'new_skill_suggestions': drf_serializers.ListField(
            child=drf_serializers.CharField()),
    },
)


@extend_schema(
    request=ResumeImportRequestSerializer,
    responses={
        200: _ResumeImportResponseSerializer,
        400: _AIErrorSerializer,
        401: _AIErrorSerializer,
        403: _AIErrorSerializer,
        429: _AIErrorSerializer,
        502: _AIErrorSerializer,
    },
    tags=['ai'],
)
@api_view(['POST'])
@permission_classes([IsSeekerUser])
@throttle_classes([AnonRateThrottle, UserRateThrottle, BurstRateThrottle, AIRateThrottle])
def resume_import(request):
    """Extract a structured draft from a resume. Returns a draft — creates nothing."""
    serializer = ResumeImportRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        draft = services.extract_resume(
            request.user,
            text=serializer.validated_data.get('text', ''),
            file=serializer.validated_data.get('file'),
        )
    except InvalidResumeFileError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except AIQuotaExceededError:
        return Response({'error': 'AI provider quota exceeded — try again later'},
                        status=status.HTTP_429_TOO_MANY_REQUESTS)
    except (AIProviderError, AIResponseInvalidError):
        return Response({'error': 'AI provider unavailable — try again later'},
                        status=status.HTTP_502_BAD_GATEWAY)
    return Response(draft)


_ScreenedCandidateSerializer = inline_serializer(
    name='ScreenedCandidate',
    fields={
        'application_id': drf_serializers.UUIDField(),
        'applicant_id': drf_serializers.UUIDField(),
        'applicant_name': drf_serializers.CharField(allow_blank=True),
        'score': drf_serializers.IntegerField(),
        'strengths': drf_serializers.ListField(child=drf_serializers.CharField()),
        'gaps': drf_serializers.ListField(child=drf_serializers.CharField()),
        'summary': drf_serializers.CharField(),
        'rank': drf_serializers.IntegerField(),
    },
)

_ScreeningResponseSerializer = inline_serializer(
    name='ScreeningReportResponse',
    fields={
        'job_post_id': drf_serializers.UUIDField(),
        'applicant_count': drf_serializers.IntegerField(),
        'truncated': drf_serializers.BooleanField(),
        'excluded_count': drf_serializers.IntegerField(),
        'generated_at': drf_serializers.DateTimeField(),
        'cached': drf_serializers.BooleanField(),
        # inline_serializer returns an instance; recover the class to build the many=True list
        'candidates': type(_ScreenedCandidateSerializer)(many=True),
    },
)


@extend_schema(
    request=None,
    parameters=[
        OpenApiParameter(
            name='refresh', type=bool, location=OpenApiParameter.QUERY, required=False,
            description='Force a fresh screening run instead of returning the cached report.'),
    ],
    responses={
        200: _ScreeningResponseSerializer,
        401: _AIErrorSerializer,
        403: _AIErrorSerializer,
        404: _AIErrorSerializer,
        409: _AIErrorSerializer,
        429: _AIErrorSerializer,
        502: _AIErrorSerializer,
    },
    tags=['ai'],
)
@api_view(['POST'])
@permission_classes([IsCompanyUserOrAdmin])
@throttle_classes([AnonRateThrottle, UserRateThrottle, BurstRateThrottle, AIRateThrottle])
def screen_applicants(request, job_post_id):
    """Score and rank this job post's applicants. Cached until a newer application arrives."""
    refresh = request.query_params.get('refresh', '').lower() in ('1', 'true', 'yes')
    try:
        report = services.screen_applicants(
            request.user, job_post_id=job_post_id, refresh=refresh)
    except JobPostNotFoundError:
        return Response({'error': 'Job post not found'},
                        status=status.HTTP_404_NOT_FOUND)
    except ScreeningPermissionError:
        return Response({'error': 'You do not have access to this job post'},
                        status=status.HTTP_403_FORBIDDEN)
    except NoApplicantsError:
        return Response({'error': 'This job post has no applicants to screen'},
                        status=status.HTTP_409_CONFLICT)
    except AIQuotaExceededError:
        return Response({'error': 'AI provider quota exceeded — try again later'},
                        status=status.HTTP_429_TOO_MANY_REQUESTS)
    except (AIProviderError, AIResponseInvalidError):
        return Response({'error': 'AI provider unavailable — try again later'},
                        status=status.HTTP_502_BAD_GATEWAY)
    return Response(report)
