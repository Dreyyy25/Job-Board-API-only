from django.conf import settings
from django.urls import path, include
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView

from .cookies import set_refresh_cookie
from . import views


_RefreshResponseSerializer = inline_serializer(
    name='TokenRefreshResponse',
    fields={'access': drf_serializers.CharField()},
)

_RefreshErrorSerializer = inline_serializer(
    name='TokenRefreshError',
    fields={'detail': drf_serializers.CharField()},
)


class CookieTokenRefreshView(TokenRefreshView):
    """Reads the refresh token from the httpOnly cookie (never the body)
    and writes the rotated refresh token back to that same cookie.

    ROTATE_REFRESH_TOKENS / BLACKLIST_AFTER_ROTATION are enabled in
    SIMPLE_JWT, so TokenRefreshSerializer.validated_data comes back with
    both `access` and `refresh` — we move `refresh` into the cookie and
    keep only `access` in the response body.
    """
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'token_refresh'

    @extend_schema(
        request=None,
        responses={
            200: _RefreshResponseSerializer,
            401: _RefreshErrorSerializer,
            429: OpenApiResponse(description='Rate limited'),
        },
        tags=['accounts'],
    )
    def post(self, request, *args, **kwargs):
        cookie_name = settings.AUTH_REFRESH_COOKIE['NAME']
        refresh_token = request.COOKIES.get(cookie_name)
        if not refresh_token:
            return Response(
                {'detail': 'Refresh token cookie not found.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        serializer = self.get_serializer(data={'refresh': refresh_token})
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as e:
            raise InvalidToken(e.args[0]) from e

        data = dict(serializer.validated_data)
        rotated_refresh = data.pop('refresh', None)
        response = Response(data, status=status.HTTP_200_OK)
        if rotated_refresh:
            set_refresh_cookie(response, rotated_refresh)
        return response


router = DefaultRouter()
router.register(r'users', views.UserAccountViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('register/', views.register, name='register'),
    path('login/', views.login, name='login'),
    path('logout/', views.logout, name='logout'),
    path('me/', views.me, name='current-user'),

    path('token/refresh/', CookieTokenRefreshView.as_view(), name='token-refresh'),
    path('token/verify/', TokenVerifyView.as_view(), name='token-verify'),
    # path('token/blacklist/', TokenBlacklistView.as_view(), name='token-blacklist'),
]