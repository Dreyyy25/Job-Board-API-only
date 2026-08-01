import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.jobs.models import JobPost


class AIUsageLog(models.Model):
    """One row per LLM call (chat, later, writes one row per turn).

    The project's Gemini bill, queryable per feature and per user.
    """

    class Feature(models.TextChoices):
        JOB_POST_WRITER = 'job_post_writer', 'Job post writer'
        RESUME_IMPORT = 'resume_import', 'Resume import'
        SCREENING = 'screening', 'Screening'
        CHAT = 'chat', 'Chat'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    feature = models.CharField(max_length=32, choices=Feature.choices)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
        related_name='ai_usage_logs',
    )
    model = models.CharField(max_length=100)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.feature} {self.model} in={self.input_tokens} out={self.output_tokens}"

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['feature', '-created_at'], name='aiusage_feature_created_idx'),
        ]


class ScreeningReport(models.Model):
    """One cached screening run for one job post.

    Append-only history: reads take the newest row. `report` holds
    {'candidates': [...], 'truncated': bool, 'excluded_count': int};
    `applicant_count` is how many applicants were actually screened,
    which is <= the number who applied when the cap truncates.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job_post = models.ForeignKey(
        JobPost, on_delete=models.CASCADE, related_name='screening_reports')
    report = models.JSONField(default=dict)
    applicant_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"screening {self.job_post_id} n={self.applicant_count}"

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['job_post', '-created_at'],
                         name='screening_job_created_idx'),
        ]
