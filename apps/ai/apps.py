from django.apps import AppConfig


class AiConfig(AppConfig):
    name = 'apps.ai'

    def ready(self):
        from . import signals  # noqa: F401  (registers the pre_delete receiver)
