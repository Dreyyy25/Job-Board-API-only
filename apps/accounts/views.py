from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from django.contrib.auth.hashers import make_password, check_password

from .models import UserAccount
from .serializers import UserAccountSerializer
from .jwt_authentication import get_tokens_for_user

# Create your views here.
# ViewSets for CRUD operations
class UserAccountViewSet(viewsets.ModelViewSet):
    """API for managing user accounts"""
    queryset = UserAccount.objects.all()
    serializer_class = UserAccountSerializer
    permission_classes = [IsAuthenticated]

# Registration endpoint
@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    """Register a new user account with JWT tokens"""
    serializer = UserAccountSerializer(data=request.data)
    if serializer.is_valid():
        # Hash password before saving
        validated_data = serializer.validated_data
        validated_data['password'] = make_password(validated_data['password'])
        
        user = UserAccount.objects.create(**validated_data)
        
        # Generate JWT tokens
        tokens = get_tokens_for_user(user)
        
        return Response({
            'message': 'User created successfully',
            'user': {
                'id': str(user.id),
                'email': user.email,
                'user_type': user.user_type
            },
            'tokens': tokens
        }, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# Login endpoint
@api_view(['POST'])
@permission_classes([AllowAny])
def login(request):
    """JWT-based login endpoint"""
    email = request.data.get('email')
    password = request.data.get('password')
    
    if not email or not password:
        return Response({
            'error': 'Email and password are required'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        user = UserAccount.objects.get(email=email)
        
        # Check password (now properly hashed)
        if check_password(password, user.password):
            # Generate JWT tokens
            tokens = get_tokens_for_user(user)
            
            return Response({
                'message': 'Login successful',
                'user': {
                    'id': str(user.id),
                    'email': user.email,
                    'user_type': user.user_type
                },
                'tokens': tokens
            }, status=status.HTTP_200_OK)
        else:
            return Response({
                'error': 'Invalid credentials'
            }, status=status.HTTP_401_UNAUTHORIZED)
    except UserAccount.DoesNotExist:
        return Response({
            'error': 'Invalid credentials'
        }, status=status.HTTP_401_UNAUTHORIZED)