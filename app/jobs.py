"""Chop etish navbati: vazifalar fonda ketma-ket bajariladi."""
import itertools
import queue
import threading
import time
from collections import deque
from datetime import datetime


class Job:
    _ids = itertools.count(1)

    def __init__(self, payload: dict, source: str = ""):
        self.id = next(Job._ids)
        self.payload = payload
        self.source = source
        self.created = datetime.now()
        self.status = "navbatda"     # navbatda -> chiqarilmoqda -> tayyor | xato
        self.error = ""
        self.result = {}
        self.done_event = threading.Event()

    def to_dict(self):
        return {
            "id": self.id,
            "time": self.created.strftime("%H:%M:%S"),
            "date": self.created.strftime("%Y-%m-%d"),
            "printer": self.result.get("printer") or self.payload.get("printer") or "",
            "status": self.status,
            "error": self.error,
            "source": self.source,
            **{k: v for k, v in self.result.items() if k != "printer"},
        }


class JobQueue:
    def __init__(self, manager, config, logger):
        self.manager = manager
        self.config = config
        self.logger = logger
        self._q = queue.Queue()
        self._history = deque(maxlen=int(config.get("history_limit") or 200))
        self._lock = threading.Lock()
        self._worker = threading.Thread(target=self._run, daemon=True,
                                        name="tprints-print-worker")
        self._worker.start()

    def submit(self, payload: dict, source: str = "") -> Job:
        job = Job(payload, source)
        with self._lock:
            self._history.appendleft(job)
        self._q.put(job)
        self.logger.info("Vazifa #%d navbatga qo'shildi (%s)", job.id, source or "lokal")
        return job

    def get_job(self, job_id: int):
        with self._lock:
            for j in self._history:
                if j.id == job_id:
                    return j
        return None

    def snapshot(self, limit: int = 100):
        with self._lock:
            return [j.to_dict() for j in list(self._history)[:limit]]

    def stats(self):
        with self._lock:
            jobs = list(self._history)
        return {
            "queued": self._q.qsize(),
            "total": len(jobs),
            "done": sum(1 for j in jobs if j.status == "tayyor"),
            "failed": sum(1 for j in jobs if j.status == "xato"),
        }

    def clear_history(self):
        with self._lock:
            finished = [j for j in self._history
                        if j.status in ("tayyor", "xato")]
            for j in finished:
                self._history.remove(j)

    def _run(self):
        while True:
            job = self._q.get()
            job.status = "chiqarilmoqda"
            t0 = time.time()
            try:
                job.result = self.manager.print_job(job.payload)
                job.status = "tayyor"
                self.logger.info("Vazifa #%d chop etildi (%.1fs, %s)",
                                 job.id, time.time() - t0,
                                 job.result.get("printer", "?"))
            except Exception as e:
                job.status = "xato"
                job.error = str(e)
                self.logger.error("Vazifa #%d xato: %s", job.id, e)
            finally:
                job.done_event.set()
                self._q.task_done()
