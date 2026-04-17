from rest_framework import serializers
from .models import JobType, JobLocation, JobPost, JobPostActivity, JobPostSkillSet


class JobTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobType
        fields = ['id', 'job_type_name', 'description']
        read_only_fields = ['id']


class JobLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobLocation
        fields = ['id', 'street_address', 'city', 'country', 'zip', 'country_code']
        read_only_fields = ['id']


class JobPostSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobPost
        fields = [
            'id', 'company', 'job_type', 'job_location',
            'job_title', 'job_description', 'job_description_hidden',
            'salary_min', 'salary_max', 'salary_type', 'deadline_date',
            'is_published', 'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'company', 'created_at', 'updated_at']

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        is_owner = bool(
            user and user.is_authenticated and (
                user.is_staff or user.is_superuser
                or instance.company.user_account_id == user.id
            )
        )
        if not is_owner:
            data.pop('job_description_hidden', None)
        return data


class JobPostActivitySerializer(serializers.ModelSerializer):
    class Meta:
        model = JobPostActivity
        fields = [
            'id', 'user_account', 'job_post', 'application_date',
            'application_status', 'cover_letter', 'updated_at',
        ]
        read_only_fields = ['id', 'application_date', 'updated_at']


class JobPostSkillSetSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobPostSkillSet
        fields = ['id', 'job_post', 'skill_set', 'skill_level', 'is_required']
        read_only_fields = ['id']
