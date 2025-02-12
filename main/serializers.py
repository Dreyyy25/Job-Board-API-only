from rest_framework import serializers
from .models import Job, JobApplication
from django.contrib.auth import get_user_model

class JobSerializer(serializers.ModelSerializer):
    employer = serializers.ReadOnlyField(source='employer.username')

    class Meta:
        model = Job
        fields = ['id', 'title', 'description', 'category', 'salary_range', 
                 'status', 'employer', 'created_at', 'updated_at']

class JobApplicationSerializer(serializers.ModelSerializer):
    freelancer = serializers.ReadOnlyField(source='freelancer.username')
    job = serializers.ReadOnlyField(source='job.id')

    class Meta:
        model = JobApplication
        fields = ['id', 'freelancer', 'job', 'cover_letter', 'status', 'applied_at']

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = get_user_model()
        fields = ['id', 'email', 'username', 'password', 'first_name', 
                 'last_name', 'user_type']
        extra_kwargs = {'password': {'write_only': True}}

    def create(self, validated_data):
        user = get_user_model().objects.create_user(
            email=validated_data['email'],
            username=validated_data['username'],
            password=validated_data['password'],
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
            user_type=validated_data['user_type']
        )
        return user