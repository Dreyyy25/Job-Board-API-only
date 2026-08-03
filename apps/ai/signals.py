"""Purge checkpointer threads whenever a Conversation row goes away.

Conversation.user is CASCADE, and the chat messages live in the LangGraph
checkpointer tables, which have no foreign key to anything Django manages.
Without this receiver, deleting a UserAccount — or any bulk queryset delete —
removes the only row mapping a thread_id to a person and strands the entire
transcript in Postgres: unreachable by any user, unpurgeable by any code path.

Registering a pre_delete receiver also disables Django's fast-delete
optimisation, which is what makes this fire on cascades and bulk deletes
rather than only on instance.delete().

Two consequences of the thread-first, fail-closed design worth stating
explicitly (both deliberate, per the deletion-ordering argument in the
task brief):

* Partial-cascade transcript loss. Deleting a user with N conversations
  purges threads and rows one row at a time, each in its own DB
  transaction (see delete_conversation / _rollback_new_conversation for
  why the purge itself cannot join the Django transaction). If the purge
  for conversation #2 fails, Django rolls back that ROW delete — but
  conversation #1's thread is already gone: the checkpointer runs on an
  autocommit pool with no transaction to roll back. The failure still
  aborts the whole cascade (the user row itself does not delete either),
  so nothing is stranded UNREACHABLE — every surviving row is still
  listed and its (now-empty) thread purge can be retried. But a
  conversation can end up rowed-and-listed with its transcript already
  gone, which is a real, visible inconsistency a retry does not undo for
  that one conversation.
* Fail-closed blocks erasure. While the checkpointer is unreachable, this
  receiver raising means account deletion itself fails — a GDPR erasure
  request 500s instead of completing. That is intentional: the
  alternative (deleting the account row while a purge failure leaves a
  transcript behind) is the unpurgeable-forever failure this whole module
  exists to prevent. An operator must restore checkpointer access before
  the erasure can complete, not silently accept a partial one.
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
