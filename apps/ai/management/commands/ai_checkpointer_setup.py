"""Create the LangGraph checkpointer tables. Run once per environment at deploy.

Idempotent: PostgresSaver.setup() re-runs its own migrations safely.
"""
from django.core.management.base import BaseCommand

from apps.ai.checkpointer import get_checkpointer


class Command(BaseCommand):
    help = "Create/upgrade the LangGraph checkpointer tables used by AI chat."

    def handle(self, *args, **options):
        get_checkpointer().setup()
        self.stdout.write(self.style.SUCCESS("Checkpointer tables ready."))
