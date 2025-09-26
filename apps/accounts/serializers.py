from rest_framework import serializers
from .models import UserType, UserAccount

class UserTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserType
        fields = '__all__'

class UserAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserAccount
        fields = '__all__'
        extra_kwargs = {
            'password': {'write_only': True}
        }