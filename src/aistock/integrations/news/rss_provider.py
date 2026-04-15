from __future__ import annotations

from datetime import datetime
import json
import time as _time
from pathlib import Path
from typing import Any, Dict, List

import feedparser
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from aistock.core.config import settings
from aistock.core.types import NewsItem
from aistock.integrations.news.base import NewsProvider


class RSSNewsProvider(NewsProvider):
    """Simple RSS/Atom feed-based news provider.

    - Reads a feed manifest (JSON) from `data/news_sources.json` if present, otherwise uses a small default.
    - Uses conditional GET (ETag / Last-Modified) and a small meta file to minimize bandwidth.
    - Matches incoming `symbols` against entry title/summary using simple token matching and `$SYMBOL`.
    - Populates `last_debug` similar to other providers so the pipeline can reason about failures.
    """

    def __init__(self, feeds_path: str | Path | None = None, timeout_seconds: int | None = None, max_retries: int | None = None) -> None:
        self._feeds_path = Path(feeds_path) if feeds_path is not None else Path(settings.data_dir) / "news_sources.json"
        self._meta_path = Path(settings.data_dir) / "news_meta.json"
        self._timeout = timeout_seconds or 10
        retries = max_retries if max_retries is not None else 1
        self._session = requests.Session()
        retry = Retry(
            total=max(0, retries),
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET"]),
        )
        adapter = HTTPAdapter(max_retries=retry)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)
        self.last_debug: list[Dict[str, Any]] = []

    def _default_feeds(self) -> List[Dict[str, Any]]:
        return [
            {
                "url": "https://feeds.reuters.com/reuters/businessNews",
                "domain": "reuters.com",
                "poll_interval_seconds": 1800,
            },
            {
                "url": "https://www.marketwatch.com/rss/topstories",
                "domain": "marketwatch.com",
                "poll_interval_seconds": 1800,
            },
        ]

    def _load_feeds(self) -> List[Dict[str, Any]]:
        if not self._feeds_path.exists():
            return self._default_feeds()
        try:
            data = json.loads(self._feeds_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception:
            pass
        return self._default_feeds()

    def _load_meta(self) -> Dict[str, Any]:
        if not self._meta_path.exists():
            return {}
        try:
            return json.loads(self._meta_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_meta(self, meta: Dict[str, Any]) -> None:
        try:
            self._meta_path.parent.mkdir(parents=True, exist_ok=True)
            self._meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _parse_entry_published(self, entry: dict) -> datetime:
        # feedparser exposes `published_parsed` or `updated_parsed` as time.struct_time
        for k in ("published_parsed", "updated_parsed"):
            t = entry.get(k)
            if t:
                try:
                    return datetime.fromtimestamp(_time.mktime(t))
                except Exception:
                    break
        # fallback to string dates
        for k in ("published", "updated"):
            s = entry.get(k)
            if s:
                try:
                    # best-effort parsing for ISO-like strings
                    return datetime.fromisoformat(str(s))
                except Exception:
                    break
        return datetime.utcnow()

    def fetch_news(self, symbols: list[str], per_symbol: int = 5) -> list[NewsItem]:
        self.last_debug = []
        items: list[NewsItem] = []
        if not symbols:
            return items

        symbols_up = [s.upper() for s in symbols]
        per_symbol_counts: dict[str, int] = {s: 0 for s in symbols_up}
        seen: set[str] = set()

        feeds = self._load_feeds()
        meta = self._load_meta()

        for feed in feeds:
            url = str(feed.get("url", "")).strip()
            if not url:
                continue
            debug_item: dict[str, Any] = {"feed": url, "status": "ok", "http_status": None, "result_count": 0, "error": None}
            headers = {"User-Agent": "AIStock/1.0", "Accept": "*/*"}
            entry_meta = meta.get(url, {}) if isinstance(meta, dict) else {}
            if isinstance(entry_meta, dict):
                etag = entry_meta.get("etag")
                lm = entry_meta.get("last_modified")
                if etag:
                    headers["If-None-Match"] = etag
                if lm:
                    headers["If-Modified-Since"] = lm

            try:
                resp = self._session.get(url, headers=headers, timeout=self._timeout)
                debug_item["http_status"] = resp.status_code
                if resp.status_code == 304:
                    debug_item["status"] = "not_modified"
                    self.last_debug.append(debug_item)
                    continue
                if resp.status_code in {401, 403}:
                    debug_item["status"] = "auth_error"
                    debug_item["error"] = f"HTTP {resp.status_code}"
                    self.last_debug.append(debug_item)
                    continue
                if resp.status_code == 429:
                    debug_item["status"] = "rate_limited"
                    debug_item["error"] = "HTTP 429"
                    self.last_debug.append(debug_item)
                    continue
                resp.raise_for_status()
                fp = feedparser.parse(resp.content)
            except Exception as exc:
                debug_item["status"] = "error"
                debug_item["error"] = f"{type(exc).__name__}: {exc}"
                self.last_debug.append(debug_item)
                continue

            # update meta with ETag/Last-Modified
            try:
                m = meta.get(url, {}) if isinstance(meta, dict) else {}
                if resp.headers.get("ETag"):
                    m["etag"] = resp.headers.get("ETag")
                if resp.headers.get("Last-Modified"):
                    m["last_modified"] = resp.headers.get("Last-Modified")
                meta[url] = m
            except Exception:
                pass

            entries = fp.get("entries", []) or []
            matched_count = 0
            for entry in entries:
                title = str(entry.get("title", "")).strip()
                summary = str(entry.get("summary", "") or entry.get("description", "") or "").strip()
                link = str(entry.get("link", "") or "").strip()
                published = self._parse_entry_published(entry)

                key = link or (title + "|" + published.isoformat())
                if key in seen:
                    continue

                # try to match any symbol
                matched = False
                for sym in symbols_up:
                    if per_symbol_counts.get(sym, 0) >= per_symbol:
                        continue
                    hay_title = title.upper()
                    hay_summary = summary.upper()
                    if sym in hay_title or f"${sym}" in hay_title or sym in hay_summary or f"${sym}" in hay_summary:
                        items.append(
                            NewsItem(
                                symbol=sym,
                                headline=title or f"News for {sym}",
                                source=str(feed.get("domain") or feed.get("url") or "rss"),
                                summary=summary if summary else None,
                                published_at=published,
                            )
                        )
                        per_symbol_counts[sym] = per_symbol_counts.get(sym, 0) + 1
                        matched = True
                        seen.add(key)
                        matched_count += 1
                        break
                # stop early if all symbols satisfied
                if all(per_symbol_counts[s] >= per_symbol for s in symbols_up):
                    break

            debug_item["result_count"] = matched_count
            self.last_debug.append(debug_item)

        # persist meta
        try:
            self._save_meta(meta)
        except Exception:
            pass

        return items
