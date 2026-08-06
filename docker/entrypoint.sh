#!/bin/sh
# Container start: apply DB state, then serve. Both steps are idempotent.
# They run here (not a deploy hook) because Render's free instance type
# has no pre-deploy command.
set -e

python manage.py migrate --noinput
python manage.py ai_checkpointer_setup

# --timeout 120 is load-bearing: an AI chat turn may legitimately run up
# to its 90 s deadline; a shorter gunicorn timeout would kill the worker.
exec gunicorn jobApp.wsgi:application \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-2}" \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
