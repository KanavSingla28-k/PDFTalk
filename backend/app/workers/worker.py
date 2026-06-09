import logging

import redis
from rq import Queue, Worker
from rq.timeouts import JobTimeoutException

from app.core.config import settings
from app.workers.failure_handler import handle_ingest_failure

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

RETRY_DELAYS = [30, 120, 480]  # seconds: 30s → 2m → 8m

def main() -> None:
    conn = redis.Redis.from_url(settings.REDIS_URL, decode_responses=False)

    ingest_q = Queue(
        "ingest",
        connection=conn,
        default_timeout=600,  # 10 min max per job — protects against hung PyMuPDF
    )

    worker = Worker(
        queues=[ingest_q],
        connection=conn,
        exception_handlers=[],  # RQ's built-in handler moves to failed queue
    )

    logger.info("RQ worker starting — listening on 'ingest' queue")
    worker.work(with_scheduler=True)  # --with-scheduler handles retry timing


if __name__ == "__main__":
    main()