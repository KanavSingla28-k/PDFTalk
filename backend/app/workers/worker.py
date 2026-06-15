import threading
import time

import redis
import structlog
from rq import Queue, Worker
from rq.registry import FailedJobRegistry

from app.core.config import settings
from app.utils.metrics import dead_letter_queue_length, queue_length
from app.workers.queue_poller import start_queue_poller
from app.utils.redis_client import get_sync_redis

logger = structlog.get_logger(__name__)


def _poll_queue_metrics(conn: redis.Redis, interval: int = 15) -> None:
    """
    Daemon thread — updates queue depth Gauges every `interval` seconds.
    Runs for the lifetime of the worker process. Errors are swallowed so
    a Redis blip never takes down the worker.
    """
    ingest_q = Queue("ingest", connection=conn)
    failed_registry = FailedJobRegistry("ingest", connection=conn)
    while True:
        try:
            queue_length.set(ingest_q.count)
            dead_letter_queue_length.set(failed_registry.count)  # O(1) ZCARD
        except Exception:
            pass  # Never crash the worker over a metrics update
        time.sleep(interval)


def main() -> None:
    conn = redis.Redis.from_url(settings.REDIS_URL, decode_responses=False)

    ingest_q = Queue(
        "ingest",
        connection=conn,
        default_timeout=600,
    )

    default_q = Queue(
        "default",
        connection=conn,
    )

    # Start queue depth poller before the worker blocks on .work()
    poller = threading.Thread(
        target=_poll_queue_metrics,
        args=(conn,),
        daemon=True,  # Dies automatically when the main process exits
    )
    poller.start()
    logger.info("Queue metrics poller started (interval=15s)")

    worker = Worker(
        queues=[ingest_q, default_q],
        connection=conn,
        exception_handlers=[],
    )

    logger.info("RQ worker starting — listening on 'ingest' and 'default' queues")
    redis_conn = get_sync_redis()
    start_queue_poller(redis_conn)
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
