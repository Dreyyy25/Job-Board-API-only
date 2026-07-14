"""Thin dispatchers: validate input, call the service, translate exceptions."""
from drf_spectacular.utils import extend_schema, inline_serializer
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
)
from .permissions import IsCompanyUser
from .serializers import JobPostAssistRequestSerializer

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
