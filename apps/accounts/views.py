from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from .models import UserAccount
from .serializers import UserAccountSerializer

# Create your views here.
# ViewSets for CRUD operations
class UserAccountViewSet(viewsets.ModelViewSet):
    """API for managing user accounts"""
    queryset = UserAccount.objects.all()
    serializer_class = UserAccountSerializer

# Registration endpoint
@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    """Register a new user account"""
    serializer = UserAccountSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save()
        return Response({
            'message': 'User created successfully',
            'user_id': str(user.id),
            'email': user.email,
            'user_type': user.user_type
        }, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# Login endpoint
@api_view(['POST'])
@permission_classes([AllowAny])
def login(request):
    """Simple login endpoint"""
    email = request.data.get('email')
    password = request.data.get('password')
    
    if not email or not password:
        return Response({
            'error': 'Email and password are required'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        user = UserAccount.objects.get(email=email)
        # Simple password check (in production, use proper hashing)
        if user.password == password:
            return Response({
                'message': 'Login successful',
                'user_id': str(user.id),
                'email': user.email,
                'user_type': user.user_type
            }, status=status.HTTP_200_OK)
        else:
            return Response({
                'error': 'Invalid credentials'
            }, status=status.HTTP_401_UNAUTHORIZED)
    except UserAccount.DoesNotExist:
        return Response({
            'error': 'Invalid credentials'
        }, status=status.HTTP_401_UNAUTHORIZED)