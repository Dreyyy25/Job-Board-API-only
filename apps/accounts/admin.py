from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.contrib.admin.sites import NotRegistered
from .models import UserAccount

# Admin for your API users (UserAccount model)
@admin.register(UserAccount)
class UserAccountAdmin(admin.ModelAdmin):
    list_display = ['email', 'user_type', 'created_at', 'is_active_status']
    search_fields = ['email']
    list_filter = ['user_type', 'created_at']
    readonly_fields = ['id', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Account Information', {
            'fields': ('id', 'email', 'user_type')
        }),
        ('Personal Information', {
            'fields': ('date_of_birth', 'contact_number', 'sex', 'user_image_url')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def is_active_status(self, obj):
        """Show if user account is active"""
        return getattr(obj, 'is_active', True)
    is_active_status.boolean = True
    is_active_status.short_description = 'Active'
    
    def has_add_permission(self, request):
        """Only allow superusers to create API user accounts through admin"""
        return request.user.is_superuser
    
    def has_change_permission(self, request, obj=None):
        """Allow staff to view, superusers to edit"""
        return request.user.is_staff
    
    def has_delete_permission(self, request, obj=None):
        """Only superusers can delete"""
        return request.user.is_superuser
    
    def get_queryset(self, request):
        """Filter data based on user permissions"""
        qs = super().get_queryset(request)
        
        if request.user.is_superuser:
            return qs  # Superusers see everything
        elif request.user.is_staff:
            return qs  # Staff can see all but with limited permissions
        else:
            return qs.none()  # No access for regular users

# Customize the built-in User admin for admin users
class AdminUserAdmin(BaseUserAdmin):
    list_display = ['username', 'email', 'is_staff', 'is_superuser', 'date_joined']
    list_filter = ['is_staff', 'is_superuser', 'date_joined']
    
    def get_queryset(self, request):
        """Only superusers can manage admin users"""
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.none()

# Re-register the User model with custom admin
try:
    admin.site.unregister(User)
except NotRegistered:
    pass  # User model was not registered, so we can't unregister it

admin.site.register(User, AdminUserAdmin)

# Customize admin site appearance
admin.site.site_header = "Job Board Administration"
admin.site.site_title = "Job Board Admin"
admin.site.index_title = "Welcome to Job Board Administration"

# Admin functions for permissions (you had these)
def superuser_required(user):
    return user.is_superuser

def staff_required(user):
    return user.is_staff