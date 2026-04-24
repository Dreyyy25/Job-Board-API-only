from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.throttling import AnonRateThrottle
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from . import services
from .models import UserAccount
from .serializers import UserAccountSerializer, RegisterSerializer
from .authentication import CustomJWTAuthentication
from .permissions import IsOwnerOrAdmin


class RegisterThrottle(AnonRateThrottle):
    scope = 'register'


class LoginThrottle(AnonRateThrottle):
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
        """Override update to hash password if provided"""
        password = serializer.validated_data.get('password')
        if password:
            serializer.save(password=make_password(password))
        else:
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


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([RegisterThrottle])
def register(request):
    """Register a new user account."""
    serializer = RegisterSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data
    try:
        user, tokens = services.register_user(
            email=data['email'],
            password=data['password'],
            user_type=data['user_type'],
            **{k: v for k, v in data.items()
               if k not in {'email', 'password', 'user_type'}},
        )
    except DjangoValidationError as e:
        return Response({'password': list(e.messages)},
                        status=status.HTTP_400_BAD_REQUEST)

    return Response({
        'message': 'User created successfully',
        'user': {
            'id': str(user.id),
            'email': user.email,
            'user_type': user.user_type,
        },
        'tokens': tokens,
        'profile': _serialize_profile(user),
    }, status=status.HTTP_201_CREATED)


# Login endpoint
@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([LoginThrottle])
def login(request):
    """Login for UserAccount model."""
    email = request.data.get('email')
    password = request.data.get('password')

    if not email or not password:
        return Response({'error': 'Email and password are required'},
                        status=status.HTTP_400_BAD_REQUEST)

    try:
        user, tokens = services.login_user(email, password)
    except services.InvalidCredentialsError:
        return Response({'error': 'Invalid credentials'},
                        status=status.HTTP_401_UNAUTHORIZED)

    return Response({
        'message': 'Login successful',
        'user': {
            'id': str(user.id),
            'email': user.email,
            'user_type': user.user_type,
        },
        'tokens': tokens,
    }, status=status.HTTP_200_OK)

# Current user's account endpoint
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
            # Hash password if provided
            password = serializer.validated_data.get('password')
            if password:
                serializer.save(password=make_password(password))
            else:
                serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# Logout endpoint
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout(request):
    """Blacklist the supplied refresh token."""
    try:
        services.logout_user(request.data.get('refresh'))
    except services.InvalidTokenError as e:
        msg = str(e) or 'invalid or expired refresh token'
        return Response({'error': msg},
                        status=status.HTTP_400_BAD_REQUEST)
    return Response(status=status.HTTP_205_RESET_CONTENT)