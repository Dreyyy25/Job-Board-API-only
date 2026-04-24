from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import UserAccount


@receiver(post_save, sender=UserAccount)
def create_user_profile(sender, instance, created, **kwargs):
    if not created:
        return

    # Lazy imports — avoid cycles and apps-not-ready at import time.
    from apps.companies.models import BusinessStream, Company
    from apps.seekers.models import SeekerProfile

    if instance.user_type == 'job_seeker':
        SeekerProfile.objects.get_or_create(
            user_account=instance,
            defaults={'first_name': '', 'last_name': ''},
        )
    elif instance.user_type == 'company':
        stream, _ = BusinessStream.objects.get_or_create(
            business_stream_name='Uncategorized',
        )
        Company.objects.get_or_create(
            user_account=instance,
            defaults={'company_name': '', 'business_stream': stream},
        )
