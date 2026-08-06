from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html
from .models import UserAccount


@admin.register(UserAccount)
class UserAccountAdmin(BaseUserAdmin):
    """Admin interface for UserAccount (custom user model)"""

    # Display configuration with custom methods
    list_display = ['email', 'user_type_badge', 'is_active', 'is_staff', 'is_superuser', 'created_at']
    list_filter = ['user_type', 'is_active', 'is_staff', 'is_superuser', 'sex', 'created_at']
    search_fields = ['email', 'contact_number']
    ordering = ['-created_at']
    date_hierarchy = 'created_at'  # Add date navigation

    # Add colored badges for user types
    @admin.display(description='User Type')
    def user_type_badge(self, obj):
        colors = {
            'job_seeker': '#28a745',  # Green
            'company': '#007bff',  # Blue
        }
        color = colors.get(obj.user_type, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 3px;">{}</span>',
            color,
            obj.get_user_type_display(),
        )

    # Form configuration
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal Info', {'fields': ('user_type', 'date_of_birth', 'contact_number', 'sex', 'user_image_url')}),
        (
            'Permissions',
            {
                'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
            },
        ),
        (
            'Important Dates',
            {
                'fields': ('last_login', 'created_at', 'updated_at'),
            },
        ),
    )

    add_fieldsets = (
        (
            None,
            {
                'classes': ('wide',),
                'fields': ('email', 'password1', 'password2', 'user_type', 'is_active', 'is_staff', 'is_superuser'),
            },
        ),
    )

    readonly_fields = ['id', 'created_at', 'updated_at', 'last_login']
    filter_horizontal = (
        'groups',
        'user_permissions',
    )  # Better UX for permissions

    # Actions
    actions = ['activate_users', 'deactivate_users']

    @admin.action(description='Activate selected users')
    def activate_users(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} user(s) activated.')

    @admin.action(description='Deactivate selected users')
    def deactivate_users(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} user(s) deactivated.')

    # Security
    def get_form(self, request, obj=None, **kwargs):
        """Override to use custom form"""
        form = super().get_form(request, obj, **kwargs)
        is_superuser = request.user.is_superuser

        if not is_superuser:
            # Non-superusers can't change these fields
            if 'is_superuser' in form.base_fields:
                form.base_fields['is_superuser'].disabled = True
            if 'is_staff' in form.base_fields:
                form.base_fields['is_staff'].disabled = True
            if 'user_permissions' in form.base_fields:
                form.base_fields['user_permissions'].disabled = True

        return form


# Customize admin site appearance
admin.site.site_header = "Job Board Administration"
admin.site.site_title = "Job Board Admin"
admin.site.index_title = "Welcome to Job Board Administration"
