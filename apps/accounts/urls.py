from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'user-types', views.UserTypeViewSet)
router.register(r'users', views.UserAccountViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('register/', views.register, name='register'),
    path('login/', views.login, name='login'),
]