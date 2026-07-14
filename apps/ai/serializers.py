from rest_framework import serializers

from apps.jobs.models import JobType


class JobPostAssistRequestSerializer(serializers.Serializer):
    notes = serializers.CharField(max_length=4000)
    job_type_id = serializers.PrimaryKeyRelatedField(
        queryset=JobType.objects.all(), required=False, allow_null=True)
    location_hint = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default='')


class ResumeImportRequestSerializer(serializers.Serializer):
    """Exactly-one-of validation lives in the service (InvalidResumeFileError)."""
    text = serializers.CharField(
        max_length=20000, required=False, allow_blank=True, default='')
    file = serializers.FileField(required=False, allow_null=True)
