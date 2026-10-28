"""JOB_RUNNER=inline: background jobs run as tasks in the API's own event loop instead of
going to Celery (for one free-tier instance with no worker)."""

import asyncio

import pytest

from app.core.config import get_celery_settings
from app.worker import dispatch


def _runner(monkeypatch, value):
    monkeypatch.setenv("JOB_RUNNER", value)
    get_celery_settings.cache_clear()


@pytest.fixture
def inline_runner(monkeypatch):
    _runner(monkeypatch, "inline")
    yield
    get_celery_settings.cache_clear()


async def _drain():
    while dispatch._running:
        await asyncio.gather(*dispatch._running, return_exceptions=True)


async def test_messages_run_in_the_loop_not_celery(inline_runner, monkeypatch):
    sent = []

    async def deliver(channel, to, body, subject=None):
        sent.append((channel, to, body, subject))

    def no_celery(*args, **kwargs):
        raise AssertionError("inline mode must not queue Celery tasks")

    monkeypatch.setattr("app.worker.messaging.deliver_message", deliver)
    monkeypatch.setattr("app.worker.messaging.send_message.delay", no_celery)
    await dispatch.dispatch_message("email", "a@b.com", "123456", "Your code")
    await _drain()
    assert sent == [("email", "a@b.com", "123456", "Your code")]


async def test_inline_messages_retry_then_give_up(monkeypatch):
    attempts, waits = [], []

    async def flaky(channel, to, body, subject=None):
        attempts.append(1)
        raise RuntimeError("provider down")

    async def sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr("app.worker.messaging.deliver_message", flaky)
    with pytest.raises(RuntimeError):
        await dispatch._deliver_with_retries("sms", "+256700000000", "hi", None, sleep=sleep)
    assert len(attempts) == dispatch.MESSAGE_RETRIES + 1
    assert waits == [5.0, 10.0, 20.0, 40.0]


async def test_pipeline_runs_inline(inline_runner, monkeypatch):
    ran = []

    async def run(tracking_id):
        ran.append(tracking_id)

    monkeypatch.setattr("app.worker.pipeline._run_in_worker", run)
    await dispatch.dispatch_pipeline("ZL-AAAA-11")
    await _drain()
    assert ran == ["ZL-AAAA-11"]


async def test_a_failed_job_is_logged_not_raised(inline_runner, monkeypatch, caplog):
    async def boom(tracking_id):
        raise RuntimeError("pipeline crashed")

    monkeypatch.setattr("app.worker.pipeline._run_in_worker", boom)
    await dispatch.dispatch_pipeline("ZL-BBBB-22")
    await _drain()
    assert "Background job pipeline:ZL-BBBB-22 failed" in caplog.text


async def test_periodic_jobs_only_start_inline(inline_runner, monkeypatch):
    _runner(monkeypatch, "celery")
    dispatch.start_periodic_jobs()()  # a no-op stop
    _runner(monkeypatch, "inline")
    stop = dispatch.start_periodic_jobs()
    assert any(t.get_name() == "brigading" for t in asyncio.all_tasks())
    stop()
