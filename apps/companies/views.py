from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import BusinessStream, Company, CompanyImages
from .serializers import BusinessStreamSerializer, CompanySerializer, CompanyImagesSerializer

# Create your views here.
class BusinessStreamViewSet(viewsets.ModelViewSet):
    """API for business categories"""
    queryset = BusinessStream.objects.all()
    serializer_class = BusinessStreamSerializer

class CompanyViewSet(viewsets.ModelViewSet):
    """API for company profiles"""
    queryset = Company.objects.all()
    serializer_class = CompanySerializer

class CompanyImagesViewSet(viewsets.ModelViewSet):
    """API for company images"""
    queryset = CompanyImages.objects.all()
    serializer_class = CompanyImagesSerializer

@api_view(['GET'])
def company_dashboard(request, user_id):
    """Get company data for dashboard"""
    try:
        company = Company.objects.get(user_account_id=user_id)
        images = CompanyImages.objects.filter(company=company)
        
        return Response({
            'company': CompanySerializer(company).data,
            'images': CompanyImagesSerializer(images, many=True).data,
        })
    except Company.DoesNotExist:
        return Response({'error': 'Company not found'}, status=404)