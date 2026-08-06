"""Create the LangGraph checkpointer tables. Run once per environment at deploy.

Idempotent: PostgresSaver.setup() re-runs its own migrations safely.
"""

from django.core.management.base import BaseCommand

from apps.ai.checkpointer import get_checkpointer, reset_checkpointer


class Command(BaseCommand):
    help = "Create/upgrade the LangGraph checkpointer tables used by AI chat."

    def handle(self, *args, **options):
        # finally: this is a short-lived process — an unclosed pool makes
        # interpreter shutdown wait out one ~5s timeout per worker thread
        # (~20s per container boot), and on failure that noise would land
        # after the real traceback.
        try:
            get_checkpointer().setup()
        finally:
            reset_checkpointer()
        self.stdout.write(self.style.SUCCESS("Checkpointer tables ready."))
