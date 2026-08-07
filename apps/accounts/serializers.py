from rest_framework import serializers
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from .models import UserAccount


class UserAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserAccount
        fields = [
            'id',
            'email',
            'password',
            'user_type',
            'date_of_birth',
            'contact_number',
            'sex',
            'user_image_url',
            'is_active',
            'last_login',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'is_active', 'last_login', 'created_at', 'updated_at']
        extra_kwargs = {'password': {'write_only': True, 'required': False}}

    def validate_user_type(self, value):
        if value not in ['job_seeker', 'company']:
            raise serializers.ValidationError("Invalid user type. Must be 'job_seeker' or 'company'")
        if self.instance and self.instance.user_type != value:
            raise serializers.ValidationError("user_type cannot be changed")
        return value

    def validate_email(self, value):
        """Validate email field"""
        if not value or value.strip() == '':
            raise serializers.ValidationError("Email is required")

        # Check if email already exists (for updates)
        if self.instance:
            if UserAccount.objects.exclude(id=self.instance.id).filter(email=value).exists():
                raise serializers.ValidationError("This email is already registered")
        else:
            if UserAccount.objects.filter(email=value).exists():
                raise serializers.ValidationError("This email is already registered")

        return value.lower().strip()

    def validate_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as e:
            raise serializers.ValidationError(list(e.messages))
        return value

    def validate(self, attrs):
        if self.instance is not None and 'password' in self.initial_data:
            raise serializers.ValidationError({'password': ['Use /accounts/change-password/ to change your password.']})
        return attrs

    def create(self, validated_data):
        """Create user with hashed password"""
        validated_data['password'] = make_password(validated_data['password'])
        return super().create(validated_data)

    def update(self, instance, validated_data):
        """password is create-only — validate() rejects it before this
        point, so no update ever carries a 'password' key here."""
        return super().update(instance, validated_data)


class RegisterSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserAccount
        fields = [
            'email',
            'password',
            'user_type',
            'date_of_birth',
            'contact_number',
            'sex',
            'user_image_url',
        ]
        extra_kwargs = {
            'password': {'write_only': True},
            'user_type': {'required': True},
        }

    def validate_user_type(self, value):
        if value not in ['job_seeker', 'company']:
            raise serializers.ValidationError("Invalid user type. Must be 'job_seeker' or 'company'")
        return value

    def validate_email(self, value):
        if UserAccount.objects.filter(email=value).exists():
            raise serializers.ValidationError("This email is already registered")
        return value.lower().strip()

    def validate_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as e:
            raise serializers.ValidationError(list(e.messages))
        return value

    def create(self, validated_data):
        validated_data['password'] = make_password(validated_data['password'])
        return super().create(validated_data)
