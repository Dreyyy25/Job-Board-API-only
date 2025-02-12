from django.urls import path
from . import views

urlpatterns = [
    # Register
    path('register/', views.UserCreateView.as_view()),
    
    # Get Users
    path('users/', views.UserViewSet.as_view({
        'get': 'list'
    })),
    path('users/<uuid:pk>/', views.UserViewSet.as_view({
        'get': 'retrieve'
    })),
    
    # Jobs
    path('jobs/', views.JobViewSet.as_view({
        'get': 'list',
        'post': 'create'
    })),
    path('jobs/<uuid:pk>/', views.JobViewSet.as_view({
        'get': 'retrieve',
        'put': 'update',
        'patch': 'partial_update',
        'delete': 'destroy'
    })),

    # Job Applications
    path('applications/', views.JobApplicationViewSet.as_view({
        'get': 'list',
        'post': 'create'
    })),
    path('applications/<uuid:pk>/', views.JobApplicationViewSet.as_view({
        'get': 'retrieve',
        # 'put': 'update',
        'patch': 'update_status',
        'delete': 'destroy'
    })),
]