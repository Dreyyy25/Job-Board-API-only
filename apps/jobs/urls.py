from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'job-types', views.JobTypeViewSet)
router.register(r'job-locations', views.JobLocationViewSet)
router.register(r'job-posts', views.JobPostViewSet)
router.register(r'job-applications', views.JobPostActivityViewSet)
router.register(r'job-skills', views.JobPostSkillSetViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('apply/', views.apply_for_job, name='apply-for-job'),
    path('applications/job/<uuid:job_id>/', views.job_applications, name='job-applications'),
    path('applications/user/<uuid:user_id>/', views.user_applications, name='user-applications'),
]