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
_progress_lock = threading.Lock()
_active_jobs = 0
_level_lock = threading.Lock()
_saved_root_level: int | None = None


def create_job(name: str) -> Job:
    job = Job(id=str(uuid.uuid4()), name=name)
    _jobs[job.id] = job
    return job


def get_job(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def reset_jobs():
    _jobs.clear()


def get_running_job(name: str) -> Job | None:
    for job in _jobs.values():
        if job.name == name and job.status in (JobStatus.PENDING, JobStatus.RUNNING):
            return job
    return None


def get_latest_job(name: str) -> Job | None:
    """Return the most recently created job with this name, regardless of status."""
    matches = [j for j in _jobs.values() if j.name == name]
    return matches[-1] if matches else None


async def run_job(job: Job, fn, *args, **kwargs):
    global _active_jobs, _saved_root_level
    job.status = JobStatus.RUNNING

    class JobLogHandler(logging.Handler):
        def emit(self, record):
            msg = self.format(record)
            if msg.strip():
                with _progress_lock:
                    job.progress.append(msg)

    handler = JobLogHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    root_logger = logging.getLogger()

    # Refcount: first job lowers the root log level; last job to finish restores it
    with _level_lock:
        if _active_jobs == 0:
            _saved_root_level = root_logger.level
            if _saved_root_level == logging.NOTSET or _saved_root_level > logging.INFO:
                root_logger.setLevel(logging.INFO)
        _active_jobs += 1
    root_logger.addHandler(handler)

    def run():
        return fn(*args, **kwargs)

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
        with _level_lock:
            _active_jobs -= 1
            if _active_jobs == 0 and _saved_root_level is not None:
                root_logger.setLevel(_saved_root_level)
