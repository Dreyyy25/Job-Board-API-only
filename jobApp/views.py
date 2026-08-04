"""Project-level plain-Django views (not DRF): infrastructure endpoints."""

from django.db import connection
from django.http import JsonResponse


def healthz(request):
    """Health probe: cheap DB ping, no auth/throttling, invisible to the
    OpenAPI schema (plain Django view — drf-spectacular never sees it)."""
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
    except Exception:
        return JsonResponse({'status': 'error'}, status=503)
    return JsonResponse({'status': 'ok'})
