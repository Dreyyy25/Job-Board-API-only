"""drf-spectacular extensions for project-specific classes.

Registered at import time when drf_spectacular initializes. Imported
from apps/accounts/apps.py via AccountsConfig.ready() to guarantee that
spectacular sees the registration before it starts walking views.
"""
from drf_spectacular.extensions import OpenApiAuthenticationExtension


class CustomJWTAuthenticationScheme(OpenApiAuthenticationExtension):
    """Tells drf-spectacular that CustomJWTAuthentication is JWT bearer auth.

    Without this, every view authenticated by CustomJWTAuthentication
    triggers a "could not resolve authenticator" warning at schema
    generation time.
    """
    target_class = 'apps.accounts.authentication.CustomJWTAuthentication'
    name = 'jwtAuth'

    def get_security_definition(self, auto_schema):
        return {
            'type': 'http',
            'scheme': 'bearer',
            'bearerFormat': 'JWT',
        }
