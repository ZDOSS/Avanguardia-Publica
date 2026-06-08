from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "avanguardia",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.timezone = "UTC"
celery_app.conf.task_default_queue = "avanguardia"
celery_app.conf.imports = ["app.etl.tasks"]

celery_app.conf.beat_schedule = {
    "sync-all-daily": {
        "task": "etl.sync_all_sources",
        "schedule": crontab(hour=4, minute=0),
    },
}
