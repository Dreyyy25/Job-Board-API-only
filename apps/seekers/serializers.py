from rest_framework import serializers
from .models import (
    SeekerProfile,
    EducationData,
    ExperienceData,
    SkillSet,
    SeekerSkillSet,
)


class SeekerProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = SeekerProfile
        fields = [
            'user_account',
            'first_name',
            'last_name',
            'contact_details',
            'goals',
            'resume_url',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['user_account', 'created_at', 'updated_at']


def _validate_date_order(attrs, instance):
    start = attrs.get('start_date', getattr(instance, 'start_date', None))
    end = attrs.get('end_date', getattr(instance, 'end_date', None))
    if start is not None and end is not None and start > end:
        raise serializers.ValidationError({'start_date': 'start_date must be <= end_date.'})


class EducationDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = EducationData
        fields = [
            'id',
            'user_account',
            'institute_university_name',
            'degree_type',
            'field_of_study',
            'academic_details',
            'percentage',
            'start_date',
            'end_date',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'user_account', 'created_at', 'updated_at']

    def validate_percentage(self, value):
        if value is not None and (value < 0 or value > 100):
            raise serializers.ValidationError('Must be between 0 and 100.')
        return value

    def validate(self, attrs):
        _validate_date_order(attrs, self.instance)
        return attrs


class ExperienceDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExperienceData
        fields = [
            'id',
            'user_account',
            'company_name',
            'position',
            'description',
            'job_location_city',
            'job_location_country',
            'start_date',
            'end_date',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'user_account', 'created_at', 'updated_at']

    def validate(self, attrs):
        _validate_date_order(attrs, self.instance)
        return attrs


class SkillSetSerializer(serializers.ModelSerializer):
    class Meta:
        model = SkillSet
        fields = ['id', 'skill_name', 'created_at']
        read_only_fields = ['id', 'created_at']


class SeekerSkillSetSerializer(serializers.ModelSerializer):
    """Write serializer. Create accepts either an existing skill_set UUID or a
    free-text skill_name (get-or-create, case-insensitive — the master list
    grows organically). Updates may change skill_level only."""

    skill_name = serializers.CharField(write_only=True, required=False, max_length=100, allow_blank=False)

    class Meta:
        model = SeekerSkillSet
        fields = ['id', 'user_account', 'skill_set', 'skill_level', 'skill_name']
        read_only_fields = ['id', 'user_account']
        extra_kwargs = {'skill_set': {'required': False}}

    def validate(self, attrs):
        if self.instance is not None:  # update: level only
            if 'skill_set' in attrs or 'skill_name' in attrs:
                raise serializers.ValidationError(
                    {'skill_set': ['Cannot change the skill; delete and re-add instead.']}
                )
            return attrs

        name = (attrs.pop('skill_name', '') or '').strip()
        if not attrs.get('skill_set') and not name:
            raise serializers.ValidationError({'skill_set': ['Provide skill_set or skill_name.']})
        if name and not attrs.get('skill_set'):
            existing = SkillSet.objects.filter(skill_name__iexact=name).first()
            attrs['skill_set'] = existing or SkillSet.objects.create(skill_name=name)

        # user_account is read-only, which silently disables DRF's
        # UniqueTogetherValidator — enforce it here so a duplicate attach is a
        # clean 400 instead of a DB IntegrityError 500.
        user = self.context['request'].user
        if SeekerSkillSet.objects.filter(user_account=user, skill_set=attrs['skill_set']).exists():
            raise serializers.ValidationError({'skill_set': ['You already added this skill.']})
        return attrs


class SeekerSkillSetReadSerializer(serializers.ModelSerializer):
    skill_set = SkillSetSerializer(read_only=True)

    class Meta:
        model = SeekerSkillSet
        fields = ['id', 'user_account', 'skill_set', 'skill_level']
        read_only_fields = fields
