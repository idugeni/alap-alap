"""
Alap-Alap Solver Pool

Every ``POST /solve`` used to construct its own :class:`~src.core.AlapAlap`,
which meant launching Camoufox from scratch per request. Browser startup is the
most expensive part of a solve, so this module keeps browsers warm between
requests and turns solving into a queue of jobs.

Thread affinity is the constraint that shapes the design. Playwright's
synchronous API is not thread safe: a browser created on one thread cannot be
driven from another. So the pool does not hand browsers out. Instead each worker
thread owns exactly one browser for its lifetime and pulls jobs from a shared
queue, which means:

* browsers are reused, so the launch cost is paid once per worker
* ``api.MAX_CONCURRENT_SOLVES`` is both the concurrency cap and the browser count
* the queue replaces the semaphore that used to gate concurrency

A pooled browser is launched with a fixed proxy, so a worker relaunches when a
job asks for a different one. Requests sharing a proxy (the common case: none,
or one fixed proxy) reuse the running browser.
"""

from __future__ import annotations

import contextlib
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from loguru import logger

from src.config import ApiConfig, config
from src.core import AlapAlap
from src.models import SolveRequest

JobStatus = Literal["queued", "running", "done", "error"]

#: Distinguishes "no proxy requested" from "no job handled yet".
_UNSET = object()


@dataclass
class SolveJob:
    """A queued or completed solve."""

    id: str
    request: SolveRequest
    status: JobStatus = "queued"
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    worker: int | None = None
    #: Set once the outcome has been mirrored into the sitekeys database, so
    #: polling a finished job repeatedly does not inflate the solve counters.
    recorded: bool = False
    _done: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def finished(self) -> bool:
        return self.status in ("done", "error")

    @property
    def queue_time(self) -> float:
        """Seconds spent waiting before a worker picked the job up."""
        if self.started_at is None:
            return time.time() - self.created_at
        return self.started_at - self.created_at

    @property
    def run_time(self) -> float:
        """Seconds spent solving."""
        if self.started_at is None:
            return 0.0
        end = self.finished_at if self.finished_at is not None else time.time()
        return end - self.started_at

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the job finishes. Returns whether it did."""
        return self._done.wait(timeout)

    def to_dict(self, *, include_token: bool = True) -> dict[str, Any]:
        """Serialize for an API response."""
        payload: dict[str, Any] = {
            "job_id": self.id,
            "status": self.status,
            "url": self.request.url,
            "queued_for": round(self.queue_time, 3),
            "solve_time": round(self.run_time, 3),
        }

        if self.status == "done" and self.result is not None:
            result = dict(self.result)
            if not include_token:
                result["token"] = None
                result["token_withheld"] = True
            payload.update(result)
        elif self.status == "error":
            payload["success"] = False
            payload["error"] = self.error
        else:
            payload["success"] = None

        return payload


class QueueFullError(RuntimeError):
    """Raised when the backlog is at ``api.QUEUE_MAX_SIZE``."""


class SolverPool:
    """
    A pool of worker threads, each owning one browser.

    Worker threads start lazily on the first submitted job, so importing or
    constructing the Flask app never launches a browser. That keeps the test
    suite and ``--help`` free of side effects.
    """

    def __init__(
        self,
        api_config: ApiConfig | None = None,
        *,
        headless: bool = True,
        alap_factory=None,
    ):
        self._cfg = api_config or config.api
        self._headless = headless
        # Injectable so tests can supply a fake browser.
        self._alap_factory = alap_factory or AlapAlap

        self.workers = max(1, self._cfg.MAX_CONCURRENT_SOLVES)
        self._queue: queue.Queue[SolveJob | None] = queue.Queue(
            maxsize=max(1, self._cfg.QUEUE_MAX_SIZE)
        )
        self._jobs: dict[str, SolveJob] = {}
        self._threads: list[threading.Thread] = []
        self._lock = threading.RLock()
        self._stopping = threading.Event()
        self._started = False
        self._launches = 0
        self._completed = 0
        self._failed = 0

    # ----------------------------------------------------------------- #
    # Lifecycle
    # ----------------------------------------------------------------- #

    def _ensure_started(self) -> None:
        """Spin up worker threads on first use."""
        with self._lock:
            if self._started or self._stopping.is_set():
                return
            for index in range(self.workers):
                thread = threading.Thread(
                    target=self._worker_loop,
                    args=(index,),
                    name=f"alap-solver-{index}",
                    daemon=True,
                )
                thread.start()
                self._threads.append(thread)
            self._started = True
            logger.info(f"Solver pool started with {self.workers} worker(s)")

    def shutdown(self, timeout: float = 30.0) -> None:
        """Stop the workers and close their browsers."""
        with self._lock:
            if not self._started:
                self._stopping.set()
                return
            self._stopping.set()

        # One sentinel per worker so each loop wakes up and exits. A full queue
        # is fine: the 0.25s poll timeout means workers notice _stopping anyway.
        for _ in self._threads:
            with contextlib.suppress(queue.Full):
                self._queue.put_nowait(None)

        deadline = time.time() + timeout
        for thread in self._threads:
            thread.join(timeout=max(0.0, deadline - time.time()))

        with self._lock:
            self._threads.clear()
            self._started = False
        logger.info("Solver pool stopped")

    def __enter__(self) -> SolverPool:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.shutdown()

    # ----------------------------------------------------------------- #
    # Submission
    # ----------------------------------------------------------------- #

    def submit(self, request: SolveRequest) -> SolveJob:
        """
        Enqueue a solve and return immediately.

        Raises:
            QueueFullError: If the backlog is full.
        """
        if self._stopping.is_set():
            raise QueueFullError("Pool is shutting down")

        self._ensure_started()
        job = SolveJob(id=uuid.uuid4().hex[:16], request=request)

        try:
            self._queue.put_nowait(job)
        except queue.Full as exc:
            raise QueueFullError(
                f"Solver queue is full ({self._cfg.QUEUE_MAX_SIZE} waiting)"
            ) from exc

        with self._lock:
            self._jobs[job.id] = job
            self._evict()

        logger.debug(f"Queued job {job.id} for {request.url}")
        return job

    def solve(self, request: SolveRequest, timeout: float | None = None) -> SolveJob:
        """
        Enqueue a solve and wait for it, preserving the synchronous endpoint.

        The returned job may still be ``queued`` or ``running`` if the wait
        elapsed; the caller decides whether that is a timeout or a redirect to
        polling.
        """
        job = self.submit(request)
        budget = self._cfg.CONCURRENCY_WAIT_S if timeout is None else timeout
        job.wait(budget)
        return job

    # ----------------------------------------------------------------- #
    # Retrieval
    # ----------------------------------------------------------------- #

    def get(self, job_id: str) -> SolveJob | None:
        """Look up a job by id."""
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self, limit: int = 100) -> list[SolveJob]:
        """Most recent jobs first."""
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    def stats(self) -> dict[str, Any]:
        """Pool state, for /health and /stats."""
        with self._lock:
            jobs = list(self._jobs.values())
            return {
                "workers": self.workers,
                "started": self._started,
                "pool_enabled": self._cfg.POOL_ENABLED,
                "browser_launches": self._launches,
                "queued": sum(1 for j in jobs if j.status == "queued"),
                "running": sum(1 for j in jobs if j.status == "running"),
                "completed": self._completed,
                "failed": self._failed,
                "retained_jobs": len(jobs),
                "queue_capacity": self._cfg.QUEUE_MAX_SIZE,
            }

    def _evict(self) -> None:
        """Drop finished jobs past their TTL, then enforce the hard cap."""
        now = time.time()
        ttl = self._cfg.JOB_TTL_S

        stale = [
            job_id
            for job_id, job in self._jobs.items()
            if job.finished and job.finished_at is not None and now - job.finished_at > ttl
        ]
        for job_id in stale:
            del self._jobs[job_id]

        overflow = len(self._jobs) - self._cfg.JOB_MAX_RETAINED
        if overflow > 0:
            # Oldest finished jobs go first; never evict work still in flight.
            finished = sorted(
                (j for j in self._jobs.values() if j.finished),
                key=lambda j: j.finished_at or j.created_at,
            )
            for job in finished[:overflow]:
                self._jobs.pop(job.id, None)

    # ----------------------------------------------------------------- #
    # Worker
    # ----------------------------------------------------------------- #

    def _worker_loop(self, index: int) -> None:
        """
        Own one browser and drain the queue.

        The browser lives in this thread and is never shared, which is what
        Playwright's sync API requires.
        """
        alap = None
        current_proxy: Any = _UNSET
        solves = 0

        try:
            while not self._stopping.is_set():
                try:
                    job = self._queue.get(timeout=0.25)
                except queue.Empty:
                    continue

                if job is None:  # shutdown sentinel
                    break

                try:
                    alap, current_proxy, solves = self._prepare(
                        index, alap, current_proxy, solves, job
                    )
                    self._run_job(index, alap, job)
                    # Counted here, not in _prepare: this is what makes
                    # POOL_MAX_SOLVES_PER_BROWSER actually recycle.
                    solves += 1
                except Exception as exc:  # noqa: BLE001 - recorded on the job
                    logger.error(f"[worker {index}] job {job.id} crashed: {exc}")
                    self._finish(job, error=str(exc))
                    # A crashed browser cannot be trusted for the next job.
                    alap = self._discard(alap)
                    current_proxy = _UNSET
                    solves = 0
                finally:
                    self._queue.task_done()
        finally:
            self._discard(alap)

    def _prepare(self, index, alap, current_proxy, solves, job) -> tuple[Any, Any, int]:
        """Return a browser suitable for ``job``, relaunching when needed."""
        recycle_after = self._cfg.POOL_MAX_SOLVES_PER_BROWSER
        needs_new = (
            alap is None
            or current_proxy != job.request.proxy
            or not self._cfg.POOL_ENABLED
            or (recycle_after > 0 and solves >= recycle_after)
        )

        if not needs_new:
            return alap, current_proxy, solves

        if alap is not None:
            reason = (
                "proxy changed"
                if current_proxy != job.request.proxy
                else f"recycling after {solves} solves"
            )
            logger.debug(f"[worker {index}] replacing browser ({reason})")
            self._discard(alap)

        alap = self._alap_factory(
            proxy=job.request.proxy,
            headless=self._headless,
            timeout=self._cfg.SOLVE_TIMEOUT_S,
            allow_private_hosts=self._cfg.ALLOW_PRIVATE_HOSTS,
        )
        alap.start()
        with self._lock:
            self._launches += 1
        logger.debug(f"[worker {index}] browser ready")
        return alap, job.request.proxy, 0

    @staticmethod
    def _discard(alap) -> None:
        """Close a browser, ignoring teardown noise."""
        if alap is not None:
            try:
                alap.close()
            except Exception as exc:  # pragma: no cover - teardown best effort
                logger.debug(f"Error closing pooled browser: {exc}")
        return None

    def _run_job(self, index: int, alap, job: SolveJob) -> None:
        """Execute one job on the given browser."""
        job.status = "running"
        job.started_at = time.time()
        job.worker = index

        request = job.request
        timeout = request.timeout or self._cfg.SOLVE_TIMEOUT_S

        if request.sitekey:
            result = alap.solve_with_sitekey(
                request.url,
                request.sitekey,
                invisible=request.invisible,
                retries=request.retries,
                timeout=timeout,
            )
        else:
            result = alap.solve(
                request.url,
                invisible=request.invisible,
                retries=request.retries,
                timeout=timeout,
            )

        self._finish(job, result=result)

    def _finish(
        self,
        job: SolveJob,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """Mark a job complete and release anyone waiting on it."""
        job.finished_at = time.time()
        if error is not None:
            job.status = "error"
            job.error = error
            with self._lock:
                self._failed += 1
        else:
            job.status = "done"
            job.result = result
            with self._lock:
                if result and result.get("success"):
                    self._completed += 1
                else:
                    self._failed += 1
        job._done.set()
