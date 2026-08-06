from django.db import models
from django.db.models.functions import Coalesce


class JobPostQuerySet(models.QuerySet):
    def published(self):
        return self.filter(is_published=True, is_active=True)

    def for_company(self, user):
        return self.filter(company__user_account=user)

    def with_related(self):
        return self.select_related(
            'company',
            'company__business_stream',
            'job_type',
            'job_location',
        ).prefetch_related('required_skills__skill_set')

    def with_salary_rank(self):
        """Annotate salary_rank = COALESCE(salary_max, salary_min, 0).

        Backs `ordering=-salary_rank` (highest-paying first). Plain
        `-salary_max` puts NULLs first on Postgres; the 0 fallback instead
        pushes salary-less jobs to the end of a descending sort.
        """
        return self.annotate(
            salary_rank=Coalesce(
                'salary_max',
                'salary_min',
                models.Value(0),
                output_field=models.DecimalField(max_digits=10, decimal_places=2),
            )
        )

    def with_salary_floor(self, value):
        """Filter to jobs where COALESCE(salary_max, salary_min) >= value.

        No 0 fallback (unlike `with_salary_rank`): a job with both
        salary_max and salary_min null coalesces to NULL, and `NULL >= value`
        is never true, so such jobs never match a salary floor.
        """
        return self.annotate(
            _salary_floor=Coalesce(
                'salary_max',
                'salary_min',
                output_field=models.DecimalField(max_digits=10, decimal_places=2),
            )
        ).filter(_salary_floor__gte=value)


class JobPostActivityQuerySet(models.QuerySet):
    def for_user(self, user):
        return self.filter(user_account=user)

    def for_company(self, user):
        return self.filter(job_post__company__user_account=user)

    def with_related(self):
        return self.select_related(
            'user_account',
            'job_post',
            'job_post__company',
        )


class JobPostSkillSetQuerySet(models.QuerySet):
    def for_company(self, user):
        return self.filter(job_post__company__user_account=user)

    def for_published_jobs(self):
        return self.filter(job_post__is_published=True)

    def with_related(self):
        return self.select_related('job_post', 'skill_set')
