from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import (
    extend_schema,
    inline_serializer,
)
from rest_framework import serializers as drf_serializers
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.filters import SearchFilter
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from apps.accounts.authentication import CustomJWTAuthentication
from jobApp.throttling import BurstRateThrottle
from . import services
from .filters import PublicCompanyFilter
from .models import BusinessStream, Company, CompanyImages
from .serializers import (
    BusinessStreamSerializer,
    CompanySerializer,
    CompanyImagesSerializer,
    PublicCompanyDetailSerializer,
    PublicCompanyListSerializer,
)
from .permissions import IsAdminOrReadOnly, IsCompanyOwnerOrAdmin, IsCompanyOwnerForImages


class _CompanyDashboardStatsSerializer(drf_serializers.Serializer):
    active_posts = drf_serializers.IntegerField()
    total_applications = drf_serializers.IntegerField()
    new_this_week = drf_serializers.IntegerField()


_CompanyDashboardSerializer = inline_serializer(
    name='CompanyDashboard',
    fields={
        'company': CompanySerializer(),
        'images': CompanyImagesSerializer(many=True),
        'stats': _CompanyDashboardStatsSerializer(),
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
        if user.is_authenticated and user.user_type == 'company':
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
        if user.is_authenticated and user.user_type == 'company':
            return qs.for_company_user(user)
        return qs.for_active_companies()


class PublicCompanyViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Public company directory -- read-only, anonymous-friendly.

    Deliberately a separate route from `profile/` (CompanyViewSet): that
    viewset's `get_queryset` narrows a logged-in company user to *their own*
    row, which is the right behavior for account management but would break
    a public companies page for a logged-in company user. This route always
    lists/retrieves active companies for everyone, logged in or not.
    """

    queryset = Company.objects.all()
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [AllowAny]
    # Layered: anon ceiling + per-user daily + per-user burst -- setting
    # this attribute REPLACES DRF's defaults, so all three must be listed
    # to keep the 60/min burst throttle backstopping anonymous browse here.
    throttle_classes = [AnonRateThrottle, UserRateThrottle, BurstRateThrottle]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_class = PublicCompanyFilter
    search_fields = ['company_name', 'profile_description']

    def get_queryset(self):
        """`.order_by(...)` is explicit here because `with_open_roles_count()`'s
        `Count(...)` annotation forces a GROUP BY, which makes Django drop the
        model's default `Meta.ordering` (`queryset.ordered` becomes False) --
        without this, pagination is nondeterministic across pages/requests.
        """
        return Company.objects.active().with_related().with_open_roles_count().order_by('company_name', 'id')

    def get_serializer_class(self):
        """Retrieve adds `images`; list stays without it."""
        if self.action == 'retrieve':
            return PublicCompanyDetailSerializer
        return PublicCompanyListSerializer


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
