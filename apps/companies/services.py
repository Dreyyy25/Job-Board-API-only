"""Service layer for the companies app."""

from .models import Company, CompanyImages


class CompanyNotFoundError(Exception):
    """Raised when the company doesn't exist."""


class DashboardPermissionError(Exception):
    """Raised when the requester isn't allowed to view the dashboard."""


def build_company_dashboard(requester, user_id):
    """Return a dashboard dict for the company owned by user_id.

    Access rules:
    - Admins can access any dashboard.
    - The owner can access their own.
    """
    is_owner = str(requester.id) == str(user_id)
    is_admin = requester.is_staff or requester.is_superuser
    if not (is_owner or is_admin):
        raise DashboardPermissionError('You do not have permission to access this dashboard')

    try:
        company = Company.objects.with_related().get(user_account_id=user_id)
    except Company.DoesNotExist:
        raise CompanyNotFoundError('Company not found')

    from .serializers import CompanyImagesSerializer, CompanySerializer

    images = CompanyImages.objects.filter(company=company).select_related('company')

    return {
        'company': CompanySerializer(company).data,
        'images': CompanyImagesSerializer(images, many=True).data,
    }
