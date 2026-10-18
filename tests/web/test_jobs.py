import pytest


@pytest.mark.unit
def test_create_job():
    from spotfm.web.jobs import JobStatus, create_job

    job = create_job("test")
    assert job.status == JobStatus.PENDING
    assert job.name == "test"
    assert job.id


@pytest.mark.unit
def test_get_job():
    from spotfm.web.jobs import create_job, get_job

    job = create_job("get-test")
    found = get_job(job.id)
    assert found is job


@pytest.mark.unit
def test_get_job_missing():
    from spotfm.web.jobs import get_job

    assert get_job("nonexistent") is None


@pytest.mark.unit
def test_get_running_job():
    from spotfm.web.jobs import JobStatus, create_job, get_running_job

    job = create_job("running-test")
    job.status = JobStatus.RUNNING
    found = get_running_job("running-test")
    assert found is job


@pytest.mark.unit
def test_get_running_job_done_not_returned():
    from spotfm.web.jobs import JobStatus, create_job, get_running_job

    job = create_job("done-test")
    job.status = JobStatus.DONE
    found = get_running_job("done-test")
    assert found is None


@pytest.mark.asyncio
async def test_run_job_success():
    from spotfm.web.jobs import JobStatus, create_job, run_job

    job = create_job("success-test")

    def fn():
        import sys

        print("progress line", file=sys.stderr, flush=True)
        return "result"

    await run_job(job, fn)
    assert job.status == JobStatus.DONE
    assert job.result == "result"
    assert job.error is None


@pytest.mark.asyncio
async def test_run_job_failure():
    from spotfm.web.jobs import JobStatus, create_job, run_job

    job = create_job("fail-test")

    def fn():
        raise ValueError("boom")

    await run_job(job, fn)
    assert job.status == JobStatus.FAILED
    assert "boom" in job.error


@pytest.mark.asyncio
async def test_spawn_job_tracks_task_until_done():
    """spawn_job must keep a strong reference to the task while it runs, then release it."""
    import asyncio

    from spotfm.web.jobs import JobStatus, _background_tasks, create_job, spawn_job

    job = create_job("spawn-test")

    task = spawn_job(job, lambda: "done")
    assert task in _background_tasks

    await task
    await asyncio.sleep(0)  # let the done callback run

    assert task not in _background_tasks
    assert job.status == JobStatus.DONE
    assert job.result == "done"


@pytest.mark.asyncio
async def test_spawn_job_failure_marks_job_failed():
    from spotfm.web.jobs import JobStatus, create_job, spawn_job

    job = create_job("spawn-fail-test")

    def _boom():
        raise RuntimeError("job exploded")

    task = spawn_job(job, _boom)
    await task

    assert job.status == JobStatus.FAILED
    assert "job exploded" in job.error


@pytest.mark.unit
def test_create_job_prunes_old_completed_jobs(monkeypatch):
    """Completed jobs are capped; the newest are kept, the oldest are dropped."""
    from spotfm.web.jobs import JobStatus, _jobs, create_job, get_job

    monkeypatch.setattr("spotfm.web.jobs._MAX_COMPLETED_JOBS", 3)

    first = create_job("prune-test")
    first.status = JobStatus.DONE
    for i in range(5):
        job = create_job(f"done-{i}")
        job.status = JobStatus.DONE

    # One more create triggers a prune; the fresh job is PENDING so it is never pruned itself
    pending = create_job("pending")

    assert get_job(first.id) is None, "oldest completed jobs must be pruned"
    completed = [j for j in _jobs.values() if j.status == JobStatus.DONE]
    assert len(completed) == 3
    assert get_job(pending.id) is not None


@pytest.mark.unit
def test_create_job_never_prunes_running_jobs(monkeypatch):
    """Running jobs must survive pruning regardless of how many completed jobs exist."""
    from spotfm.web.jobs import JobStatus, _jobs, create_job, get_job

    monkeypatch.setattr("spotfm.web.jobs._MAX_COMPLETED_JOBS", 2)

    running = create_job("long-running")
    running.status = JobStatus.RUNNING
    for i in range(6):
        job = create_job(f"done-{i}")
        job.status = JobStatus.DONE

    create_job("pending")  # triggers a prune

    assert get_job(running.id) is not None
    completed = [j for j in _jobs.values() if j.status == JobStatus.DONE]
    assert len(completed) == 2


@pytest.mark.asyncio
async def test_run_job_captures_info_logs():
    """INFO log records emitted by the job function must land in job.progress (live logs)."""
    import logging

    from spotfm.web.jobs import create_job, run_job

    root = logging.getLogger()
    previous_level = root.level
    root.setLevel(logging.INFO)
    try:
        job = create_job("log-test")

        def fn():
            logging.getLogger("spotfm.jobtest").info("hello from the job")
            return "ok"

        await run_job(job, fn)
        assert job.status == "done"
        assert any("hello from the job" in line for line in job.progress)
    finally:
        root.setLevel(previous_level)


@pytest.mark.asyncio
async def test_run_job_progress_isolated_between_concurrent_jobs():
    """Concurrent jobs must not capture each other's log lines in their progress.

    Each job attaches a handler to the root logger, so without a thread filter a
    record from job B's executor thread would also land in job A's progress.
    """
    import logging
    import threading

    from spotfm.web.jobs import create_job, run_job

    root = logging.getLogger()
    previous_level = root.level
    root.setLevel(logging.INFO)
    try:
        job_a = create_job("cross-talk-a")
        job_b = create_job("cross-talk-b")

        logged_a = threading.Event()
        logged_b = threading.Event()

        def fn_a():
            logging.getLogger("spotfm.crosstest").info("log from A")
            logged_a.set()
            logged_b.wait(timeout=5)
            return "a"

        def fn_b():
            logged_a.wait(timeout=5)
            logging.getLogger("spotfm.crosstest").info("log from B")
            logged_b.set()
            return "b"

        import asyncio

        await asyncio.gather(run_job(job_a, fn_a), run_job(job_b, fn_b))

        assert any("log from A" in line for line in job_a.progress)
        assert not any("log from B" in line for line in job_a.progress)
        assert any("log from B" in line for line in job_b.progress)
        assert not any("log from A" in line for line in job_b.progress)
    finally:
        root.setLevel(previous_level)
