"""
tests/test_webm_maker_logic.py — unit tests for pure helpers in webm_maker.py
(no GUI required — Tkinter is never imported).
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_snap_even_already_even():
    from tabs.social.webm_maker import _snap_even
    assert _snap_even(1080) == 1080
    assert _snap_even(2) == 2
    assert _snap_even(1920) == 1920


def test_snap_even_rounds_odd_up():
    from tabs.social.webm_maker import _snap_even
    assert _snap_even(1) == 2
    assert _snap_even(1079) == 1080
    assert _snap_even(7681) == 7682


def test_resolve_pixfmt_explicit_choice_passes_through():
    from tabs.social.webm_maker import _resolve_pixfmt
    pf, warn = _resolve_pixfmt("yuv420p", "yuv420p10le", "VP9")
    assert pf == "yuv420p"
    assert warn is None


def test_resolve_pixfmt_source_in_supported_set_vp9():
    from tabs.social.webm_maker import _resolve_pixfmt
    pf, warn = _resolve_pixfmt("source", "yuv420p10le", "VP9")
    assert pf == "yuv420p10le"
    assert warn is None


def test_resolve_pixfmt_source_unsupported_falls_back_with_warning():
    from tabs.social.webm_maker import _resolve_pixfmt
    pf, warn = _resolve_pixfmt("source", "rgb24", "VP9")
    assert pf == "yuv420p"
    assert warn is not None
    assert "rgb24" in warn
    assert "yuv420p" in warn


def test_resolve_pixfmt_source_unsupported_in_vp8_falls_back():
    from tabs.social.webm_maker import _resolve_pixfmt
    # yuv444p is supported in VP9 but not VP8
    pf, warn = _resolve_pixfmt("source", "yuv444p", "VP8")
    assert pf == "yuv420p"
    assert warn is not None
    assert "yuv444p" in warn


def test_resolve_pixfmt_source_unknown_falls_back_silently():
    """If source pix_fmt is empty (probe never succeeded), use yuv420p with no warning."""
    from tabs.social.webm_maker import _resolve_pixfmt
    pf, warn = _resolve_pixfmt("source", "", "VP9")
    assert pf == "yuv420p"
    assert warn is None
