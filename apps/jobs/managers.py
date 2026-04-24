from django.db import models


class JobPostQuerySet(models.QuerySet):
    def published(self):
        return self.filter(is_published=True, is_active=True)

    def for_company(self, user):
        return self.filter(company__user_account=user)

    def with_related(self):
        return self.select_related(
            'company', 'company__business_stream', 'job_type', 'job_location',
        ).prefetch_related('required_skills__skill_set')


class JobPostActivityQuerySet(models.QuerySet):
    def for_user(self, user):
        return self.filter(user_account=user)

    def for_company(self, user):
        return self.filter(job_post__company__user_account=user)

    def with_related(self):
        return self.select_related(
            'user_account', 'job_post', 'job_post__company',
        )


class JobPostSkillSetQuerySet(models.QuerySet):
    def for_company(self, user):
        return self.filter(job_post__company__user_account=user)

    def for_published_jobs(self):
        return self.filter(job_post__is_published=True)

    def with_related(self):
        return self.select_related('job_post', 'skill_set')
