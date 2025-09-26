from rest_framework.authentication import BasicAuthentication
from rest_framework import exceptions
from django.utils.translation import gettext_lazy as _
import base64
import binascii
from .models import UserAccount

class EmailBasicAuthentication(BasicAuthentication):
    """
    HTTP Basic authentication using email instead of username.
    """
    
    def authenticate_credentials(self, userid, password, request=None):
        """
        Authenticate the userid and password against email and password.
        """
        try:
            user = UserAccount.objects.get(email=userid)
        except UserAccount.DoesNotExist:
            raise exceptions.AuthenticationFailed(_('Invalid email/password.'))
        
        # Simple password check (in production, use proper hashing)
        if user.password != password:
            raise exceptions.AuthenticationFailed(_('Invalid email/password.'))
        
        return (user, None)
    
    def authenticate_header(self, request):
        """
        Return a string to be used as the value of the `WWW-Authenticate`
        header in a `401 Unauthenticated` response, or `None` if the
        authentication scheme should return `403 Permission Denied` responses.
        """
        return 'Basic realm="%s"' % self.www_authenticate_realm