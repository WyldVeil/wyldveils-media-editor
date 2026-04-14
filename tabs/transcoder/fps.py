"""
tab_fpsinterpolator.py  ─  Framerate Interpolator

Re-exports FPSInterpolatorTab from tab_resolutionscaler.  Both tools live
in the same file because they share the same FFmpeg scale/fps filter
infrastructure and were originally designed together.

This shim keeps the import in main.py clean and explicit:
    from tabs.tab_fpsinterpolator import FPSInterpolatorTab
"""
from tabs.tab_resolutionscaler import FPSInterpolatorTab  # noqa: F401
from core.i18n import t

__all__ = ["FPSInterpolatorTab"]
