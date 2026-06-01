import asyncio
import logging
import threading
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
_jobs_lock = threading.Lock()


def create_job(name: str) -> Job:
    job = Job(id=str(uuid.uuid4()), name=name)
    with _jobs_lock:
        _jobs[job.id] = job
    return job


def get_job(job_id: str) -> Job | None:
    with _jobs_lock:
        return _jobs.get(job_id)


def reset_jobs():
    """Clear all jobs. For testing purposes only."""
    with _jobs_lock:
        _jobs.clear()


def get_running_job(name: str) -> Job | None:
    with _jobs_lock:
        for job in _jobs.values():
            if job.name == name and job.status == JobStatus.RUNNING:
                return job
    return None


async def run_job(job: Job, fn, *args, **kwargs):
    job.status = JobStatus.RUNNING

    # Capture logging output as progress lines
    class JobLogHandler(logging.Handler):
        def emit(self, record):
            msg = self.format(record)
            if msg.strip():
                with _jobs_lock:
                    job.progress.append(msg)

    handler = JobLogHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)

    def run():
        try:
            result = fn(*args, **kwargs)
            return result
        finally:
            root_logger.removeHandler(handler)

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, run)
        job.result = result
        job.status = JobStatus.DONE
    except Exception as e:
        job.error = str(e)
        job.status = JobStatus.FAILED
    finally:
        root_logger.removeHandler(handler)
