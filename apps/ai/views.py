"""Thin dispatchers: validate input, call the service, translate exceptions."""

from drf_spectacular.utils import (
    OpenApiParameter,
    PolymorphicProxySerializer,
    extend_schema,
    inline_serializer,
)
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

from jobApp.throttling import BurstRateThrottle

from . import services
from .exceptions import (
    AgentLimitExceededError,
    AIProviderError,
    AIQuotaExceededError,
    AIResponseInvalidError,
    CompanyProfileMissingError,
    ConversationExhaustedError,
    ConversationNotFoundError,
    InvalidResumeFileError,
    JobPostNotFoundError,
    NoApplicantsError,
    ScreeningPermissionError,
)
from .permissions import IsCompanyUser, IsCompanyUserOrAdmin, IsSeekerUser
from .serializers import (
    ChatRequestSerializer,
    JobPostAssistRequestSerializer,
    ResumeImportRequestSerializer,
)
from .throttling import AIChatRateThrottle, AIRateThrottle

# Two error envelopes reach clients, and which one you get depends on WHERE the
# request died:
#   {'error': ...}  — raised by these views translating a domain exception.
#   {'detail': ...} — raised by DRF itself, before the view body runs: the
#                     permission class (401/403) and the throttles (429).
# Declaring only the first would make the schema lie about every DRF-generated
# response, so the statuses that can produce either are declared as a oneOf.
_AIErrorSerializer = inline_serializer(
    name='AIError',
    fields={'error': drf_serializers.CharField()},
)

_AIDetailErrorSerializer = inline_serializer(
    name='AIDetailError',
    fields={'detail': drf_serializers.CharField()},
)

_AIEitherErrorSerializer = PolymorphicProxySerializer(
    component_name='AIErrorOrDetail',
    serializers=[_AIErrorSerializer, _AIDetailErrorSerializer],
    resource_type_field_name=None,
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
        401: _AIDetailErrorSerializer,
        403: _AIDetailErrorSerializer,
        429: _AIEitherErrorSerializer,
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
            status=status.HTTP_400_BAD_REQUEST,
        )
    except AIQuotaExceededError:
        return Response(
            {'error': 'AI provider quota exceeded — try again later'}, status=status.HTTP_429_TOO_MANY_REQUESTS
        )
    except (AIProviderError, AIResponseInvalidError):
        return Response({'error': 'AI provider unavailable — try again later'}, status=status.HTTP_502_BAD_GATEWAY)
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
        'new_skill_suggestions': drf_serializers.ListField(child=drf_serializers.CharField()),
    },
)


@extend_schema(
    request=ResumeImportRequestSerializer,
    responses={
        200: _ResumeImportResponseSerializer,
        400: _AIErrorSerializer,
        401: _AIDetailErrorSerializer,
        403: _AIDetailErrorSerializer,
        429: _AIEitherErrorSerializer,
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
        return Response(
            {'error': 'AI provider quota exceeded — try again later'}, status=status.HTTP_429_TOO_MANY_REQUESTS
        )
    except (AIProviderError, AIResponseInvalidError):
        return Response({'error': 'AI provider unavailable — try again later'}, status=status.HTTP_502_BAD_GATEWAY)
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
            name='refresh',
            type=bool,
            location=OpenApiParameter.QUERY,
            required=False,
            description='Force a fresh screening run instead of returning the cached report.',
        ),
    ],
    responses={
        200: _ScreeningResponseSerializer,
        401: _AIDetailErrorSerializer,
        # 403 has two shapes here: the permission class rejects a non-company
        # user with {'detail'}, while ScreeningPermissionError — a company that
        # does not own this post — is translated below into {'error'}.
        403: _AIEitherErrorSerializer,
        404: _AIErrorSerializer,
        409: _AIErrorSerializer,
        429: _AIEitherErrorSerializer,
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
        report = services.screen_applicants(request.user, job_post_id=job_post_id, refresh=refresh)
    except JobPostNotFoundError:
        return Response({'error': 'Job post not found'}, status=status.HTTP_404_NOT_FOUND)
    except ScreeningPermissionError:
        return Response({'error': 'You do not have access to this job post'}, status=status.HTTP_403_FORBIDDEN)
    except NoApplicantsError:
        return Response({'error': 'This job post has no applicants to screen'}, status=status.HTTP_409_CONFLICT)
    except AIQuotaExceededError:
        return Response(
            {'error': 'AI provider quota exceeded — try again later'}, status=status.HTTP_429_TOO_MANY_REQUESTS
        )
    except (AIProviderError, AIResponseInvalidError):
        return Response({'error': 'AI provider unavailable — try again later'}, status=status.HTTP_502_BAD_GATEWAY)
    return Response(report)


# `reply` is always assistant-produced and always passed through
# _sanitize_reply — html.escape(text, quote=False) — so `<`, `>`, and `&`
# arrive as `&lt;`, `&gt;`, `&amp;` entities. Markdown/HTML clients can render
# the string directly (the entities display as the literal characters);
# plain-text clients must entity-decode it exactly once before display.
_REPLY_HELP_TEXT = (
    "HTML-escaped (&lt;/&gt;/&amp; entities). Markdown/HTML clients can "
    "render this directly; plain-text clients must entity-decode it once "
    "and render the decoded result as text only — never insert it into "
    "HTML/the DOM, since markup that survived stripping is inert only "
    "while escaped."
)

# Unlike `reply`, transcript `content` mixes two roles that get DIFFERENT
# treatment in apps.ai.services.get_conversation_messages: 'assistant' rows go
# through the same _sanitize_reply/html.escape pass as a live reply, but
# 'user' rows are HumanMessage.text verbatim — never escaped, since it is the
# requester's own submitted text being played back to them. A client that
# entity-decodes or "renders directly" uniformly across roles will render the
# user's raw markup unescaped (self-XSS today, stored-XSS if a transcript
# ever reaches a second party) or corrupt literal `&`/`<` the user typed.
_TRANSCRIPT_CONTENT_HELP_TEXT = (
    "Escaping DIFFERS by role: assistant-role content is HTML-escaped "
    "(&lt;/&gt;/&amp; entities) by the server, same as the chat reply field — "
    "plain-text clients must entity-decode it once and render the decoded "
    "result as text only, never insert it into HTML/the DOM, since markup "
    "that survived stripping is inert only while escaped. "
    "user-role content is returned verbatim as originally submitted — NOT "
    "escaped. Clients must escape user-role content themselves before "
    "rendering it as HTML; do not entity-decode it."
)

_TITLE_HELP_TEXT = (
    "The first user message, truncated to 60 characters, returned verbatim "
    "— NOT HTML-escaped. Clients must escape it themselves before "
    "rendering as HTML, same as transcript user-role content."
)

_ChatResponseSerializer = inline_serializer(
    name='ChatResponse',
    fields={
        'conversation_id': drf_serializers.UUIDField(),
        'reply': drf_serializers.CharField(help_text=_REPLY_HELP_TEXT),
    },
)

_ConversationSerializer = inline_serializer(
    name='ChatConversation',
    fields={
        'id': drf_serializers.UUIDField(),
        'title': drf_serializers.CharField(help_text=_TITLE_HELP_TEXT),
        'created_at': drf_serializers.DateTimeField(),
    },
)

_TranscriptMessageSerializer = inline_serializer(
    name='ChatTranscriptMessage',
    fields={
        'role': drf_serializers.ChoiceField(choices=['user', 'assistant']),
        'content': drf_serializers.CharField(help_text=_TRANSCRIPT_CONTENT_HELP_TEXT),
    },
)

_TranscriptSerializer = inline_serializer(
    name='ChatTranscript',
    fields={
        'id': drf_serializers.UUIDField(),
        'title': drf_serializers.CharField(help_text=_TITLE_HELP_TEXT),
        'created_at': drf_serializers.DateTimeField(),
        # inline_serializer returns an instance; recover the class for many=True
        'messages': type(_TranscriptMessageSerializer)(many=True),
    },
)


@extend_schema(
    request=ChatRequestSerializer,
    responses={
        200: _ChatResponseSerializer,
        400: _AIErrorSerializer,
        401: _AIDetailErrorSerializer,
        403: _AIDetailErrorSerializer,
        404: _AIErrorSerializer,
        409: _AIErrorSerializer,
        429: _AIEitherErrorSerializer,
        502: _AIErrorSerializer,
        504: _AIErrorSerializer,
    },
    tags=['ai'],
)
@api_view(['POST'])
@permission_classes([IsSeekerUser])
@throttle_classes([AnonRateThrottle, UserRateThrottle, BurstRateThrottle, AIChatRateThrottle])
def chat(request):
    """One chat turn. The agent's tools are read-only — nothing is created."""
    serializer = ChatRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    conversation_id = serializer.validated_data.get('conversation_id')
    try:
        result = services.send_chat_message(
            request.user,
            message=serializer.validated_data['message'],
            conversation_id=str(conversation_id) if conversation_id else None,
        )
    except ConversationNotFoundError:
        return Response({'error': 'Conversation not found'}, status=status.HTTP_404_NOT_FOUND)
    except ConversationExhaustedError:
        # Deliberately NOT the 504: this thread can never answer again.
        return Response(
            {'error': 'This conversation has reached its limit — start a new one'}, status=status.HTTP_409_CONFLICT
        )
    except AgentLimitExceededError:
        return Response(
            {'error': 'The assistant took too long to answer — try a simpler question'},
            status=status.HTTP_504_GATEWAY_TIMEOUT,
        )
    except AIQuotaExceededError:
        return Response(
            {'error': 'AI provider quota exceeded — try again later'}, status=status.HTTP_429_TOO_MANY_REQUESTS
        )
    except (AIProviderError, AIResponseInvalidError):
        return Response({'error': 'AI provider unavailable — try again later'}, status=status.HTTP_502_BAD_GATEWAY)
    return Response(result)


@extend_schema(
    responses={
        200: type(_ConversationSerializer)(many=True),
        401: _AIDetailErrorSerializer,
        403: _AIDetailErrorSerializer,
        429: _AIDetailErrorSerializer,
    },
    tags=['ai'],
)
@api_view(['GET'])
@permission_classes([IsSeekerUser])
@throttle_classes([AnonRateThrottle, UserRateThrottle, BurstRateThrottle])
def list_conversations(request):
    """The requester's own chat threads, newest first. No LLM call."""
    return Response(services.list_conversations(request.user))


@extend_schema(
    methods=['GET'],
    responses={
        200: _TranscriptSerializer,
        401: _AIDetailErrorSerializer,
        403: _AIDetailErrorSerializer,
        404: _AIErrorSerializer,
        429: _AIDetailErrorSerializer,
    },
    tags=['ai'],
)
@extend_schema(
    methods=['DELETE'],
    responses={
        204: None,
        401: _AIDetailErrorSerializer,
        403: _AIDetailErrorSerializer,
        404: _AIErrorSerializer,
        429: _AIDetailErrorSerializer,
    },
    tags=['ai'],
)
@api_view(['GET', 'DELETE'])
@permission_classes([IsSeekerUser])
@throttle_classes([AnonRateThrottle, UserRateThrottle, BurstRateThrottle])
def conversation_detail(request, conversation_id):
    """GET the transcript, or DELETE the thread and its stored messages.

    Neither makes an LLM call.
    """
    try:
        if request.method == 'DELETE':
            services.delete_conversation(request.user, conversation_id=str(conversation_id))
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(services.get_conversation_messages(request.user, conversation_id=str(conversation_id)))
    except ConversationNotFoundError:
        return Response({'error': 'Conversation not found'}, status=status.HTTP_404_NOT_FOUND)
