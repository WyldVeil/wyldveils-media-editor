"""
core/hardware.py  ─  Platform-safe hardware and binary utilities

Provides:
  - get_binary_path()       - locate ffmpeg/ffplay/ffprobe for current OS
  - detect_gpu()            - NVIDIA / AMD / Apple / CPU (Cached for performance)
  - get_video_duration()    - ffprobe-based precise duration
  - get_audio_bitrate_kbps()- ffprobe-based exact audio stream bitrate
  - launch_preview()        - ffplay preview window
  - get_local_version()     - installed FFmpeg version string
  - get_latest_online_version() - latest release from gyan.dev
  - download_and_extract_ffmpeg() - auto-update bundled FFmpeg
  - open_in_explorer()      - cross-platform file/folder opener

Platform notes
──────────────
• Windows  - ffmpeg.exe / ffplay.exe / ffprobe.exe
• macOS    - ffmpeg / ffplay / ffprobe  (no .exe)
• Linux    - ffmpeg / ffplay / ffprobe  (no .exe)

CREATE_NO_WINDOW is a Windows-only subprocess flag (0x08000000). On other
platforms it is defined as 0 so it can be passed safely without guards.
"""

import os
import platform
import subprocess
import urllib.request
import zipfile
from typing import Optional

# ── Platform constants ────────────────────────────────────────────────────────
_IS_WIN = platform.system() == "Windows"
_IS_MAC = platform.system() == "Darwin"

# Suppress the console window on Windows; harmless (0) elsewhere.
CREATE_NO_WINDOW: int = 0x08000000 if _IS_WIN else 0

# Binary extension depends on platform
_EXE = ".exe" if _IS_WIN else ""

# Global cache to prevent redundant, slow hardware polling
_CACHED_GPU: Optional[str] = None


# ── Binary path resolution ────────────────────────────────────────────────────

def get_binary_path(name: str) -> str:
    """
    Return the absolute path to a bundled binary.

    *name* should be the bare binary name, e.g. ``"ffmpeg"``.  The correct
    platform extension (.exe on Windows, nothing elsewhere) is appended
    automatically.  Passing ``"ffmpeg.exe"`` is also accepted for backwards
    compatibility - the extension is stripped and re-applied.
    """
    base     = os.path.splitext(name)[0]
    filename = base + _EXE
    root     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "bin", filename)


def _check_settings_override(name: str) -> Optional[str]:
    """Return a user-overridden binary path from settings, or None."""
    try:
        from core.settings import load_settings
        override = load_settings().get("ffmpeg_path_override", "").strip()
        if override and os.path.isfile(override):
            parent    = os.path.dirname(override)
            base      = os.path.splitext(name)[0]
            candidate = os.path.join(parent, base + _EXE)
            if os.path.isfile(candidate):
                return candidate
    except Exception:
        pass
    return None


def _resolve(name: str) -> str:
    """
    Resolve the best available path for binary *name* (e.g. ``"ffmpeg"``).
    Priority: settings override → bundled bin/ → system PATH fallback.
    """
    override = _check_settings_override(name)
    if override:
        return override
    bundled = get_binary_path(name)
    if os.path.isfile(bundled):
        return bundled
    return os.path.splitext(name)[0] + _EXE


# ── GPU detection ─────────────────────────────────────────────────────────────

def detect_gpu() -> str:
    """
    Detect the best available hardware encoder.
    Returns one of: ``"nvidia"`` | ``"amd"`` | ``"apple"`` | ``"cpu"``
    Results are cached to prevent blocking the main thread on subsequent calls.
    """
    global _CACHED_GPU
    if _CACHED_GPU is not None:
        return _CACHED_GPU

    # NVIDIA - nvidia-smi present on any system with NVIDIA drivers installed
    try:
        subprocess.run(
            ["nvidia-smi"],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=3,
        )
        _CACHED_GPU = "nvidia"
        return _CACHED_GPU
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        pass

    # AMD on Linux - rocm-smi
    if not _IS_WIN and not _IS_MAC:
        try:
            subprocess.run(
                ["rocm-smi"], capture_output=True, timeout=3
            )
            _CACHED_GPU = "amd"
            return _CACHED_GPU
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            pass

    # Apple Silicon / VideoToolbox
    if _IS_MAC:
        _CACHED_GPU = "apple"
        return _CACHED_GPU

    # AMD on Windows - lightweight wmic query
    if _IS_WIN:
        try:
            r = subprocess.run(
                ["wmic", "path", "win32_VideoController",
                 "get", "Name", "/value"],
                capture_output=True, text=True,
                creationflags=CREATE_NO_WINDOW,
                timeout=5,
            )
            names_lower = r.stdout.lower()
            if "amd" in names_lower or "radeon" in names_lower:
                _CACHED_GPU = "amd"
                return _CACHED_GPU
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            pass

    _CACHED_GPU = "cpu"
    return _CACHED_GPU


# ── Metadata helpers ──────────────────────────────────────────────────────────

def get_video_duration(file_path: str) -> float:
    """
    Return the exact duration of *file_path* in seconds via ffprobe.
    Returns 0.0 on any error.
    """
    if not file_path:
        return 0.0

    ffprobe = _resolve("ffprobe")
    if not os.path.isfile(ffprobe):
        return 0.0

    try:
        result = subprocess.run(
            [
                ffprobe, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                file_path,
            ],
            capture_output=True, text=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=15,
        )
        return float(result.stdout.strip())
    except (ValueError, subprocess.TimeoutExpired, OSError):
        return 0.0


def get_audio_bitrate_kbps(file_path: str) -> float:
    """
    Return the bitrate of the first audio stream in kbps via ffprobe.
    Returns 0.0 on any error or if the bitrate is not explicitly declared.
    """
    if not file_path:
        return 0.0

    ffprobe = _resolve("ffprobe")
    if not os.path.isfile(ffprobe):
        return 0.0

    try:
        result = subprocess.run(
            [
                ffprobe, "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=bit_rate",
                "-of", "default=noprint_wrappers=1:nokey=1",
                file_path,
            ],
            capture_output=True, text=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=15,
        )
        output = result.stdout.strip()
        if output and output.lower() != "n/a":
            return float(output) / 1000.0
        return 0.0
    except (ValueError, subprocess.TimeoutExpired, OSError):
        return 0.0


def launch_preview(
    file_path: str, start_time: float = 0
) -> Optional[subprocess.Popen]:
    """
    Launch ffplay for an inline preview window.
    Returns the Popen handle or None on failure.
    """
    if not file_path or not os.path.exists(file_path):
        return None

    ffplay = _resolve("ffplay")
    if not os.path.isfile(ffplay):
        return None

    cmd = [
        ffplay,
        "-ss",           str(start_time),
        "-i",            file_path,
        "-window_title", "Studio Preview  |  Press P to pause",
        "-x",            "800", "-y", "450",
        "-autoexit",
        "-loglevel",     "quiet",
    ]
    try:
        return subprocess.Popen(cmd, creationflags=CREATE_NO_WINDOW)
    except OSError:
        return None


# ── Version management ────────────────────────────────────────────────────────

def get_local_version() -> str:
    """
    Return the version of the bundled FFmpeg, e.g. ``"7.1"``.
    Returns ``"Missing"`` or ``"Unknown"`` on failure.
    """
    ffmpeg = _resolve("ffmpeg")
    if not os.path.isfile(ffmpeg):
        return "Missing"

    try:
        res = subprocess.run(
            [ffmpeg, "-version"],
            capture_output=True, text=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=10,
        )
        first_line   = res.stdout.splitlines()[0]
        version_part = first_line.split("version ")[1].split()[0]
        return version_part.split("-")[0]
    except (IndexError, OSError, subprocess.TimeoutExpired):
        return "Unknown"


def get_latest_online_version() -> str:
    """
    Fetch the latest FFmpeg release version from gyan.dev (3 s timeout).
    Falls back to the local version if the network is unavailable.
    """
    url = "https://www.gyan.dev/ffmpeg/builds/release-version"
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            latest = response.read().decode("utf-8").strip()
            return latest.split("-")[0]
    except Exception as exc:
        print(f"[Hardware] Could not fetch latest FFmpeg version: {exc}")
        return get_local_version()


def download_and_extract_ffmpeg(log_func) -> bool:
    """
    Download the latest FFmpeg essentials zip and extract the three
    binaries into ``bin/``.  Calls ``log_func(message)`` for progress.

    Auto-download is Windows-only; other platforms receive guidance to
    use their system package manager.  Returns True on success.
    """
    if not _IS_WIN:
        log_func(
            "Auto-download is only supported on Windows.\n"
            "  macOS : brew install ffmpeg\n"
            "  Linux : sudo apt install ffmpeg   (or equivalent)"
        )
        return False

    bin_dir  = os.path.dirname(get_binary_path("ffmpeg"))
    os.makedirs(bin_dir, exist_ok=True)
    url      = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    zip_path = os.path.join(bin_dir, "_ffmpeg_download.zip")

    try:
        log_func("Connecting to gyan.dev …")
        urllib.request.urlretrieve(url, zip_path)
        log_func("Download complete. Extracting …")

        targets = {"ffmpeg.exe", "ffplay.exe", "ffprobe.exe"}
        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.namelist():
                if os.path.basename(member) in targets:
                    dest = os.path.join(bin_dir, os.path.basename(member))
                    with zf.open(member) as src, open(dest, "wb") as dst:
                        dst.write(src.read())

        os.remove(zip_path)
        log_func("✅  FFmpeg suite updated successfully!")
        return True

    except Exception as exc:
        log_func(f"❌  Error: {exc}")
        try:
            os.remove(zip_path)
        except OSError:
            pass
        return False


# ── Cross-platform folder / file opener ──────────────────────────────────────

def open_in_explorer(path: str) -> bool:
    """
    Open *path* (file or folder) in the system file manager.
    Supports Windows, macOS, and Linux (xdg-open).
    Returns True on success, False on failure.
    """
    if not os.path.exists(path):
        return False
    try:
        if _IS_WIN:
            os.startfile(path)                             # type: ignore[attr-defined]
        elif _IS_MAC:
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception:
        return False