import uuid
from django.db import models
from django.utils import timezone

# Create your models here.
class UserAccount(models.Model):
    USER_TYPE_CHOICES = [
        ('job_seeker', 'Job Seeker'),
        ('company', 'Company')
    ]
    
    SEX_CHOICES = [('M', 'Male'), ('F', 'Female'), ('Other', 'Other')]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_type = models.CharField(max_length=100, choices=USER_TYPE_CHOICES, null=False, blank=False)
    email = models.EmailField(max_length=100, unique=True, null=False, blank=False)
    password = models.CharField(max_length=255, null=False, blank=False)
    date_of_birth = models.DateField(null=True, blank=True)
    contact_number = models.CharField(max_length=20, blank=True)
    sex = models.CharField(max_length=10, choices=SEX_CHOICES, blank=True)
    user_image_url = models.URLField(max_length=500, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return self.email

    def is_authenticated(self):
        return True
    
    def is_anonymous(self):
        return False
    
    def is_active(self):
        return True
    
    def get_username(self):
        return self.email