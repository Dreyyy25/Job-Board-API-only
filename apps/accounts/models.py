import uuid
from django.db import models, transaction
from django.utils import timezone
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin

# Custom manager for UserAccount
class UserAccountManager(BaseUserManager):
    """Custom manager for UserAccount model"""

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
        """Create and return a superuser"""
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('user_type', 'company')
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True')
        
        return self.create_user(email, password, **extra_fields)
    
class UserAccount(AbstractBaseUser, PermissionsMixin):
    USER_TYPE_CHOICES = [
        ('job_seeker', 'Job Seeker'),
        ('company', 'Company')
    ]
    
    SEX_CHOICES = [('M', 'Male'), ('F', 'Female'), ('Other', 'Other')]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_type = models.CharField(max_length=100, choices=USER_TYPE_CHOICES, null=False, blank=False)
    email = models.EmailField(max_length=100, unique=True, null=False, blank=False)
    date_of_birth = models.DateField(null=True, blank=True)
    contact_number = models.CharField(max_length=20, blank=True)
    sex = models.CharField(max_length=10, choices=SEX_CHOICES, blank=True)
    user_image_url = models.URLField(max_length=500, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = UserAccountManager()
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['user_type']
    
    class Meta:
        db_table = 'accounts_useraccount'
        verbose_name = 'User Account'
        verbose_name_plural = 'User Accounts'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user_type'], name='useracct_user_type_idx'),
        ]
    
    def __str__(self):
        return self.email
    
    def get_full_name(self):
        """Return the email as full name"""
        return self.email
    
    def get_short_name(self):
        """Return the email as short name"""
        return self.email