from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import (
    TokenRefreshView,
    # TokenBlacklistView,
    TokenVerifyView,
)
from . import views

router = DefaultRouter()
router.register(r'users', views.UserAccountViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('register/', views.register, name='register'),
    path('login/', views.login, name='login'),
    path('me/', views.me, name='current-user'),
    
    path('token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),
    path('token/verify/', TokenVerifyView.as_view(), name='token-verify'),
    # path('token/blacklist/', TokenBlacklistView.as_view(), name='token-blacklist'),
]