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
