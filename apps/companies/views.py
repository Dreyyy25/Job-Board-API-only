from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.accounts.authentication import CustomJWTAuthentication
from .models import BusinessStream, Company, CompanyImages
from .serializers import BusinessStreamSerializer, CompanySerializer, CompanyImagesSerializer
from .permissions import (
    IsAdminOrReadOnly,
    IsCompanyOwnerOrAdmin,
    IsCompanyOwnerForImages
)

# Create your views here.
class BusinessStreamViewSet(viewsets.ModelViewSet):
    """
    API for business categories/industries.
    - Everyone can view business streams
    - Only admins can create/update/delete business streams
    """
    queryset = BusinessStream.objects.all()
    serializer_class = BusinessStreamSerializer
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAdminOrReadOnly]


class CompanyViewSet(viewsets.ModelViewSet):
    """
    API for company profiles.
    - Authenticated users can view all companies
    - Company owners can create and manage their own company
    - Admins can manage all companies
    """
    queryset = Company.objects.all()
    serializer_class = CompanySerializer
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsCompanyOwnerOrAdmin]
    
    def get_queryset(self):
        """
        Filter queryset based on user type:
        - Admins see all companies
        - Company users see only their own company
        - Job seekers see all active companies
        """
        user = self.request.user
        base = (
            Company.objects
            .select_related('user_account', 'business_stream')
            .prefetch_related('images')
        )
        if user.is_staff or user.is_superuser:
            return base
        elif user.user_type == 'company':
            return base.filter(user_account=user)
        else:
            return base.filter(status='active')
    
    def perform_create(self, serializer):
        """Automatically assign the current user as the company owner.

        Only users with user_type='company' may create companies — the
        Company.user_account FK limit_choices_to is only enforced in
        admin forms, not the ORM, so we guard here explicitly.
        """
        if self.request.user.user_type != 'company':
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only company users can create companies")
        serializer.save(user_account=self.request.user)


class CompanyImagesViewSet(viewsets.ModelViewSet):
    """
    API for company images.
    - Everyone can view company images
    - Company owners can upload/manage their company's images
    - Admins can manage all images
    """
    queryset = CompanyImages.objects.all()
    serializer_class = CompanyImagesSerializer
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsCompanyOwnerForImages]
    
    def get_queryset(self):
        """
        Filter queryset based on user:
        - Admins see all images
        - Company users see only their company's images
        - Others see images from active companies
        """
        user = self.request.user
        base = CompanyImages.objects.select_related('company', 'company__user_account')
        if user.is_staff or user.is_superuser:
            return base
        elif user.user_type == 'company':
            return base.filter(company__user_account=user)
        else:
            return base.filter(company__status='active')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def company_dashboard(request, user_id):
    """
    Get company data for dashboard.
    - Company owners can access their own dashboard
    - Admins can access any company dashboard
    """
    # Security check: verify user can access this dashboard
    if not (request.user.is_staff or request.user.is_superuser or str(request.user.id) == str(user_id)):
        return Response({
            'error': 'You do not have permission to access this dashboard'
        }, status=status.HTTP_403_FORBIDDEN)
    
    try:
        company = Company.objects.get(user_account_id=user_id)
        images = CompanyImages.objects.filter(company=company)
        
        return Response({
            'company': CompanySerializer(company).data,
            'images': CompanyImagesSerializer(images, many=True).data,
        })
    except Company.DoesNotExist:
        return Response({
            'error': 'Company not found'
        }, status=status.HTTP_404_NOT_FOUND)