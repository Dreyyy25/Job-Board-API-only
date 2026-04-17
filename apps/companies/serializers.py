from rest_framework import serializers
from .models import BusinessStream, Company, CompanyImages


class BusinessStreamSerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessStream
        fields = ['id', 'business_stream_name']
        read_only_fields = ['id']


class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = [
            'id', 'user_account', 'company_name', 'business_stream',
            'profile_description', 'company_website_url', 'contact_email',
            'status', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'user_account', 'created_at', 'updated_at']


class CompanyImagesSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanyImages
        fields = ['id', 'company', 'image_url', 'created_at']
        read_only_fields = ['id', 'created_at']
