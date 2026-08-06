from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'business-streams', views.BusinessStreamViewSet)
router.register(r'profile', views.CompanyViewSet)
router.register(r'company-images', views.CompanyImagesViewSet)
router.register(r'public', views.PublicCompanyViewSet, basename='public-company')

urlpatterns = [
    path('', include(router.urls)),
    path('dashboard/<uuid:user_id>/', views.company_dashboard, name='company-dashboard'),
]
