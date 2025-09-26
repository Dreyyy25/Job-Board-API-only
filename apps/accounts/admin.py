from django.contrib import admin
from .models import UserAccount

@admin.register(UserAccount)
class UserAccountAdmin(admin.ModelAdmin):
    list_display = ['email', 'user_type', 'created_at']
    search_fields = ['email']
    list_filter = ['user_type']