"""
Entry point del worker. Se ejecuta como:
    python -m app.tasks.worker
Consume la cola 'default' de Redis y ejecuta las funciones de app.tasks.jobs.
"""
import redis
from rq import Queue, Worker

from app.config import settings
from app.core.logging import setup_logging

redis_conn = redis.from_url(settings.redis_url)
queue = Queue("default", connection=redis_conn)

if __name__ == "__main__":
    setup_logging()
    worker = Worker([queue], connection=redis_conn)
    worker.work()
