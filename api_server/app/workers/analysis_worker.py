from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
from threading import Event, Thread

from app.core.config import get_settings
from app.integrations import redis_cache
from app.services.analysis_job_service import (
    acknowledge_analysis_job,
    cleanup_analysis_consumers,
    dequeue_analysis_job,
    ensure_analysis_consumer_group,
    execute_queued_analysis_job,
    remove_analysis_consumer,
    touch_analysis_job_message,
)
from app.services.local_classifier_service import warm_classifier


logger = logging.getLogger("supporthr.analysis_worker")
shutdown_requested = Event()


def _request_shutdown(_signum: int, _frame: object) -> None:
    shutdown_requested.set()


def _verify_runtime() -> None:
    settings = get_settings()
    if settings.analysis_job_mode != "redis":
        raise RuntimeError("Analysis worker requires ANALYSIS_JOB_MODE=redis.")
    if not redis_cache.ping():
        raise RuntimeError("Analysis worker cannot connect to Redis.")
    if not ensure_analysis_consumer_group():
        raise RuntimeError("Analysis worker cannot create or access its Redis consumer group.")
    classifier = warm_classifier()
    if settings.require_classifier_ready and not bool(classifier.get("ready")):
        raise RuntimeError(f"Classifier is not ready: {classifier.get('error')}")


def _heartbeat_message(message_id: str, consumer_name: str, stopped: Event) -> None:
    interval_seconds = max(30, min(300, get_settings().analysis_job_reclaim_idle_seconds // 3))
    while not stopped.wait(interval_seconds):
        if not touch_analysis_job_message(message_id, consumer_name):
            logger.warning("Unable to renew Redis lease for stream message %s", message_id)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    signal.signal(signal.SIGTERM, _request_shutdown)
    signal.signal(signal.SIGINT, _request_shutdown)
    _verify_runtime()
    consumer_name = f"{socket.gethostname()}-{os.getpid()}"
    cleaned_consumers = cleanup_analysis_consumers()
    if cleaned_consumers:
        logger.info("Removed %s stale Redis consumers.", cleaned_consumers)
    logger.info("Analysis worker started.")

    try:
        while not shutdown_requested.is_set():
            message = dequeue_analysis_job(consumer_name, timeout_seconds=5)
            if not message:
                continue
            message_id, job_id = message
            if not job_id:
                logger.warning("Acknowledging malformed analysis stream message %s", message_id)
                acknowledge_analysis_job(message_id)
                continue
            logger.info("Processing analysis job %s", job_id)
            heartbeat_stopped = Event()
            heartbeat = Thread(
                target=_heartbeat_message,
                args=(message_id, consumer_name, heartbeat_stopped),
                daemon=True,
            )
            heartbeat.start()
            try:
                asyncio.run(execute_queued_analysis_job(job_id))
                acknowledge_analysis_job(message_id)
            except Exception:
                logger.exception("Unhandled worker failure for job %s", job_id)
            finally:
                heartbeat_stopped.set()
                heartbeat.join(timeout=1)
    finally:
        remove_analysis_consumer(consumer_name)
        logger.info("Analysis worker stopped.")


if __name__ == "__main__":
    main()
