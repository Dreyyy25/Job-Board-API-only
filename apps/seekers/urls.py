from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'profiles', views.SeekerProfileViewSet)
router.register(r'education', views.EducationDataViewSet)
router.register(r'experience', views.ExperienceDataViewSet)
router.register(r'skills', views.SkillSetViewSet)
router.register(r'seeker-skills', views.SeekerSkillSetViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('dashboard/<uuid:user_id>/', views.seeker_dashboard, name='seeker-dashboard'),
]