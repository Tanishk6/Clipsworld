"""Background jobs with progress the UI can poll."""
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor

_pool = ThreadPoolExecutor(max_workers=2)
_jobs: dict = {}
_lock = threading.Lock()


class Cancelled(Exception):
    pass


class Job:
    def __init__(self, kind: str, project_id: str | None):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.project_id = project_id
        self.status = "running"   # running, done, error, cancelled
        self.progress = 0.0
        self.stage = "Starting…"
        self.result = None
        self.error = None
        self.cancel_requested = False

    def update(self, progress: float | None = None, stage: str | None = None):
        if self.cancel_requested:
            raise Cancelled()
        if progress is not None:
            self.progress = max(0.0, min(1.0, float(progress)))
        if stage is not None:
            self.stage = stage

    def to_dict(self):
        return {
            "id": self.id, "kind": self.kind, "project_id": self.project_id,
            "status": self.status, "progress": round(self.progress, 4),
            "stage": self.stage, "result": self.result, "error": self.error,
        }


def start(kind: str, project_id: str | None, fn, *args) -> Job:
    job = Job(kind, project_id)
    with _lock:
        _jobs[job.id] = job

    def run():
        try:
            job.result = fn(job, *args)
            job.progress = 1.0
            job.status = "done"
            job.stage = "Done"
        except Cancelled:
            job.status = "cancelled"
            job.stage = "Cancelled"
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            job.status = "error"
            job.error = str(e) or e.__class__.__name__
            job.stage = "Failed"

    _pool.submit(run)
    return job


def get(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def all_jobs():
    return [j.to_dict() for j in list(_jobs.values())[-50:]]


def cancel(job_id: str) -> bool:
    j = _jobs.get(job_id)
    if j and j.status == "running":
        j.cancel_requested = True
        return True
    return False
