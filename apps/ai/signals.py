"""Purge checkpointer threads whenever a Conversation row goes away.

Conversation.user is CASCADE, and the chat messages live in the LangGraph
checkpointer tables, which have no foreign key to anything Django manages.
Without this receiver, deleting a UserAccount — or any bulk queryset delete —
removes the only row mapping a thread_id to a person and strands the entire
transcript in Postgres: unreachable by any user, unpurgeable by any code path.

Registering a pre_delete receiver also disables Django's fast-delete
optimisation, which is what makes this fire on cascades and bulk deletes
rather than only on instance.delete().
"""
import logging

from django.db.models.signals import pre_delete
from django.dispatch import receiver

from .checkpointer import get_checkpointer
from .models import Conversation

logger = logging.getLogger('apps.ai')


@receiver(pre_delete, sender=Conversation)
def purge_checkpointer_thread(sender, instance, **kwargs):
    """Delete the thread BEFORE the row. Raising here aborts the row delete,
    which is the safe direction: better a conversation that will not delete
    than message content nothing can ever reach."""
    # delete_conversation attaches the checkpointer it was given so the
    # service keeps its injectable test seam; cascades have no such hint.
    checkpointer = getattr(instance, '_checkpointer', None) or get_checkpointer()
    checkpointer.delete_thread(str(instance.id))
    logger.info('ai chat purged thread conversation=%s', instance.id)
