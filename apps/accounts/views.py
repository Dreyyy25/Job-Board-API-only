from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated, BasePermission
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth.hashers import make_password, check_password
from django.utils import timezone

from .models import UserAccount
from .serializers import UserAccountSerializer
from .authentication import CustomJWTAuthentication

# Create your views here.
# ViewSets for CRUD operations
#FIXME: Create and move the custom permission to a separate file
#FIXME: Improve error handling and responses
class IsOwnerOrAdmin(BasePermission):
    """
    Custom permission to only allow users to access their own account,
    or allow admins to access all accounts.
    """
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated
    
    def has_object_permission(self, request, view, obj):
        if request.user.is_staff or request.user.is_superuser:
            return True
        
        return obj.id == request.user.id

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
@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    """Register a new user account"""
    serializer = UserAccountSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save()  # Password hashing handled by serializer
        
        # Generate tokens using built-in RefreshToken
        refresh = RefreshToken.for_user(user)
        refresh['user_id'] = str(user.id)
        refresh['email'] = user.email
        refresh['user_type'] = user.user_type
        
        return Response({
            'message': 'User created successfully',
            'user': {
                'id': str(user.id),
                'email': user.email,
                'user_type': user.user_type
            },
            'tokens': {
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            }
        }, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# Login endpoint
@api_view(['POST'])
@permission_classes([AllowAny])
def login(request):
    """Login for UserAccount model"""
    email = request.data.get('email')
    password = request.data.get('password')
    
    if not email or not password:
        return Response({
            'error': 'Email and password are required'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        user = UserAccount.objects.get(email=email)
        if check_password(password, user.password):
            user.last_login = timezone.now()
            user.save(update_fields=['last_login'])

            # Use built-in RefreshToken.for_user()
            refresh = RefreshToken.for_user(user)
            refresh['user_id'] = str(user.id)
            refresh['email'] = user.email
            refresh['user_type'] = user.user_type
            
            return Response({
                'message': 'Login successful',
                'user': {
                    'id': str(user.id),
                    'email': user.email,
                    'user_type': user.user_type
                },
                'tokens': {
                    'refresh': str(refresh),
                    'access': str(refresh.access_token),
                }
            }, status=status.HTTP_200_OK)
        else:
            return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)
    except UserAccount.DoesNotExist:
        return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)

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