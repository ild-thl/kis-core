"""The one place that knows where Redis lives."""

import os

REDIS_URL = os.environ.get("REDIS_URL", "redis://askf-redis:6379/0")
# Celery keeps task results apart from the queue, in a database of its own.
CELERY_RESULT_URL = os.environ.get("CELERY_RESULT_URL", "redis://askf-redis:6379/1")
