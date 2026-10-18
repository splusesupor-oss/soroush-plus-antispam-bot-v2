"""Keyless factual answer provider using public Persian Wikipedia endpoints."""
import re
from html import unescape
from urllib.parse import quote

import requests

from modules import free_tier

_SEARCH_URL = "https://fa.wikipedia.org/w/rest.php/v1/search/page?q={query}&limit=1"
_SUMMARY_URL = "https://fa.wikipedia.org/api/rest_v1/page/summary/{key}"
_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "SoroushPlusBot/1.0 (group factual assistant)"})


class WikiSearchError(RuntimeError):
    pass


def _clean(value):
    return " ".join(unescape(re.sub(r"<.*?>", " ", str(value or ""))).split())


def answer(query):
    """Return a short factual summary; no API key, no generative provider."""
    if not free_tier.is_enabled("ai"):
        raise WikiSearchError("feature_disabled")
    query = " ".join(str(query or "").strip().split())
    if not query:
        raise WikiSearchError("empty_query")
    try:
        search = _SESSION.get(_SEARCH_URL.format(query=quote(query)), timeout=(4, 10))
    except requests.Timeout as error:
        raise WikiSearchError("timeout") from error
    except requests.RequestException as error:
        raise WikiSearchError("transport") from error
    if search.status_code != 200:
        raise WikiSearchError(f"http_{search.status_code}")
    try:
        pages = search.json().get("pages") or []
        page = pages[0] if pages else None
        key = page.get("key") if isinstance(page, dict) else None
    except (ValueError, TypeError, KeyError) as error:
        raise WikiSearchError("invalid_search_response") from error
    if not key:
        raise WikiSearchError("no_results")
    try:
        summary = _SESSION.get(_SUMMARY_URL.format(key=quote(key)), timeout=(4, 10))
    except requests.Timeout as error:
        raise WikiSearchError("timeout") from error
    except requests.RequestException as error:
        raise WikiSearchError("transport") from error
    if summary.status_code != 200:
        raise WikiSearchError(f"summary_http_{summary.status_code}")
    try:
        data = summary.json()
        extract = _clean(data.get("extract"))
        title = _clean(data.get("title"))
    except (ValueError, TypeError) as error:
        raise WikiSearchError("invalid_summary_response") from error
    if not extract:
        raise WikiSearchError("no_results")
    return f"{extract[:700]}\n\nمنبع: ویکی‌پدیا — {title}" if title else extract[:700]
