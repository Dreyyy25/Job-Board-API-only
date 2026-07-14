from django.urls import path

from . import views

urlpatterns = [
    path('job-post-assist/', views.job_post_assist, name='ai-job-post-assist'),
    path('resume-import/', views.resume_import, name='ai-resume-import'),
]
