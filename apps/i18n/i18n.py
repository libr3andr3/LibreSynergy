#!/usr/bin/env python3
"""LibreSynergy shared i18n — pure stdlib, mounted read-only into each sidecar.

The catalog is split into per-namespace files under strings/ (common.json,
admin.json, bridge.json, …) and merged at import, so parallel translation work
never collides on one big file. Language is resolved per request:

    ?lang=xx  >  ls_lang cookie  >  Accept-Language  >  LS_DEFAULT_LANG  >  en

Translations fall back  lang -> en -> the key itself, so a missing string is
never fatal — it just renders in English (or, worst case, shows the key).

Usage inside a BaseHTTPRequestHandler:

    import sys
    for _p in ("/i18n", "/ls/apps/i18n"):
        if os.path.isdir(_p): sys.path.insert(0, _p); break
    import i18n
    ...
    lang, set_cookie = i18n.resolve(self)
    title = i18n.t(lang, "admin.page_title", brand="Yaya")
"""
import glob
import http.cookies
import json
import os
import urllib.parse

LANGS = ("en", "es", "fr")                       # supported UI languages
DEFAULT = (os.environ.get("LS_DEFAULT_LANG", "en") or "en").strip().lower()[:2]
if DEFAULT not in LANGS:
    DEFAULT = "en"

# First existing dir wins: explicit override, the read-only mount, then the
# repo-root mount that every sidecar already has (..:/ls).
_DIRS = [os.environ.get("LS_I18N_DIR"), "/i18n/strings", "/ls/apps/i18n/strings"]


def _load():
    catalog = {}
    for d in _DIRS:
        if not d or not os.path.isdir(d):
            continue
        for path in sorted(glob.glob(os.path.join(d, "*.json"))):
            try:
                data = json.load(open(path, encoding="utf-8"))
            except Exception:
                continue                          # a broken file must not brick the UI
            for lang, table in (data or {}).items():
                catalog.setdefault(lang, {}).update(table or {})
        break
    return catalog


STRINGS = _load()


def _norm(code):
    return (code or "").strip().lower()[:2]


def negotiate(accept_language=None, cookie_lang=None, query_lang=None):
    """Return a supported language code by precedence (see module docstring)."""
    for cand in (query_lang, cookie_lang):
        if _norm(cand) in LANGS:
            return _norm(cand)
    for part in (accept_language or "").split(","):          # "es-PE,es;q=0.9,en;q=0.8"
        if _norm(part.split(";")[0]) in LANGS:
            return _norm(part.split(";")[0])
    return DEFAULT


def resolve(handler):
    """From a BaseHTTPRequestHandler -> (lang, set_cookie).

    set_cookie is True only when an explicit ?lang= was honored, so the caller
    can persist the choice with a Set-Cookie header.
    """
    q = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
    query_lang = (q.get("lang") or [None])[0]
    cookie_lang = None
    raw = handler.headers.get("Cookie")
    if raw:
        try:
            c = http.cookies.SimpleCookie(raw).get("ls_lang")
            cookie_lang = c.value if c else None
        except Exception:
            cookie_lang = None
    lang = negotiate(handler.headers.get("Accept-Language"), cookie_lang, query_lang)
    return lang, (_norm(query_lang) in LANGS)


def t(lang, key, **fmt):
    """Translate key for lang; fall back lang -> en -> key. **fmt feeds str.format."""
    lang = lang if lang in LANGS else DEFAULT
    val = (STRINGS.get(lang) or {}).get(key)
    if val is None:
        val = (STRINGS.get("en") or {}).get(key, key)
    if fmt:
        try:
            return val.format(**fmt)
        except Exception:
            return val
    return val


def switcher_html(lang, base_path="/"):
    """A small EN/ES/FR language switcher; the current language gets class .cur."""
    sep = "&" if "?" in base_path else "?"
    links = []
    for code in LANGS:
        cur = " cur" if code == lang else ""
        links.append(f'<a class="ls-lang{cur}" href="{base_path}{sep}lang={code}">{code.upper()}</a>')
    return '<span class="ls-langsw">' + "".join(links) + "</span>"
