from django.db import models
from django.db.models import Count, Q


class CompanyQuerySet(models.QuerySet):
    def active(self):
        return self.filter(status='active')

    def for_user(self, user):
        return self.filter(user_account=user)

    def with_related(self):
        return self.select_related(
            'user_account',
            'business_stream',
        ).prefetch_related('images')

    def with_open_roles_count(self):
        """Annotate each company with its published+active job-post count.

        A filtered, distinct Count -- `distinct=True` keeps this correct
        even when composed with a join-based prefetch (e.g. `with_related()`'s
        `images`) that would otherwise multiply the joined rows behind the
        aggregate.
        """
        return self.annotate(
            open_roles_count=Count(
                'job_posts',
                filter=Q(job_posts__is_published=True, job_posts__is_active=True),
                distinct=True,
            )
        )


class CompanyImagesQuerySet(models.QuerySet):
    def for_company_user(self, user):
        return self.filter(company__user_account=user)

    def for_active_companies(self):
        return self.filter(company__status='active')

    def with_related(self):
        return self.select_related('company', 'company__user_account')
