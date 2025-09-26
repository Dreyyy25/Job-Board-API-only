from rest_framework import serializers
from .models import JobType, JobLocation, JobPost, JobPostActivity, JobPostSkillSet

class JobTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobType
        fields = '__all__'

class JobLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobLocation
        fields = '__all__'

class JobPostSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobPost
        fields = '__all__'

class JobPostActivitySerializer(serializers.ModelSerializer):
    class Meta:
        model = JobPostActivity
        fields = '__all__'

class JobPostSkillSetSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobPostSkillSet
        fields = '__all__'