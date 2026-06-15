"""
workers/queue_poller.py

Background daemon thread that updates queue depth Gauges every 15 seconds.
Start this before calling rq.Worker(...).work() in the worker entrypoint.

Usage in workers/worker.py:
    from app.workers.queue_poller import start_queue_poller
    start_queue_poller(redis_conn)
    Worker(["ingest"], connection=redis_conn).work()
"""

import structlog
import threading
import time

from redis import Redis

from rq import Queue
from rq.registry import FailedJobRegistry

from app.utils.metrics import queue_length, dead_letter_queue_length

log = structlog.get_logger(__name__)

_POLL_INTERVAL = 15  # seconds


def _poll(redis_conn: Redis, interval: int) -> None:
    ingest_q        = Queue("ingest", connection=redis_conn)
    failed_registry = FailedJobRegistry("ingest", connection=redis_conn)

    while True:
        try:
            queue_length.set(ingest_q.count)
            dead_letter_queue_length.set(failed_registry.count)  # O(1) ZCARD
        except Exception:
            # Never crash the worker over a metrics update.
            log.debug("queue_poller: metric update failed", exc_info=True)
        time.sleep(interval)


def start_queue_poller(redis_conn: Redis, interval: int = _POLL_INTERVAL) -> None:
    """
    Start the queue depth poller as a daemon thread.
    Daemon=True means it exits automatically when the worker process exits.
    """
    t = threading.Thread(
        target=_poll,
        args=(redis_conn, interval),
        daemon=True,
        name="queue-poller",
    )
    t.start()
    log.info("queue_poller started (interval=%ds)", interval)
