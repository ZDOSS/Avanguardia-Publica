from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "avanguardia",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.timezone = "UTC"
celery_app.conf.task_default_queue = "avanguardia"
celery_app.conf.imports = ["app.etl.tasks"]
celery_app.autodiscover_tasks(["app.etl"])
