from django.contrib.auth.models import BaseUserManager
from django.db import models, transaction


class UserAccountQuerySet(models.QuerySet):
    def seekers(self):
        return self.filter(user_type='job_seeker')

    def companies(self):
        return self.filter(user_type='company')

    def with_profile(self):
        return self.select_related('seeker_profile', 'company_profile')


class UserAccountManager(BaseUserManager.from_queryset(UserAccountQuerySet)):
    """Manager composing BaseUserManager with the UserAccount queryset methods.

    Uses the single-base ``BaseUserManager.from_queryset(...)`` pattern
    rather than multiple inheritance — avoids the Manager-diamond MRO
    ambiguity that arises with ``(BaseUserManager, Manager.from_queryset(X))``.
    """

    def create_user(self, email, password=None, **extra_fields):
        """Create and return a regular user.

        Wrapped in transaction.atomic() so the post_save signal that
        auto-creates the user's profile either succeeds with the user row
        or rolls back both together. Matters most for shell-invoked paths
        (`manage.py createsuperuser`, direct `create_user` in scripts)
        that run in autocommit mode.
        """
        if not email:
            raise ValueError('Email is required')

        email = self.normalize_email(email)
        with transaction.atomic():
            user = self.model(email=email, **extra_fields)
            user.set_password(password)
            user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        """Create and return a superuser."""
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('user_type', 'company')

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True')

        return self.create_user(email, password, **extra_fields)
