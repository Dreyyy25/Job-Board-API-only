import uuid
from django.db import models
from django.utils import timezone
from apps.accounts.models import UserAccount

# Create your models here.
class SeekerProfile(models.Model):
    """Profile for job seekers with personal and academic details"""
    
    user_account = models.OneToOneField(UserAccount, on_delete=models.CASCADE, primary_key=True, related_name='seeker_profile')
    
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    contact_details = models.TextField(blank=True)
    goals = models.TextField(blank=True)
    resume_url = models.URLField(max_length=500, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.first_name} {self.last_name}"
    
class EducationData(models.Model):
    """Education records for job seekers"""
    
    DEGREE_TYPE_CHOICES = [
        ('High School', 'High School'),
        ('Associate', 'Associate Degree'),
        ('Bachelor', 'Bachelor Degree'),
        ('Master', 'Master Degree'),
        ('PhD', 'PhD'),
        ('Certificate', 'Certificate'),
        ('Diploma', 'Diploma'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_account = models.ForeignKey(UserAccount, on_delete=models.CASCADE, related_name='education')
    
    institute_university_name = models.CharField(max_length=200, blank=True)
    degree_type = models.CharField(max_length=50, choices=DEGREE_TYPE_CHOICES, blank=True)
    field_of_study = models.CharField(max_length=200, blank=True)
    academic_details = models.TextField(blank=True)
    percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.degree_type} at {self.institute_university_name}"
    
    class Meta:
        ordering = ['-end_date', '-start_date']

class ExperienceData(models.Model):
    """Work experience records for job seekers"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_account = models.ForeignKey(UserAccount, on_delete=models.CASCADE,related_name='experiences')
    
    company_name = models.CharField(max_length=200)
    position = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    job_location_city = models.CharField(max_length=100, blank=True)
    job_location_country = models.CharField(max_length=100, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.position} at {self.company_name}"
    
    class Meta:
        ordering = ['-created_at']

class SkillSet(models.Model):
    """Master list of skills"""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    skill_name = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(default=timezone.now)
    
    def __str__(self):
        return self.skill_name

class SeekerSkillSet(models.Model):
    """Junction table linking seekers to their skills with proficiency levels"""
    
    SKILL_LEVEL_CHOICES = [
        ('Beginner', 'Beginner'),
        ('Intermediate', 'Intermediate'), 
        ('Advanced', 'Advanced'),
        ('Expert', 'Expert')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user_account = models.ForeignKey(UserAccount, on_delete=models.CASCADE, related_name='skills')
    skill_set = models.ForeignKey(SkillSet, on_delete=models.CASCADE)
    skill_level = models.CharField(max_length=20, choices=SKILL_LEVEL_CHOICES)
    
    def __str__(self):
        return f"{self.user_account.email} - {self.skill_set.skill_name} ({self.skill_level})"
    
    class Meta:
        unique_together = ['user_account', 'skill_set']