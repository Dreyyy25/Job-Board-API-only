"""Project-level tests: the /healthz endpoint and its schema invisibility."""

import json
from unittest.mock import patch

from django.test import TestCase


class HealthzTests(TestCase):
    def test_healthz_returns_ok(self):
        response = self.client.get('/healthz')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok'})

    def test_healthz_db_failure_returns_503(self):
        with patch('jobApp.views.connection') as mock_conn:
            mock_conn.cursor.side_effect = Exception('db down')
            response = self.client.get('/healthz')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'status': 'error'})

    def test_healthz_is_not_in_openapi_schema(self):
        response = self.client.get('/api/schema/?format=json')
        self.assertEqual(response.status_code, 200)
        schema = json.loads(response.content)
        self.assertNotIn('/healthz', schema['paths'])
