from rest_framework import serializers
from apps.companies.models import Company
from apps.companies.serializers import BusinessStreamSerializer
from apps.seekers.models import SkillSet
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


class JobTypeRefSerializer(serializers.ModelSerializer):
    """Minimal job-type shape nested inside a job post read representation."""

    class Meta:
        model = JobType
        fields = ['id', 'job_type_name']
        read_only_fields = fields


class CompanyRefSerializer(serializers.ModelSerializer):
    """Minimal company shape nested inside a job post read representation.

    `id` is the Company id (not the owning user-account id) -- the frontend
    links a job post to `/companies/{id}` with it.
    """

    business_stream = BusinessStreamSerializer(read_only=True)

    class Meta:
        model = Company
        fields = ['id', 'company_name', 'business_stream']
        read_only_fields = fields


class SkillSetRefSerializer(serializers.ModelSerializer):
    """Minimal skill shape nested inside a job post's required_skills."""

    class Meta:
        model = SkillSet
        fields = ['id', 'skill_name']
        read_only_fields = fields


class JobPostSkillSetReadSerializer(serializers.ModelSerializer):
    """Read-only nested shape for one of a job post's required skills."""

    skill_set = SkillSetRefSerializer(read_only=True)

    class Meta:
        model = JobPostSkillSet
        fields = ['id', 'skill_set', 'skill_level', 'is_required']
        read_only_fields = fields


class JobLocationRefSerializer(serializers.ModelSerializer):
    """City/country only — the application screens need no more."""

    class Meta:
        model = JobLocation
        fields = ['city', 'country']
        read_only_fields = fields


class ApplicationCompanyRefSerializer(serializers.ModelSerializer):
    """Minimal company shape nested inside an application's job_post summary.

    Deliberately leaner than `CompanyRefSerializer` (no `business_stream`):
    the application list screens only need id/company_name, and dropping it
    avoids an extra select_related hop with no read consumer.
    """

    class Meta:
        model = Company
        fields = ['id', 'company_name']
        read_only_fields = fields


class ApplicationJobPostSerializer(serializers.ModelSerializer):
    """Lean job summary embedded in application reads. Embedding (rather than a
    client-side join) is what lets a seeker keep seeing details of a job that
    was unpublished after they applied."""

    company = ApplicationCompanyRefSerializer(read_only=True)
    job_type = JobTypeRefSerializer(read_only=True)
    job_location = JobLocationRefSerializer(read_only=True)

    class Meta:
        model = JobPost
        fields = [
            'id',
            'job_title',
            'company',
            'job_type',
            'job_location',
            'salary_min',
            'salary_max',
            'salary_type',
            'deadline_date',
            'is_published',
            'is_active',
        ]
        read_only_fields = fields


class JobPostActivityReadSerializer(serializers.ModelSerializer):
    job_post = ApplicationJobPostSerializer(read_only=True)

    class Meta:
        model = JobPostActivity
        fields = [
            'id',
            'user_account',
            'job_post',
            'application_date',
            'application_status',
            'cover_letter',
            'updated_at',
        ]
        read_only_fields = fields


def _job_post_is_owner(context, instance):
    request = context.get('request')
    user = getattr(request, 'user', None)
    return bool(
        user
        and user.is_authenticated
        and (user.is_staff or user.is_superuser or instance.company.user_account_id == user.id)
    )


class JobPostSerializer(serializers.ModelSerializer):
    """Write contract for job posts.

    `job_type`/`job_location` accept UUIDs on create/update; `company` is
    auto-assigned and read-only. Used for create/update/destroy actions --
    list/retrieve use `JobPostReadSerializer` for the nested read shape.
    """

    class Meta:
        model = JobPost
        fields = [
            'id',
            'company',
            'job_type',
            'job_location',
            'job_title',
            'job_description',
            'job_description_hidden',
            'salary_min',
            'salary_max',
            'salary_type',
            'deadline_date',
            'is_published',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'company', 'created_at', 'updated_at']

    def validate(self, attrs):
        salary_min = attrs.get('salary_min', getattr(self.instance, 'salary_min', None))
        salary_max = attrs.get('salary_max', getattr(self.instance, 'salary_max', None))
        if salary_min is not None and salary_min < 0:
            raise serializers.ValidationError({'salary_min': 'Must be non-negative.'})
        if salary_max is not None and salary_max < 0:
            raise serializers.ValidationError({'salary_max': 'Must be non-negative.'})
        if salary_min is not None and salary_max is not None and salary_min > salary_max:
            raise serializers.ValidationError({'salary_min': 'salary_min must be <= salary_max.'})
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not _job_post_is_owner(self.context, instance):
            data.pop('job_description_hidden', None)
        return data


class JobPostReadSerializer(serializers.ModelSerializer):
    """Nested read representation for job posts (list + retrieve).

    Replaces the bare FK UUIDs the write serializer accepts with nested
    objects and adds `required_skills`. Relies on `JobPostQuerySet.with_related()`
    (select_related company/business_stream/job_type/job_location,
    prefetch_related required_skills__skill_set) for a flat query count.
    """

    company = CompanyRefSerializer(read_only=True)
    job_type = JobTypeRefSerializer(read_only=True)
    job_location = JobLocationSerializer(read_only=True)
    required_skills = JobPostSkillSetReadSerializer(many=True, read_only=True)

    class Meta:
        model = JobPost
        fields = [
            'id',
            'company',
            'job_type',
            'job_location',
            'required_skills',
            'job_title',
            'job_description',
            'job_description_hidden',
            'salary_min',
            'salary_max',
            'salary_type',
            'deadline_date',
            'is_published',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not _job_post_is_owner(self.context, instance):
            data.pop('job_description_hidden', None)
        return data


class JobPostActivitySerializer(serializers.ModelSerializer):
    class Meta:
        model = JobPostActivity
        fields = [
            'id',
            'user_account',
            'job_post',
            'application_date',
            'application_status',
            'cover_letter',
            'updated_at',
        ]
        read_only_fields = ['id', 'application_date', 'updated_at']


_STATUS_TRANSITIONS = {
    # actor role -> {current status -> allowed next statuses}
    'seeker': {'pending': {'withdrawn'}, 'reviewed': {'withdrawn'}},
    'company': {'pending': {'reviewed', 'accepted', 'rejected'}, 'reviewed': {'accepted', 'rejected'}},
}


class JobPostActivityUpdateSerializer(serializers.ModelSerializer):
    """Only application_status is writable, and only along the allowed
    transitions for the caller's role. Everything else about an application
    is immutable after /jobs/apply/ creates it."""

    class Meta:
        model = JobPostActivity
        fields = [
            'id',
            'user_account',
            'job_post',
            'application_date',
            'application_status',
            'cover_letter',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'user_account',
            'job_post',
            'application_date',
            'cover_letter',
            'updated_at',
        ]

    def validate_application_status(self, value):
        user = self.context['request'].user
        current = self.instance.application_status
        if value == current or user.is_staff or user.is_superuser:
            return value
        if user.id == self.instance.user_account_id:
            allowed = _STATUS_TRANSITIONS['seeker'].get(current, set())
        elif self.instance.job_post.company.user_account_id == user.id:
            allowed = _STATUS_TRANSITIONS['company'].get(current, set())
        else:
            allowed = set()  # unreachable via queryset narrowing; defense in depth
        if value not in allowed:
            raise serializers.ValidationError(f"Cannot change status from '{current}' to '{value}'.")
        return value


class JobPostSkillSetSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobPostSkillSet
        fields = ['id', 'job_post', 'skill_set', 'skill_level', 'is_required']
        read_only_fields = ['id']
