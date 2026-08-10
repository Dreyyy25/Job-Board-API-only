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
            'id',
            'user_account',
            'company_name',
            'business_stream',
            'profile_description',
            'company_website_url',
            'contact_email',
            'status',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'user_account', 'created_at', 'updated_at']

    def validate_status(self, value):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if user is None or user.is_staff or user.is_superuser:
            return value
        current = self.instance.status if self.instance else None
        if value == current:
            return value  # no-op writes always pass (mirrors the application-status rule)
        if current == 'suspended':
            raise serializers.ValidationError('Your account is suspended. Contact support to restore it.')
        if value not in ('active', 'inactive'):
            raise serializers.ValidationError('Status may only be set to active or inactive.')
        return value


class CompanyImagesSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanyImages
        fields = ['id', 'company', 'image_url', 'created_at']
        read_only_fields = ['id', 'company', 'created_at']


class CompanyImagesRefSerializer(serializers.ModelSerializer):
    """Minimal image shape nested inside a public company retrieve response."""

    class Meta:
        model = CompanyImages
        fields = ['id', 'image_url', 'created_at']
        read_only_fields = fields


class PublicCompanyListSerializer(serializers.ModelSerializer):
    """Public read shape for the company directory (list + retrieve base).

    Deliberately excludes `contact_email` and `user_account` by not listing
    them -- neither belongs in an anonymous payload.
    """

    business_stream = BusinessStreamSerializer(read_only=True)
    open_roles_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Company
        fields = [
            'id',
            'company_name',
            'business_stream',
            'profile_description',
            'company_website_url',
            'status',
            'open_roles_count',
        ]
        read_only_fields = fields


class PublicCompanyDetailSerializer(PublicCompanyListSerializer):
    """Public read shape for a single company; adds `images`."""

    images = CompanyImagesRefSerializer(many=True, read_only=True)

    class Meta(PublicCompanyListSerializer.Meta):
        fields = PublicCompanyListSerializer.Meta.fields + ['images']
        read_only_fields = fields
