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


class ChatRequestSerializer(serializers.Serializer):
    # allow_blank defaults to False and trim_whitespace to True, so a
    # whitespace-only message is rejected — which is what the 400 tests expect.
    message = serializers.CharField(max_length=4000, trim_whitespace=True)
    # Ownership is enforced in the service, which 404s rather than 403s so a
    # stranger's conversation id is never confirmed to exist.
    conversation_id = serializers.UUIDField(required=False, allow_null=True)
