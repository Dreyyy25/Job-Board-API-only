import uuid
from django.db import models
from django.utils import timezone
from apps.accounts.models import UserAccount

# Create your models here.
class BusinessStream(models.Model):
    """Business categories/industries for companies"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business_stream_name = models.CharField(max_length=100, unique=True)
    
    def __str__(self):
        return self.business_stream_name
    
    class Meta:
        ordering = ['business_stream_name']

class Company(models.Model):
    """Company profiles for business users"""
    
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('suspended', 'Suspended'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_account = models.OneToOneField(UserAccount, on_delete=models.CASCADE, related_name='company_profile')
    
    company_name = models.CharField(max_length=200)
    business_stream = models.ForeignKey(BusinessStream, on_delete=models.CASCADE)
    profile_description = models.TextField(blank=True)
    company_website_url = models.URLField(max_length=500, blank=True)
    contact_email = models.EmailField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return self.company_name
    
    class Meta:
        ordering = ['company_name']
        verbose_name_plural = "Companies"

class CompanyImages(models.Model):
    """Images for company profiles"""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='images')
    image_url = models.URLField(max_length=500)
    created_at = models.DateTimeField(default=timezone.now)
    
    def __str__(self):
        return f"{self.company.company_name} - Image"
    
    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = "Company Images"