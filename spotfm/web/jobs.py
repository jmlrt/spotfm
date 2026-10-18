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
# Finished jobs are kept for results pages, but capped so a long-lived server
# doesn't accumulate them (dupe results can be large lists)
_MAX_COMPLETED_JOBS = 50
_progress_lock = threading.Lock()


def _prune_completed_jobs():
    completed = [job for job in _jobs.values() if job.status in (JobStatus.DONE, JobStatus.FAILED)]
    # _jobs preserves creation order — drop the oldest completed jobs beyond the cap
    for job in completed[: max(0, len(completed) - _MAX_COMPLETED_JOBS)]:
        del _jobs[job.id]


def create_job(name: str) -> Job:
    job = Job(id=str(uuid.uuid4()), name=name)
    _jobs[job.id] = job
    _prune_completed_jobs()
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


# The event loop only keeps weak references to tasks, so an unreferenced
# background task can be garbage-collected mid-run — keep strong refs until done.
_background_tasks: set[asyncio.Task] = set()


def spawn_job(job: Job, fn, *args, **kwargs) -> asyncio.Task:
    """Schedule run_job as a tracked background task and return it."""
    task = asyncio.create_task(run_job(job, fn, *args, **kwargs))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def run_job(job: Job, fn, *args, **kwargs):
    job.status = JobStatus.RUNNING

    class JobLogHandler(logging.Handler):
        # Set once fn starts on its executor thread; records from other threads
        # (other concurrent jobs) must not leak into this job's progress
        job_thread_id: int | None = None

        def emit(self, record):
            if record.thread != self.job_thread_id:
                return
            msg = self.format(record)
            if msg.strip():
                with _progress_lock:
                    job.progress.append(msg)

    handler = JobLogHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logging.getLogger().addHandler(handler)

    def run():
        handler.job_thread_id = threading.get_ident()
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
        logging.getLogger().removeHandler(handler)
