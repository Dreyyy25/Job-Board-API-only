from rest_framework import serializers
from .models import SeekerProfile, EducationData, ExperienceData, SkillSet, SeekerSkillSet

class SeekerProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = SeekerProfile
        fields = '__all__'

class EducationDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = EducationData
        fields = '__all__'

class ExperienceDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExperienceData
        fields = '__all__'

class SkillSetSerializer(serializers.ModelSerializer):
    class Meta:
        model = SkillSet
        fields = '__all__'

class SeekerSkillSetSerializer(serializers.ModelSerializer):
    class Meta:
        model = SeekerSkillSet
        fields = '__all__'