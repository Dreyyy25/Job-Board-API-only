from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'business-streams', views.BusinessStreamViewSet)
router.register(r'companies', views.CompanyViewSet)
router.register(r'company-images', views.CompanyImagesViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('dashboard/<uuid:user_id>/', views.company_dashboard, name='company-dashboard'),
]