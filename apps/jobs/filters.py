import django_filters

from .models import JobPost


class JobPostFilter(django_filters.FilterSet):
    city = django_filters.CharFilter(field_name="job_location__city", lookup_expr="icontains")
    country = django_filters.CharFilter(field_name="job_location__country", lookup_expr="exact")
    salary_min_gte = django_filters.NumberFilter(field_name="salary_min", lookup_expr="gte")
    salary_max_lte = django_filters.NumberFilter(field_name="salary_max", lookup_expr="lte")
    salary_floor = django_filters.NumberFilter(method="filter_salary_floor")
    deadline_before = django_filters.DateFilter(field_name="deadline_date", lookup_expr="lte")
    required_skill = django_filters.UUIDFilter(field_name="required_skills__skill_set")
    business_stream = django_filters.UUIDFilter(field_name="company__business_stream")

    def filter_salary_floor(self, queryset, name, value):
        """'Could I earn at least X here': COALESCE(salary_max, salary_min) >= X."""
        return queryset.with_salary_floor(value)

    class Meta:
        model = JobPost
        fields = ["job_type", "company", "salary_type", "is_published", "is_active"]
