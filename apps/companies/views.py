from drf_spectacular.utils import (
    extend_schema,
    inline_serializer,
)
from rest_framework import serializers as drf_serializers
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.accounts.authentication import CustomJWTAuthentication
from . import services
from .models import BusinessStream, Company, CompanyImages
from .serializers import BusinessStreamSerializer, CompanySerializer, CompanyImagesSerializer
from .permissions import IsAdminOrReadOnly, IsCompanyOwnerOrAdmin, IsCompanyOwnerForImages


_CompanyDashboardSerializer = inline_serializer(
    name='CompanyDashboard',
    fields={
        'company': CompanySerializer(),
        'images': CompanyImagesSerializer(many=True),
    },
)

_CompaniesErrorSerializer = inline_serializer(
    name='CompaniesError',
    fields={'error': drf_serializers.CharField()},
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
        """Admins → all; company → their own; else → active companies."""
        qs = Company.objects.with_related()
        user = self.request.user
        if user.is_staff or user.is_superuser:
            return qs
        if user.user_type == 'company':
            return qs.for_user(user)
        return qs.active()

    def perform_create(self, serializer):
        """Automatically assign the current user as the company owner.

        After the Tier 1 signal lands, every company user has an
        auto-created Company. Pre-check existence and 400 here instead of
        letting the OneToOne IntegrityError turn into a 500.
        """
        from rest_framework.exceptions import PermissionDenied, ValidationError

        if self.request.user.user_type != 'company':
            raise PermissionDenied("Only company users can create companies")
        if Company.objects.filter(user_account=self.request.user).exists():
            raise ValidationError({'detail': 'Profile already exists. Use PATCH to update.'})
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
        """Admins → all; company → their own; else → active companies' images."""
        qs = CompanyImages.objects.with_related()
        user = self.request.user
        if user.is_staff or user.is_superuser:
            return qs
        if user.user_type == 'company':
            return qs.for_company_user(user)
        return qs.for_active_companies()


@extend_schema(
    responses={
        200: _CompanyDashboardSerializer,
        403: _CompaniesErrorSerializer,
        404: _CompaniesErrorSerializer,
    },
    tags=['companies'],
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def company_dashboard(request, user_id):
    """Get company data for dashboard. Owner/admin only."""
    try:
        data = services.build_company_dashboard(request.user, user_id)
    except services.DashboardPermissionError as e:
        return Response({'error': str(e)}, status=status.HTTP_403_FORBIDDEN)
    except services.CompanyNotFoundError as e:
        return Response({'error': str(e)}, status=status.HTTP_404_NOT_FOUND)
    return Response(data)
