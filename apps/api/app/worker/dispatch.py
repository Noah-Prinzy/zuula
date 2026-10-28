"""Handing committed work to the background.

Where it runs is JOB_RUNNER (app/core/config.py's CelerySettings):

- "celery" (default): Celery tasks, run by the worker process against its own database
  connection.
- "inline": the same work as asyncio tasks inside the API's own event loop, each on its own
  database connection. For a single free-tier instance with no worker (Render free; see
  docs/zuula_state.md §11). A job still running when the process stops is lost.

Either way, the rows a job reads must be committed first — callers commit, then dispatch.

The contract tests replace these functions (tests/contract/conftest.py) with ones that await
the same work inline on the test's own database connection, so a request's effects are
complete when it returns and everything stays inside the test's rolled-back transaction.
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from app.core.config import get_celery_settings

logger = logging.getLogger("zuula.worker.dispatch")

# Inline jobs still running. The event loop keeps only weak references to tasks, so without
# this a job could be garbage-collected halfway through.
_running: set[asyncio.Task] = set()

# Inline email/SMS: the same retries Celery's send_message gets (4, backing off).
MESSAGE_RETRIES = 4
MESSAGE_BACKOFF_SECONDS = 5.0

# Inline mode's stand-in for Celery beat: the brigading check every 5 minutes.
BRIGADING_INTERVAL_SECONDS = 300.0


def inline() -> bool:
    return get_celery_settings().job_runner == "inline"


def _spawn(name: str, job: Coroutine[Any, Any, Any]) -> None:
    task = asyncio.get_running_loop().create_task(job, name=name)
    _running.add(task)
    task.add_done_callback(_finished)


def _finished(task: asyncio.Task) -> None:
    _running.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.error("Background job %s failed", task.get_name(), exc_info=task.exception())


async def dispatch_pipeline(tracking_id: str) -> None:
    from app.worker.pipeline import _run_in_worker, run_submission_pipeline

    if inline():
        _spawn(f"pipeline:{tracking_id}", _run_in_worker(tracking_id))
    else:
        run_submission_pipeline.delay(tracking_id)


async def dispatch_recompute(report_ids: list[str] | None = None) -> None:
    """Recompute community scores (all reports when None): after a weight/threshold change,
    or after a user's ratings were dropped or restored."""
    from app.services.recompute import recompute_reports
    from app.worker.admin_tasks import _with_session, recompute_scores

    if inline():
        _spawn("recompute", _with_session(lambda db: recompute_reports(db, report_ids)))
    else:
        recompute_scores.delay(report_ids)


async def dispatch_broadcast(broadcast_id: str) -> None:
    """Deliver a broadcast over its SMS/email channels (in-app is written synchronously)."""
    from app.services import broadcasts
    from app.worker.admin_tasks import _with_session, deliver_broadcast

    if inline():
        _spawn(
            f"broadcast:{broadcast_id}",
            _with_session(lambda db: broadcasts.deliver_channels(db, broadcast_id)),
        )
    else:
        deliver_broadcast.delay(broadcast_id)


async def _deliver_with_retries(
    channel: str, to: str, body: str, subject: str | None, sleep: Callable = asyncio.sleep
) -> None:
    from app.worker.messaging import deliver_message

    for attempt in range(MESSAGE_RETRIES + 1):
        try:
            await deliver_message(channel, to, body, subject)
            return
        except Exception:
            if attempt == MESSAGE_RETRIES:
                raise
            logger.warning("Sending %s failed (attempt %d), retrying", channel, attempt + 1)
            await sleep(MESSAGE_BACKOFF_SECONDS * 2**attempt)


async def dispatch_message(channel: str, to: str, body: str, subject: str | None = None) -> None:
    """Send one SMS ("sms") or email ("email") off the request path: codes, alerts,
    broadcasts."""
    from app.worker.messaging import send_message

    if inline():
        _spawn(f"message:{channel}", _deliver_with_retries(channel, to, body, subject))
    else:
        send_message.delay(channel, to, body, subject)


async def _brigading_loop() -> None:
    from app.services import brigading
    from app.worker.admin_tasks import _with_session

    while True:
        await asyncio.sleep(BRIGADING_INTERVAL_SECONDS)
        try:
            await _with_session(brigading.detect)
        except Exception:
            logger.exception("Brigading check failed")


def start_periodic_jobs() -> Callable[[], None]:
    """Inline mode only: start the periodic jobs Celery beat would run. Returns a stop
    function for the app's shutdown."""
    if not inline():
        return lambda: None
    task = asyncio.get_running_loop().create_task(_brigading_loop(), name="brigading")
    return task.cancel
