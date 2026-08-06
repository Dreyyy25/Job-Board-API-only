import django_filters

from .models import Company


class PublicCompanyFilter(django_filters.FilterSet):
    business_stream = django_filters.UUIDFilter(field_name="business_stream")

    class Meta:
        model = Company
        fields = ["business_stream"]
