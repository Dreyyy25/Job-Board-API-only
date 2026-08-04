import uuid
from django.db import models
from django.utils import timezone
from apps.accounts.models import UserAccount
from apps.companies.models import Company
from apps.seekers.models import SkillSet

from .managers import (
    JobPostActivityQuerySet,
    JobPostQuerySet,
    JobPostSkillSetQuerySet,
)


# Create your models here.
class JobType(models.Model):
    """Job types like Full-time, Part-time, Contract, etc."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job_type_name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.job_type_name

    class Meta:
        ordering = ['job_type_name']


class JobLocation(models.Model):
    """Location details for job posts"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    street_address = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=100)
    country = models.CharField(max_length=100)
    zip = models.CharField(max_length=20, blank=True)
    country_code = models.CharField(max_length=5, blank=True)

    def __str__(self):
        return f"{self.city}, {self.country}"

    class Meta:
        ordering = ['country', 'city']
        indexes = [
            models.Index(fields=['country', 'city'], name='joblocation_country_city_idx'),
        ]


class JobPost(models.Model):
    """Main job posting model"""

    SALARY_TYPE_CHOICES = [('hourly', 'Hourly'), ('monthly', 'Monthly'), ('yearly', 'Yearly')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='job_posts')
    job_type = models.ForeignKey(JobType, on_delete=models.CASCADE)
    job_location = models.ForeignKey(JobLocation, on_delete=models.CASCADE)

    job_title = models.CharField(max_length=200)
    job_description = models.TextField()

    job_description_hidden = models.TextField(blank=True)
    salary_min = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    salary_max = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    salary_type = models.CharField(max_length=20, choices=SALARY_TYPE_CHOICES, blank=True)
    deadline_date = models.DateField(null=True, blank=True)

    is_published = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    objects = JobPostQuerySet.as_manager()

    def __str__(self):
        return f"{self.job_title} at {self.company.company_name}"

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['is_published', 'is_active', '-created_at'],
                name='jobpost_pub_active_created_idx',
            ),
            models.Index(
                fields=['company', '-created_at'],
                name='jobpost_company_created_idx',
            ),
            models.Index(fields=['deadline_date'], name='jobpost_deadline_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(salary_min__isnull=True)
                | models.Q(salary_max__isnull=True)
                | models.Q(salary_min__lte=models.F('salary_max')),
                name='jobpost_salary_min_le_max',
            ),
            models.CheckConstraint(
                check=(models.Q(salary_min__isnull=True) | models.Q(salary_min__gte=0))
                & (models.Q(salary_max__isnull=True) | models.Q(salary_max__gte=0)),
                name='jobpost_salary_non_negative',
            ),
        ]


class JobPostActivity(models.Model):
    """Job applications from seekers"""

    APPLICATION_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('reviewed', 'Reviewed'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
        ('withdrawn', 'Withdrawn'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_account = models.ForeignKey(UserAccount, on_delete=models.CASCADE, related_name='job_applications')
    job_post = models.ForeignKey(JobPost, on_delete=models.CASCADE, related_name='applications')

    application_date = models.DateTimeField(default=timezone.now)
    application_status = models.CharField(max_length=20, choices=APPLICATION_STATUS_CHOICES, default='pending')
    cover_letter = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = JobPostActivityQuerySet.as_manager()

    def __str__(self):
        return f"{self.user_account.email} applied for {self.job_post.job_title}"

    class Meta:
        ordering = ['-application_date']
        unique_together = ['user_account', 'job_post']
        indexes = [
            models.Index(
                fields=['job_post', 'application_status'],
                name='jpactivity_job_status_idx',
            ),
            models.Index(
                fields=['user_account', '-application_date'],
                name='jpactivity_user_date_idx',
            ),
        ]


class JobPostSkillSet(models.Model):
    """Skills required for specific job posts"""

    SKILL_LEVEL_CHOICES = [
        ('Beginner', 'Beginner'),
        ('Intermediate', 'Intermediate'),
        ('Advanced', 'Advanced'),
        ('Expert', 'Expert'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job_post = models.ForeignKey(JobPost, on_delete=models.CASCADE, related_name='required_skills')
    skill_set = models.ForeignKey(SkillSet, on_delete=models.CASCADE)
    skill_level = models.CharField(max_length=20, choices=SKILL_LEVEL_CHOICES)
    is_required = models.BooleanField(default=True)

    objects = JobPostSkillSetQuerySet.as_manager()

    def __str__(self):
        required = "Required" if self.is_required else "Optional"
        return f"{self.job_post.job_title} - {self.skill_set.skill_name} ({self.skill_level}) - {required}"

    class Meta:
        unique_together = ['job_post', 'skill_set']
