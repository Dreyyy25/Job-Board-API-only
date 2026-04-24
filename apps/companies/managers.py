from django.db import models


class CompanyQuerySet(models.QuerySet):
    def active(self):
        return self.filter(status='active')

    def for_user(self, user):
        return self.filter(user_account=user)

    def with_related(self):
        return self.select_related(
            'user_account', 'business_stream',
        ).prefetch_related('images')


class CompanyImagesQuerySet(models.QuerySet):
    def for_company_user(self, user):
        return self.filter(company__user_account=user)

    def for_active_companies(self):
        return self.filter(company__status='active')

    def with_related(self):
        return self.select_related('company', 'company__user_account')
