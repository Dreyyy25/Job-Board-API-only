from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework import exceptions

from .models import UserAccount


class CustomJWTAuthentication(JWTAuthentication):
    """JWT Authentication that uses UserAccount model instead of Django's User model"""

    def get_user(self, validated_token):
        """
        Attempts to find and return a UserAccount using the given validated token.
        """
        try:
            user_id = validated_token.get('user_id')
        except KeyError:
            raise exceptions.AuthenticationFailed('Token contained no recognizable user identification')

        try:
            # Use UserAccount instead of User model
            user = UserAccount.objects.get(id=user_id)
        except UserAccount.DoesNotExist:
            raise exceptions.AuthenticationFailed('User not found')

        if not user.is_active:
            raise exceptions.AuthenticationFailed('User is inactive')

        return user
