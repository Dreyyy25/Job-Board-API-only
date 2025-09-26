from rest_framework import serializers
from .models import BusinessStream, Company, CompanyImages

class BusinessStreamSerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessStream
        fields = '__all__'

class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = '__all__'

class CompanyImagesSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanyImages
        fields = '__all__'