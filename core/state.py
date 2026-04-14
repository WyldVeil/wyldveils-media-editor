"""
core/state.py  ─  Centralized State Manager (Observable pattern)

Provides a thread-safe singleton that any tab can import to share video
metadata and global settings without being tightly coupled to main.py.

Usage
-----
    from core.state import state

    # Write a value and notify listeners
    state.set("last_file", "/path/to/video.mp4")

    # Read a value
    path = state.get("last_file", default="")

    # Subscribe to changes (fires on the calling thread - use after() if in UI code)
    state.subscribe("last_file", lambda v: print("new file:", v))

    # Unsubscribe
    state.unsubscribe("last_file", my_callback)

Built-in keys (set by main.py / tabs as they load files):
    "last_file"          str   - most recently loaded video path
    "last_output_dir"    str   - most recently used output directory
    "video_width"        int   - width of last probed video
    "video_height"       int   - height of last probed video
    "video_duration"     float - duration in seconds of last probed video
    "active_tab"         str   - name of the currently visible tab
    "processing"         bool  - True while any tab is running FFmpeg
"""

import threading


class StateManager:
    """
    Thread-safe observable key/value store.
    Callbacks fire synchronously on whichever thread calls set().
    In UI subscribers, wrap the callback body in widget.after(0, ...) to
    ensure it runs on the main Tk thread.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._data: dict = {}
        self._listeners: dict[str, list] = {}

    # ── Read / Write ──────────────────────────────────────────────────────────

    def get(self, key: str, default=None):
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value) -> None:
        with self._lock:
            old = self._data.get(key)
            self._data[key] = value
            # Snapshot listeners so the lock is not held during callbacks
            cbs = list(self._listeners.get(key, []))

        if old != value:
            for cb in cbs:
                try:
                    cb(value)
                except Exception:
                    pass

    def get_all(self) -> dict:
        with self._lock:
            return dict(self._data)

    # ── Observation ───────────────────────────────────────────────────────────

    def subscribe(self, key: str, callback) -> None:
        """Register *callback(new_value)* to fire whenever *key* changes."""
        with self._lock:
            self._listeners.setdefault(key, []).append(callback)

    def unsubscribe(self, key: str, callback) -> None:
        with self._lock:
            lst = self._listeners.get(key, [])
            try:
                lst.remove(callback)
            except ValueError:
                pass


# Module-level singleton - import and use directly:  from core.state import state
state = StateManager()
