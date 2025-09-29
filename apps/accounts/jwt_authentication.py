from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth.models import AnonymousUser
from .models import UserAccount

class CustomJWTAuthentication(JWTAuthentication):
    """
    Custom JWT authentication that works with UserAccount model
    """
    
    def get_user(self, validated_token):
        """
        Attempts to find and return a user using the given validated token.
        """
        try:
            user_id = validated_token['user_id']
        except KeyError:
            raise InvalidToken('Token contained no recognizable user identification')

        try:
            user = UserAccount.objects.get(id=user_id)
        except UserAccount.DoesNotExist:
            raise InvalidToken('User not found')

        return user

def get_tokens_for_user(user):
    """
    Generate JWT tokens for a user
    """
    refresh = RefreshToken()
    refresh['user_id'] = str(user.id)
    refresh['email'] = user.email
    refresh['user_type'] = user.user_type
    
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }