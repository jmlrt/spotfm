import asyncio
import io
import sys
import uuid
from dataclasses import dataclass, field
from enum import StrEnum


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Job:
    id: str
    name: str
    status: JobStatus = JobStatus.PENDING
    progress: list[str] = field(default_factory=list)
    result: object = None
    error: str | None = None


_jobs: dict[str, Job] = {}


def create_job(name: str) -> Job:
    job = Job(id=str(uuid.uuid4()), name=name)
    _jobs[job.id] = job
    return job


def get_job(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def reset_jobs():
    """Clear all jobs. For testing purposes only."""
    _jobs.clear()


def get_running_job(name: str) -> Job | None:
    for job in _jobs.values():
        if job.name == name and job.status == JobStatus.RUNNING:
            return job
    return None


async def run_job(job: Job, fn, *args, **kwargs):
    job.status = JobStatus.RUNNING

    # Capture stderr output as progress lines
    old_stderr = sys.stderr
    buf = io.StringIO()

    def run():
        nonlocal buf
        sys.stderr = buf
        try:
            result = fn(*args, **kwargs)
            return result
        finally:
            sys.stderr = old_stderr

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, run)
        job.progress = [line for line in buf.getvalue().splitlines() if line.strip()]
        job.result = result
        job.status = JobStatus.DONE
    except Exception as e:
        job.progress = [line for line in buf.getvalue().splitlines() if line.strip()]
        job.error = str(e)
        job.status = JobStatus.FAILED
    finally:
        sys.stderr = old_stderr
