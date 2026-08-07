from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import (
    ObjectDoesNotExist,
    ValidationError as DjangoValidationError,
)
from drf_spectacular.utils import (
    OpenApiResponse,
    extend_schema,
    inline_serializer,
)
from rest_framework import serializers as drf_serializers
from rest_framework import viewsets, status
from rest_framework.decorators import (
    api_view,
    parser_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle, UserRateThrottle
from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.views import TokenRefreshView

from . import services
from .models import UserAccount
from .serializers import UserAccountSerializer, RegisterSerializer
from .authentication import CustomJWTAuthentication
from .cookies import delete_refresh_cookie, set_refresh_cookie
from .permissions import IsOwnerOrAdmin


_TokensSerializer = inline_serializer(
    name='AuthTokens',
    fields={
        'access': drf_serializers.CharField(),
    },
)

_AuthResponseSerializer = inline_serializer(
    name='AuthResponse',
    fields={
        'message': drf_serializers.CharField(),
        'user': inline_serializer(
            name='AuthUser',
            fields={
                'id': drf_serializers.UUIDField(),
                'email': drf_serializers.EmailField(),
                'user_type': drf_serializers.CharField(),
            },
        ),
        'tokens': _TokensSerializer,
        'profile': drf_serializers.JSONField(
            help_text='SeekerProfile or Company payload (signal-created).',
            allow_null=True,
        ),
    },
)

_LoginRequestSerializer = inline_serializer(
    name='LoginRequest',
    fields={
        'email': drf_serializers.EmailField(),
        'password': drf_serializers.CharField(write_only=True),
    },
)

_ErrorSerializer = inline_serializer(
    name='ErrorResponse',
    fields={'error': drf_serializers.CharField()},
)

_RefreshResponseSerializer = inline_serializer(
    name='TokenRefreshResponse',
    fields={'access': drf_serializers.CharField()},
)

_RefreshErrorSerializer = inline_serializer(
    name='TokenRefreshError',
    fields={'detail': drf_serializers.CharField()},
)


class RegisterThrottle(AnonRateThrottle):
    scope = 'register'


class LoginThrottle(AnonRateThrottle):
    scope = 'login'


class ChangePasswordThrottle(UserRateThrottle):
    """Keyed by authenticated user (login is anon/IP-keyed, which no-ops here).

    Reuses the 'login' rate (10/min): both endpoints guard password guessing.
    """

    scope = 'login'


# Create your views here.
# ViewSets for CRUD operations
class UserAccountViewSet(viewsets.ModelViewSet):
    """API for managing user accounts"""

    queryset = UserAccount.objects.all()
    serializer_class = UserAccountSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]
    authentication_classes = [CustomJWTAuthentication]

    def get_queryset(self):
        """
        Filter queryset based on user permissions:
        - Admins see all users
        - Regular users only see their own account
        """
        user = self.request.user

        # Admins can see all accounts
        if user.is_staff or user.is_superuser:
            return UserAccount.objects.all()

        # Regular users only see their own account
        return UserAccount.objects.filter(id=user.id)

    def perform_create(self, serializer):
        """Override create to hash password"""
        password = serializer.validated_data.get('password')
        if password:
            serializer.save(password=make_password(password))
        else:
            serializer.save()

    def perform_update(self, serializer):
        """password is create-only; UserAccountSerializer.validate() rejects
        it on update, so there is nothing left to hash here."""
        serializer.save()


# Registration endpoint
def _serialize_profile(user):
    """Serialize the signal-created profile for the register response.

    Lazy imports keep apps.accounts at the root of the dependency graph
    (no module-top cross-app imports). Uses getattr for defense in depth
    — never 500s if the reverse OneToOne is missing.
    """
    if user.user_type == 'job_seeker':
        from apps.seekers.serializers import SeekerProfileSerializer

        profile = getattr(user, 'seeker_profile', None)
        return SeekerProfileSerializer(profile).data if profile else None
    if user.user_type == 'company':
        from apps.companies.serializers import CompanySerializer

        profile = getattr(user, 'company_profile', None)
        return CompanySerializer(profile).data if profile else None
    return None


@extend_schema(
    request=RegisterSerializer,
    responses={
        201: _AuthResponseSerializer,
        400: OpenApiResponse(description='Validation error or weak password'),
        429: OpenApiResponse(description='Rate limited (5/min)'),
    },
    tags=['accounts'],
)
@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([RegisterThrottle])
@parser_classes([JSONParser])
def register(request):
    """Register a new user account (JSON bodies only).

    JSON-only is a login-CSRF mitigation: this view is AllowAny, DRF wraps
    `@api_view` in `csrf_exempt`, and it sets an httpOnly refresh cookie.
    Accepting form/multipart bodies would let a cross-site HTML form plant
    an attacker's refresh token in the victim's browser. HTML forms cannot
    send `application/json`, and a cross-site fetch that does triggers a
    CORS preflight that fails.
    """
    serializer = RegisterSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data
    try:
        user, tokens = services.register_user(
            email=data['email'],
            password=data['password'],
            user_type=data['user_type'],
            **{k: v for k, v in data.items() if k not in {'email', 'password', 'user_type'}},
        )
    except DjangoValidationError as e:
        return Response({'password': list(e.messages)}, status=status.HTTP_400_BAD_REQUEST)

    refresh_token = tokens.pop('refresh')
    response = Response(
        {
            'message': 'User created successfully',
            'user': {
                'id': str(user.id),
                'email': user.email,
                'user_type': user.user_type,
            },
            'tokens': tokens,
            'profile': _serialize_profile(user),
        },
        status=status.HTTP_201_CREATED,
    )
    set_refresh_cookie(response, refresh_token)
    return response


# Login endpoint
@extend_schema(
    request=_LoginRequestSerializer,
    responses={
        200: _AuthResponseSerializer,
        400: _ErrorSerializer,
        401: _ErrorSerializer,
        429: OpenApiResponse(description='Rate limited (10/min)'),
    },
    tags=['accounts'],
)
@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([LoginThrottle])
@parser_classes([JSONParser])
def login(request):
    """Login for UserAccount model (JSON bodies only).

    See `register` — JSON-only closes the login-CSRF / refresh-cookie
    fixation hole on this AllowAny, csrf-exempt, cookie-setting view.
    """
    email = request.data.get('email')
    password = request.data.get('password')

    if not email or not password:
        return Response({'error': 'Email and password are required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        user, tokens = services.login_user(email, password)
    except services.InvalidCredentialsError:
        return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)

    refresh_token = tokens.pop('refresh')
    response = Response(
        {
            'message': 'Login successful',
            'user': {
                'id': str(user.id),
                'email': user.email,
                'user_type': user.user_type,
            },
            'tokens': tokens,
        },
        status=status.HTTP_200_OK,
    )
    set_refresh_cookie(response, refresh_token)
    return response


# Current user's account endpoint
@extend_schema(
    methods=['GET'],
    responses={200: UserAccountSerializer},
    tags=['accounts'],
)
@extend_schema(
    methods=['PUT', 'PATCH'],
    request=UserAccountSerializer,
    responses={200: UserAccountSerializer, 400: _ErrorSerializer},
    tags=['accounts'],
)
@api_view(['GET', 'PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def me(request):
    """Get or update current user's account"""
    user = request.user

    if request.method == 'GET':
        serializer = UserAccountSerializer(user)
        return Response(serializer.data)

    elif request.method in ['PUT', 'PATCH']:
        partial = request.method == 'PATCH'
        serializer = UserAccountSerializer(user, data=request.data, partial=partial)

        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# Change-password endpoint
@extend_schema(
    request=inline_serializer(
        name='ChangePasswordRequest',
        fields={
            'current_password': drf_serializers.CharField(),
            'new_password': drf_serializers.CharField(),
        },
    ),
    responses={
        204: OpenApiResponse(description='Password changed'),
        400: OpenApiResponse(description='Validation error'),
    },
    tags=['accounts'],
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([ChangePasswordThrottle])
@parser_classes([JSONParser])
def change_password(request):
    """Verify the current password, then set the new one (JSON bodies only).

    Mirrors login/register's JSON-only parser wiring for consistency across
    the accounts auth endpoints. Throttling is user-keyed (ChangePasswordThrottle)
    rather than login's anon/IP-keyed LoginThrottle: this view is
    IsAuthenticated-only, and AnonRateThrottle no-ops for authenticated
    requests, so it would not actually guard against password guessing here.
    """
    current = request.data.get('current_password') or ''
    new = request.data.get('new_password') or ''
    if not request.user.check_password(current):
        return Response({'current_password': ['Incorrect password.']}, status=status.HTTP_400_BAD_REQUEST)
    try:
        validate_password(new, user=request.user)
    except DjangoValidationError as e:
        return Response({'new_password': list(e.messages)}, status=status.HTTP_400_BAD_REQUEST)
    request.user.password = make_password(new)
    request.user.save(update_fields=['password'])
    return Response(status=status.HTTP_204_NO_CONTENT)


# Logout endpoint
@extend_schema(
    request=None,
    responses={
        205: OpenApiResponse(description='Token blacklisted'),
        400: _ErrorSerializer,
    },
    tags=['accounts'],
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout(request):
    """Blacklist the refresh token cookie and clear it."""
    cookie_name = settings.AUTH_REFRESH_COOKIE['NAME']
    refresh_token = request.COOKIES.get(cookie_name)
    try:
        services.logout_user(refresh_token)
    except services.InvalidTokenError as e:
        msg = str(e) or 'invalid or expired refresh token'
        response = Response({'error': msg}, status=status.HTTP_400_BAD_REQUEST)
        delete_refresh_cookie(response)
        return response
    response = Response(status=status.HTTP_205_RESET_CONTENT)
    delete_refresh_cookie(response)
    return response


# Token refresh endpoint
class CookieTokenRefreshView(TokenRefreshView):
    """Reads the refresh token from the httpOnly cookie (never the body)
    and writes the rotated refresh token back to that same cookie.

    ROTATE_REFRESH_TOKENS / BLACKLIST_AFTER_ROTATION are enabled in
    SIMPLE_JWT, so TokenRefreshSerializer.validated_data comes back with
    both `access` and `refresh` — we move `refresh` into the cookie and
    keep only `access` in the response body.
    """

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'token_refresh'

    @extend_schema(
        request=None,
        responses={
            200: _RefreshResponseSerializer,
            401: _RefreshErrorSerializer,
            429: OpenApiResponse(description='Rate limited'),
        },
        tags=['accounts'],
    )
    def post(self, request, *args, **kwargs):
        cookie_name = settings.AUTH_REFRESH_COOKIE['NAME']
        refresh_token = request.COOKIES.get(cookie_name)
        if not refresh_token:
            return Response(
                {'detail': 'Refresh token cookie not found.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        serializer = self.get_serializer(data={'refresh': refresh_token})
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as e:
            raise InvalidToken(e.args[0]) from e
        except ObjectDoesNotExist as e:
            # simplejwt's TokenRefreshSerializer.validate looks the user up
            # with an unguarded .get(), so a signature-valid token whose user
            # row was deleted raises DoesNotExist — not TokenError — and DRF
            # would render it as a 500. A vanished user is an invalid token.
            raise InvalidToken() from e

        data = dict(serializer.validated_data)
        rotated_refresh = data.pop('refresh', None)
        response = Response(data, status=status.HTTP_200_OK)
        if rotated_refresh:
            set_refresh_cookie(response, rotated_refresh)
        return response
