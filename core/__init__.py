"""
core  -  Quintessential Video Editor internal utilities

Submodules
----------
  hardware  - binary resolution, GPU detection, ffprobe/ffplay helpers
  settings  - centralised settings.json I/O (single source of truth)
  deps      - vendored dependency manager (auto-install into libs/)
  skins     - theming engine (skin palette, live switching, star particles)
"""

# ── Single-source application version ────────────────────────────────────────
APP_VERSION = "1.14.0"
