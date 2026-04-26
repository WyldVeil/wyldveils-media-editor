"""
core/network.py  -  Centralised network configuration

Single source of truth for proxy, bandwidth, timeout, identity, and SSL
settings. Every HTTP fetch and every network-touching subprocess in the
app should go through these helpers so a user can govern the whole app
from Advanced Settings -> Networking.

Public surface:
    DEFAULTS              dict of every setting key and its default value
    PRESETS               dict of preset_id -> partial settings dict
    get()                 effective settings (defaults + saved overrides)
    reset_key(k)          reset one setting to its default
    reset_all()           reset every network.* setting
    proxy_url(cfg=None)   "scheme://[user:pass@]host:port" or None
    urlopen(url, ...)     drop-in replacement for urllib.request.urlopen
    build_yt_dlp_args()   list of CLI flags for yt-dlp invocations
    subprocess_env(...)   env dict for subprocess.Popen child processes
    test()                (ok: bool, message: str)
"""
import os
import ssl
import urllib.request
from urllib.parse import quote

from core import settings as _settings


# ── Defaults ──────────────────────────────────────────────────────────────────
# Empty strings / 0 mean "use the library default". Reading these via get()
# returns the saved value if the user has overridden it, otherwise the
# default below. Keys are namespaced under "network." so they coexist with
# other settings.json entries without collision.
DEFAULTS = {
    "network.proxy_enabled":   False,
    "network.proxy_scheme":    "http",          # http, https, socks4, socks5, socks5h
    "network.proxy_host":      "127.0.0.1",
    "network.proxy_port":      "",              # "" = unset
    "network.proxy_user":      "",
    "network.proxy_pass":      "",
    "network.no_proxy":        "localhost,127.0.0.1",
    "network.bandwidth_limit": "",              # e.g. "1M", "500K"
    "network.connect_timeout": "15",            # seconds
    "network.socket_timeout":  "60",            # seconds
    "network.user_agent":      "",
    "network.ip_version":      "auto",          # auto, ipv4, ipv6
    "network.source_address":  "",              # bind interface, e.g. "192.168.1.5"
    "network.verify_ssl":      True,
    "network.allow_http":      True,
}


# ── Presets ───────────────────────────────────────────────────────────────────
# One-click defaults for common setups. UI buttons call apply_preset(id).
PRESETS = {
    "direct": {
        "network.proxy_enabled": False,
    },
    "system": {
        # Disable the in-app proxy so urllib falls back to system proxy
        # env vars (HTTP_PROXY, HTTPS_PROXY) the OS has set.
        "network.proxy_enabled": False,
    },
    "tor": {
        "network.proxy_enabled": True,
        "network.proxy_scheme":  "socks5h",
        "network.proxy_host":    "127.0.0.1",
        "network.proxy_port":    "9050",
    },
    "local_http": {
        "network.proxy_enabled": True,
        "network.proxy_scheme":  "http",
        "network.proxy_host":    "127.0.0.1",
        "network.proxy_port":    "8080",
    },
}


# ── Settings load / save ──────────────────────────────────────────────────────
def get():
    """
    Return a flat dict containing every network.* key with its effective
    value. Saved values override DEFAULTS; missing or blank-string saves
    fall back to the default for that key.
    """
    s = _settings.load_settings()
    out = dict(DEFAULTS)
    for k, default in DEFAULTS.items():
        if k in s:
            v = s[k]
            # Treat empty strings as "use default" for string defaults so
            # the form's blank entry == default behaviour.
            if isinstance(default, str) and v == "":
                out[k] = default
            else:
                out[k] = v
    return out


def reset_key(key):
    """Reset one setting to its default and persist."""
    if key not in DEFAULTS:
        return
    s = _settings.load_settings()
    s[key] = DEFAULTS[key]
    _settings.save_settings(s)


def reset_all():
    """Reset every network.* key to its default and persist."""
    s = _settings.load_settings()
    for k, v in DEFAULTS.items():
        s[k] = v
    _settings.save_settings(s)


def apply_preset(preset_id):
    """
    Merge a preset into saved settings. Unknown preset_id is a no-op.
    Returns the merged values dict for the caller to refresh its form.
    """
    p = PRESETS.get(preset_id)
    if not p:
        return {}
    s = _settings.load_settings()
    s.update(p)
    _settings.save_settings(s)
    return p


# ── Proxy URL builder ─────────────────────────────────────────────────────────
def proxy_url(cfg=None):
    """
    Return "scheme://[user:pass@]host:port" or None.
    Returns None when proxy is disabled OR host/port are missing.
    """
    cfg = cfg if cfg is not None else get()
    if not cfg.get("network.proxy_enabled"):
        return None
    scheme = (cfg.get("network.proxy_scheme") or "http").lower().strip()
    host   = (cfg.get("network.proxy_host")   or "").strip()
    port   = str(cfg.get("network.proxy_port") or "").strip()
    if not host or not port:
        return None
    user = (cfg.get("network.proxy_user") or "").strip()
    pwd  = (cfg.get("network.proxy_pass") or "").strip()
    auth = ""
    if user:
        auth = quote(user, safe="")
        if pwd:
            auth += ":" + quote(pwd, safe="")
        auth += "@"
    return f"{scheme}://{auth}{host}:{port}"


# ── urllib opener ─────────────────────────────────────────────────────────────
def _make_opener(cfg):
    handlers = []
    pu = proxy_url(cfg)
    scheme = (cfg.get("network.proxy_scheme") or "http").lower()
    if pu and not scheme.startswith("socks"):
        handlers.append(urllib.request.ProxyHandler({
            "http":  pu,
            "https": pu,
        }))
    # SOCKS proxies aren't natively supported by urllib. We don't monkey-
    # patch the global socket because that would have surprising side
    # effects elsewhere in the app. SOCKS still works for yt-dlp and
    # ffmpeg via their own --proxy / env-var paths; the helper just
    # falls back to a direct connection for in-app urllib calls.

    if cfg.get("network.verify_ssl", True) is False:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        handlers.append(urllib.request.HTTPSHandler(context=ctx))

    return urllib.request.build_opener(*handlers)


def urlopen(url, timeout=None, headers=None, cfg=None, data=None):
    """
    Drop-in replacement for urllib.request.urlopen that honours the user's
    proxy / timeout / SSL / User-Agent settings. Use this everywhere instead
    of importing urllib.request directly.

    `headers` is a dict merged on top of the global User-Agent.
    `data` is forwarded to Request() for POST-style fetches.
    """
    cfg = cfg if cfg is not None else get()

    if timeout is None:
        try:
            timeout = float(cfg.get("network.socket_timeout") or 60)
        except (TypeError, ValueError):
            timeout = 60

    if cfg.get("network.allow_http", True) is False and \
            isinstance(url, str) and url.lower().startswith("http://"):
        raise ValueError(
            "Plain HTTP downloads are blocked by your network settings. "
            "Re-enable 'Allow plain HTTP' in Advanced Settings to fetch "
            "this URL.")

    req_headers = {}
    ua = (cfg.get("network.user_agent") or "").strip()
    if ua:
        req_headers["User-Agent"] = ua
    if headers:
        req_headers.update(headers)

    if isinstance(url, urllib.request.Request):
        req = url
        for k, v in req_headers.items():
            req.add_header(k, v)
    else:
        req = urllib.request.Request(url, headers=req_headers, data=data)

    opener = _make_opener(cfg)
    return opener.open(req, timeout=timeout)


# ── yt-dlp CLI args ───────────────────────────────────────────────────────────
def build_yt_dlp_args(cfg=None):
    """
    Return a list of CLI flags reflecting current network settings.
    Caller prepends or appends these to the yt-dlp argv before exec.
    """
    cfg = cfg if cfg is not None else get()
    args = []

    pu = proxy_url(cfg)
    if pu:
        args += ["--proxy", pu]

    rate = (cfg.get("network.bandwidth_limit") or "").strip()
    if rate:
        args += ["--limit-rate", rate]

    so = (cfg.get("network.socket_timeout") or "").strip()
    if so:
        args += ["--socket-timeout", str(so)]

    ipv = (cfg.get("network.ip_version") or "auto").lower()
    if ipv == "ipv4":
        args += ["--force-ipv4"]
    elif ipv == "ipv6":
        args += ["--force-ipv6"]

    src = (cfg.get("network.source_address") or "").strip()
    if src:
        args += ["--source-address", src]

    ua = (cfg.get("network.user_agent") or "").strip()
    if ua:
        args += ["--user-agent", ua]

    if cfg.get("network.verify_ssl", True) is False:
        args += ["--no-check-certificates"]

    return args


# ── Subprocess env ────────────────────────────────────────────────────────────
def subprocess_env(extra=None, cfg=None):
    """
    Build an env dict for subprocess.Popen / subprocess.run that exports
    the proxy / no-proxy values to child processes (ffmpeg, pip, etc.).
    Includes both upper- and lower-case variants since different tools
    look for different cases.
    """
    cfg = cfg if cfg is not None else get()
    env = dict(os.environ)
    if extra:
        env.update(extra)

    pu = proxy_url(cfg)
    if pu:
        env["HTTP_PROXY"]  = pu
        env["HTTPS_PROXY"] = pu
        env["http_proxy"]  = pu
        env["https_proxy"] = pu
        if (cfg.get("network.proxy_scheme") or "").lower().startswith("socks"):
            env["ALL_PROXY"] = pu
            env["all_proxy"] = pu

    no_proxy = (cfg.get("network.no_proxy") or "").strip()
    if no_proxy:
        env["NO_PROXY"] = no_proxy
        env["no_proxy"] = no_proxy

    return env


# ── Connectivity test ─────────────────────────────────────────────────────────
def test(cfg=None):
    """
    Try a small HTTPS GET against a known endpoint using *cfg* (or the
    saved settings if None). Returns (ok: bool, message: str).
    """
    try:
        with urlopen("https://api.github.com/zen",
                     timeout=8, cfg=cfg) as r:
            data = r.read(120)
        text = data.decode("utf-8", errors="replace").strip()
        return True, f"OK ({len(data)} bytes): {text[:80]}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
