"""Manual smoke check: one cheap Flash call. Requires a real GEMINI_API_KEY.

Run after deploys: uv run python manage.py ai_smoke
Deliberately NOT exercised by the test suite (network + billable).
"""

from django.core.management.base import BaseCommand, CommandError

from apps.ai.llm import get_model


class Command(BaseCommand):
    help = "Make one cheap Gemini Flash call to verify AI connectivity."

    def handle(self, *args, **options):
        model = get_model('flash')
        try:
            reply = model.invoke("Reply with exactly: OK")
        except Exception as exc:
            raise CommandError(f"Gemini call failed: {type(exc).__name__}: {exc}")
        usage = reply.usage_metadata or {}
        self.stdout.write(
            self.style.SUCCESS(
                f"model={model.model} reply={reply.content!r} "
                f"in={usage.get('input_tokens')} out={usage.get('output_tokens')}"
            )
        )
