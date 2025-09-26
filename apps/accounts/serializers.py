from rest_framework import serializers
from .models import UserAccount

class UserAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserAccount
        fields = '__all__'
        extra_kwargs = {
            'password': {'write_only': True}
        }
    
    def validate_user_type(self, value):
        """Validate user_type field"""
        if value not in ['job_seeker', 'company']:
            raise serializers.ValidationError("Invalid user type. Must be 'job_seeker' or 'company'")
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