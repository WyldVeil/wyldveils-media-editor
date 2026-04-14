"""
core/queue_manager.py  -  Global Background Render Queue
=========================================================
Thread-safe singleton that serialises all FFmpeg (and other long-running)
render jobs submitted from any tab.

Design:
  • Tasks are executed ONE AT A TIME in the order they were submitted.
  • Each task is either a simple cmd/cmds list  OR  a worker_fn callable.
  • All UI callbacks (on_start, on_progress, on_complete) are dispatched to
    the Tkinter main thread via root.after(0, …) so they are always safe
    to touch widgets.
  • The background worker thread is a daemon; it wakes via a threading.Event
    whenever new work arrives.
"""

import threading
import subprocess
import time
import uuid
from typing import Optional, Callable, List

try:
    from core.hardware import CREATE_NO_WINDOW
except ImportError:
    import platform
    CREATE_NO_WINDOW = 0x08000000 if platform.system() == "Windows" else 0


# ─────────────────────────────────────────────────────────────────────────────
#  RenderTask  -  data model for a single queue entry
# ─────────────────────────────────────────────────────────────────────────────

class RenderTask:
    """
    Represents one unit of work in the render queue.

    Either ``cmds`` or ``worker_fn`` must be provided (not both).

    ``cmds``       List[List[str]] - one or more FFmpeg (or arbitrary) commands
                   to run sequentially. The task fails at the first non-zero
                   return code.

    ``worker_fn``  Callable[[progress_cb, cancel_fn], int]
                   A function run entirely inside the worker thread.
                   It receives:
                     progress_cb(line: str) - report a log line
                     cancel_fn() -> bool   - True when cancellation requested
                   It must return an int return-code (0 = success).
                   Use this for complex multi-step workflows that need to
                   run several subprocesses or do Python-level work between
                   subprocess calls.
    """

    def __init__(self, *, id, name, output_path="",
                 cmds=None, worker_fn=None,
                 on_start=None, on_progress=None, on_complete=None):
        self.id          = id                   # short UUID str
        self.name        = name                 # display name
        self.output_path = output_path          # used for open-folder actions
        self.cmds        = cmds                 # List[List[str]] | None
        self.worker_fn   = worker_fn            # callable | None
        self.status      = "pending"            # pending|active|done|failed|cancelled
        self.progress    = ""                   # latest progress line
        self.created_at  = time.time()
        self.started_at: Optional[float] = None
        self.finished_at: Optional[float] = None
        self.returncode  = 0
        # UI callbacks (always called on main thread)
        self.on_start    = on_start             # (task_id)
        self.on_progress = on_progress          # (task_id, line)
        self.on_complete = on_complete          # (task_id, returncode)
        # Internal
        self._cancel     = threading.Event()    # set by cancel()
        self._proc       = None                 # active subprocess.Popen


# ─────────────────────────────────────────────────────────────────────────────
#  RenderQueueManager  -  singleton, owns the worker thread
# ─────────────────────────────────────────────────────────────────────────────

class RenderQueueManager:
    """
    Singleton background render queue.

    Usage
    -----
    # In main.py / App.__init__:
        qmgr = RenderQueueManager.get_instance()
        qmgr.set_tk_root(self)
        qmgr.register_update_callback(self._refresh_queue_widget)

    # In a tab:
        from core.queue_manager import RenderQueueManager
        RenderQueueManager.get_instance().enqueue(
            name="My Render",
            cmd=[ffmpeg, "-i", src, ..., out, "-y"],
            output_path=out,
            on_progress=lambda tid, line: ...,
            on_complete=lambda tid, rc: ...,
        )
    """

    _instance: Optional["RenderQueueManager"] = None
    _instance_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "RenderQueueManager":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._tasks: List[RenderTask] = []
        self._lock = threading.Lock()                # guards _tasks list
        self._work_event = threading.Event()         # signals worker
        self._update_callbacks: List[Callable] = []  # registered UI refreshers
        self._tk_root = None

        worker = threading.Thread(
            target=self._run_worker,
            name="RenderQueueWorker",
            daemon=True,
        )
        worker.start()

    # ── Public API ────────────────────────────────────────────────────────────

    def set_tk_root(self, root) -> None:
        """Give the manager a reference to the Tk root for after() callbacks."""
        self._tk_root = root

    def register_update_callback(self, cb: Callable) -> None:
        """
        Register a zero-argument callable that will be called (on the main
        thread) whenever the queue state changes. Use this to refresh widgets.
        """
        self._update_callbacks.append(cb)

    def enqueue(
        self,
        name: str,
        output_path: str = "",
        *,
        cmd: Optional[List] = None,
        cmds: Optional[List[List]] = None,
        worker_fn: Optional[Callable] = None,
        on_start: Optional[Callable] = None,
        on_progress: Optional[Callable] = None,
        on_complete: Optional[Callable] = None,
    ) -> str:
        """
        Submit a task to the queue and return its task_id.

        Exactly one of ``cmd``, ``cmds``, or ``worker_fn`` must be supplied.

        cmd / cmds  - FFmpeg (or any) command(s) run via subprocess.Popen.
        worker_fn   - callable(progress_cb, cancel_fn) -> int  for complex
                      multi-step workflows.
        """
        if cmd is not None:
            cmds_arg = [list(cmd)]
        elif cmds is not None:
            cmds_arg = [list(c) for c in cmds]
        else:
            cmds_arg = None

        task = RenderTask(
            id=str(uuid.uuid4())[:8],
            name=name,
            output_path=output_path,
            cmds=cmds_arg,
            worker_fn=worker_fn,
            on_start=on_start,
            on_progress=on_progress,
            on_complete=on_complete,
        )
        with self._lock:
            self._tasks.append(task)

        self._work_event.set()
        self._fire_update()
        return task.id

    def cancel(self, task_id: str) -> None:
        """Cancel a pending or active task by id."""
        with self._lock:
            for t in self._tasks:
                if t.id == task_id:
                    t._cancel.set()
                    if t.status == "pending":
                        t.status = "cancelled"
                        self._fire_update()
                    # If active, the worker detects _cancel and terminates proc
                    break

    def clear_finished(self) -> None:
        """Remove all done/failed/cancelled tasks from the list."""
        with self._lock:
            self._tasks = [
                t for t in self._tasks
                if t.status not in ("done", "failed", "cancelled")
            ]
        self._fire_update()

    def get_all_tasks(self) -> List[RenderTask]:
        """Return a snapshot of all tasks (any status)."""
        with self._lock:
            return list(self._tasks)

    def get_stats(self):
        """Return (active_count, pending_count, done_count, failed_count)."""
        with self._lock:
            active  = sum(1 for t in self._tasks if t.status == "active")
            pending = sum(1 for t in self._tasks if t.status == "pending")
            done    = sum(1 for t in self._tasks if t.status == "done")
            failed  = sum(1 for t in self._tasks
                         if t.status in ("failed", "cancelled"))
        return active, pending, done, failed

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _fire_update(self) -> None:
        """Schedule all registered update callbacks on the main thread."""
        if self._tk_root:
            try:
                cbs = list(self._update_callbacks)
                self._tk_root.after(0, lambda: [_safe_call(cb) for cb in cbs])
            except Exception:
                pass

    # ── Worker thread ─────────────────────────────────────────────────────────

    def _run_worker(self) -> None:
        """Runs in a background daemon thread. Picks up pending tasks."""
        while True:
            self._work_event.wait()
            self._work_event.clear()

            while True:
                task = self._next_pending()
                if task is None:
                    break
                self._execute_task(task)

    def _next_pending(self) -> Optional[RenderTask]:
        with self._lock:
            for t in self._tasks:
                if t.status == "pending":
                    t.status = "active"
                    return t
        return None

    def _execute_task(self, task: RenderTask) -> None:
        task.started_at = time.time()
        self._fire_update()

        # on_start callback
        if task.on_start:
            self._dispatch(task.on_start, task.id)

        def progress_cb(line: str) -> None:
            task.progress = line
            if task.on_progress:
                self._dispatch(task.on_progress, task.id, line)

        def cancel_fn() -> bool:
            return task._cancel.is_set()

        final_rc = 0
        try:
            if task.worker_fn is not None:
                result = task.worker_fn(progress_cb, cancel_fn)
                final_rc = result if isinstance(result, int) else 0
            elif task.cmds:
                for cmd in task.cmds:
                    if task._cancel.is_set():
                        final_rc = -1
                        break
                    final_rc = self._run_cmd(cmd, task, progress_cb)
                    if final_rc != 0 and not task._cancel.is_set():
                        break
        except Exception as exc:
            progress_cb(f"⚠ Queue error: {exc}")
            final_rc = 1

        task.finished_at = time.time()
        task.returncode  = final_rc

        if task._cancel.is_set():
            task.status = "cancelled"
        elif final_rc == 0:
            task.status = "done"
        else:
            task.status = "failed"

        self._fire_update()

        if task.on_complete:
            self._dispatch(task.on_complete, task.id, task.returncode)

    def _run_cmd(self, cmd: List, task: RenderTask,
                 progress_cb: Callable) -> int:
        """Run one command via Popen, streaming stdout to progress_cb."""
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=CREATE_NO_WINDOW,
            )
            task._proc = proc
            for line in iter(proc.stdout.readline, ""):
                if task._cancel.is_set():
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                    break
                stripped = line.rstrip()
                if stripped:
                    progress_cb(stripped)
            proc.stdout.close()
            try:
                proc.wait(timeout=7200)  # 2-hour safety net
            except subprocess.TimeoutExpired:
                proc.kill()
                progress_cb("⚠ Process killed: exceeded 2-hour timeout")
                return 1
            task._proc = None
            return proc.returncode if proc.returncode is not None else 0
        except Exception as exc:
            progress_cb(f"⚠ Launch error: {exc}")
            return 1

    def _dispatch(self, fn: Callable, *args) -> None:
        """Schedule fn(*args) on the Tkinter main thread."""
        if self._tk_root and fn:
            try:
                self._tk_root.after(0, lambda f=fn, a=args: _safe_call(f, *a))
            except Exception:
                pass


def _safe_call(fn, *args):
    try:
        fn(*args)
    except Exception:
        pass
