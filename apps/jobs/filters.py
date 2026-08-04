import django_filters

from .models import JobPost


class JobPostFilter(django_filters.FilterSet):
    city = django_filters.CharFilter(field_name="job_location__city", lookup_expr="icontains")
    country = django_filters.CharFilter(field_name="job_location__country", lookup_expr="exact")
    salary_min_gte = django_filters.NumberFilter(field_name="salary_min", lookup_expr="gte")
    salary_max_lte = django_filters.NumberFilter(field_name="salary_max", lookup_expr="lte")
    deadline_before = django_filters.DateFilter(field_name="deadline_date", lookup_expr="lte")
    required_skill = django_filters.UUIDFilter(field_name="required_skills__skill_set")

    class Meta:
        model = JobPost
        fields = ["job_type", "company", "salary_type", "is_published"]
