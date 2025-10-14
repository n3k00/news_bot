#!/usr/bin/env python3
# Shared news bot core logic
import asyncio
import json
import logging
import re
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup, Tag
from telegram import Bot
from telegram.constants import ParseMode


LIST_URL = "https://www.bbc.com/burmese.lite"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

ELEVEN_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://news-eleven.com/",
    "Connection": "keep-alive",
}

def headers_for(url: str | None) -> Dict[str, str]:
    h = dict(HEADERS)
    try:
        from urllib.parse import urlparse
        host = urlparse(url or "").netloc.lower()
    except Exception:
        host = ""
    if "news-eleven.com" in host:
        h.update(ELEVEN_HEADERS)
    elif "dvb.no" in host:
        # DVB specific headers
        h.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://burmese.dvb.no/",
            "Connection": "keep-alive",
        })
    return h
BASE_DIR = Path(__file__).resolve().parent
SEEN_PATH = BASE_DIR / "seen.json"
POLL_SEC = 60
LIVE_PAT = re.compile(r"\blive\b", re.I)

logger = logging.getLogger(__name__)


def _silence_noise() -> None:
    try:
        logging.basicConfig(level=logging.INFO)
        logging.getLogger().setLevel(logging.INFO)
        for name in ("telegram", "httpx", "urllib3", "asyncio", "bs4"):
            logging.getLogger(name).setLevel(logging.ERROR)
        try:
            from telegram.warnings import PTBUserWarning  # type: ignore
            warnings.filterwarnings("ignore", category=PTBUserWarning)
        except Exception:
            pass
        try:
            from bs4 import MarkupResemblesLocatorWarning  # type: ignore
            warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)
        except Exception:
            pass
        warnings.filterwarnings("ignore", category=UserWarning, module="bs4")
    except Exception:
        pass


@dataclass(frozen=True)
class Item:
    id: str
    title: str
    link: str
    date_text: str
    date_iso: str


@dataclass(frozen=True)
class Feed:
    key: str
    type: str  # "rss" | "bbc" | "dvb" | "eleven"
    url: str
    chat_id: Optional[str] = None
    template: Optional[str] = None
    parse_mode: str = "HTML"
    resolve: bool = False
    fulltext: bool = False
    split_len: int = 3500


def load_seen() -> Dict[str, List[str]]:
    try:
        with open(SEEN_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            if "feeds" in data and isinstance(data["feeds"], dict):
                return {str(k): [str(i) for i in v] for k, v in data["feeds"].items()}
            return {str(k): [str(i) for i in v] for k, v in data.items() if isinstance(v, list)}
    except Exception:
        pass
    return {}


def save_seen(mapper: Dict[str, List[str]]) -> None:
    try:
        with open(SEEN_PATH, "w", encoding="utf-8") as f:
            json.dump({k: sorted(set(v)) for k, v in mapper.items()}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("failed to save seen.json: %s", e)


def fetch_list() -> List[Item]:
    try:
        r = requests.get(LIST_URL, headers=headers_for(LIST_URL), timeout=20)
        r.raise_for_status()
    except requests.RequestException as e:
        logger.warning("fetch_list error: %s", e)
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    ul = soup.select_one("ul.bbc-14jdpb9") or soup.find("ul", class_="bbc-14jdpb9")
    if not isinstance(ul, Tag):
        return []
    out: List[Item] = []
    for li in ul.select("li"):
        h3 = li.select_one("h3")
        if not isinstance(h3, Tag):
            continue
        for el in h3.select("span[data-testid='visually-hidden-text'], span.bbc-m04vo2"):
            el.decompose()
        title = h3.get_text(" ", strip=True)
        a = h3.select_one("a[href]") or li.select_one("a[href]")
        href_val = a.get("href") if isinstance(a, Tag) else None
        href = href_val if isinstance(href_val, str) else ""
        link = urljoin(LIST_URL, href) if href else ""
        t = li.find("time")
        date_text = t.get_text(strip=True) if isinstance(t, Tag) else ""
        date_iso = t.get("datetime", "") if isinstance(t, Tag) and t.has_attr("datetime") else ""
        raw = h3.get_text(" ", strip=True)
        if not title or not link:
            continue
        if "/live/" in link.lower() or LIVE_PAT.search(raw) or h3.select_one("svg.first-promo"):
            continue
        out.append(Item(id=link, title=title, link=link, date_text=date_text, date_iso=date_iso))
    return out


def fetch_rss(feed_url: str) -> List[Item]:
    try:
        r = requests.get(feed_url, headers=headers_for(feed_url), timeout=20)
        r.raise_for_status()
        parsed = feedparser.parse(r.content)
    except Exception as e:
        logger.warning("fetch_rss error: %s", e)
        return []
    out: List[Item] = []
    for e in getattr(parsed, "entries", []) or []:
        title = getattr(e, "title", "") or ""
        link = getattr(e, "link", "") or ""
        if not title or not link:
            continue
        eid = getattr(e, "id", "") or link
        date_text = getattr(e, "published", "") or getattr(e, "updated", "") or ""
        date_iso = getattr(e, "published", "") or getattr(e, "updated", "") or ""
        out.append(Item(id=str(eid), title=str(title), link=str(link), date_text=str(date_text), date_iso=str(date_iso)))
    return out


def fetch_eleven(base: str) -> List[Item]:
    """Scrape News Eleven category/listing pages for article links.
    Example: https://news-eleven.com/business
    """
    try:
        u = (base or "").strip()
        if not u:
            return []
        r = requests.get(u, headers=headers_for(u), timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        selectors = [
            "a[href^='/article/']",
            "a[href^='https://news-eleven.com/article/']",
            "article h2 a[href]",
            "article h3 a[href]",
            "div.views-row h2 a[href]",
            "div.views-row h3 a[href]",
        ]
        seen: set[str] = set()
        out: List[Item] = []
        for sel in selectors:
            for a in soup.select(sel):
                if not isinstance(a, Tag):
                    continue
                href = a.get("href")
                if not isinstance(href, str) or not href.strip():
                    continue
                link = urljoin(u, href)
                if link in seen:
                    continue
                title = a.get_text(" ", strip=True) or a.get("title") or ""
                if not title:
                    img = a.find("img")
                    if isinstance(img, Tag):
                        alt = img.get("alt")
                        if isinstance(alt, str) and alt.strip():
                            title = alt.strip()
                if not title:
                    continue
                seen.add(link)
                out.append(Item(id=link, title=title, link=link, date_text="", date_iso=""))
        return out
    except Exception as e:
        logger.warning("fetch_eleven error: %s", e)
        return []


def load_config(default_chat: Optional[str]) -> List[Feed]:
    cfg_path = BASE_DIR / "feeds.yaml"
    feeds: List[Feed] = []
    if cfg_path.exists():
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                data: Dict[str, Any] = yaml.safe_load(f) or {}
            entries = data.get("feeds", []) if isinstance(data, dict) else []
            for ent in entries:
                if not isinstance(ent, dict):
                    continue
                key = str(ent.get("key") or ent.get("name") or ent.get("url") or "feed")
                ftype = str(ent.get("type") or "rss").lower()
                url = str(ent.get("url") or "").strip()
                chat_id = str(ent.get("chat_id") or (default_chat or "")) or None
                template = ent.get("template")
                parse_mode = str(ent.get("parse_mode") or "HTML")
                resolve = bool(ent.get("resolve_canonical") or ent.get("resolve") or False)
                fulltext = bool(ent.get("fulltext") or False)
                split_len = int(ent.get("split_len") or 3500)
                if not url:
                    continue
                feeds.append(Feed(key=key, type=ftype, url=url, chat_id=chat_id, template=template, parse_mode=parse_mode, resolve=resolve, fulltext=fulltext, split_len=split_len))
        except Exception as e:
            logger.warning("failed to load config: %s", e)
    if feeds:
        return feeds
    base = [Feed(key="bbc_burmese", type="bbc", url=LIST_URL, chat_id=default_chat, template=None, parse_mode="HTML")]
    base.append(Feed(key="myanmarnow", type="rss", url="https://myanmar-now.org/mm/feed/", chat_id=default_chat, template=None, parse_mode="HTML", resolve=True, fulltext=True))
    return base


def fmt_date(dt_iso: str, fallback_text: str) -> str:
    if dt_iso:
        return dt_iso
    return fallback_text or datetime.now(timezone.utc).strftime("%Y-%m-%d")


def parse_iso(dt_iso: str) -> Optional[datetime]:
    if not dt_iso:
        return None
    s = dt_iso.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except Exception:
        return None


def parse_dt_key(it: Item):
    dt = parse_iso(it.date_iso)
    return (dt or datetime.min, it.link)


def _clean_soup(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(["script", "style", "noscript", "iframe", "svg", "form", "header", "footer", "nav", "aside"]):
        tag.decompose()


def _extract_main_node(soup: BeautifulSoup) -> Tag | None:
    candidates = []
    selectors = [
        "article",
        "div.entry-content",
        "div.td-post-content",
        "div[itemprop='articleBody']",
        "div.post-content",
        "div.single-post-content",
        "div.article-content",
        "main",
        "section.article",
        "div#region-content",
        "#content",
        "div.node__content",
        "div.field--name-body",
        "div.field__item",
    ]
    for sel in selectors:
        for node in soup.select(sel):
            if isinstance(node, Tag):
                txt = node.get_text(" ", strip=True)
                candidates.append((len(txt), node))
    if not candidates:
        body = soup.body if hasattr(soup, "body") else None
        return body if isinstance(body, Tag) else None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _strip_html_to_text(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    _clean_soup(soup)
    node = _extract_main_node(soup) or soup
    parts: List[str] = []
    for el in node.find_all(["p", "li"]):
        if not isinstance(el, Tag):
            continue
        t = el.get_text(" ", strip=True)
        if not t:
            continue
        if el.name == "li":
            t = "• " + t
        parts.append(t)
    txt = "\n\n".join(parts).strip()
    try:
        txt = txt.replace("\x07 ", "\u2022 ")
    except Exception:
        pass
    txt = re.sub(r"(\s*\n\s*)+", "\n\n", txt)
    return txt


def extract_article_text(url: str) -> str:
    try:
        r = requests.get(url, headers=headers_for(url), timeout=20)
        r.raise_for_status()
    except Exception as e:
        logger.warning("extract_article_text error: %s", e)
        return ""
    soup = BeautifulSoup(r.text, "html.parser")
    _clean_soup(soup)
    node = _extract_main_node(soup)
    if not isinstance(node, Tag):
        return ""
    parts: List[str] = []
    for el in node.find_all(["p", "li"]):
        if not isinstance(el, Tag):
            continue
        t = el.get_text(" ", strip=True)
        if not t:
            continue
        if el.name == "li":
            t = "• " + t
        parts.append(t)
    txt = "\n\n".join(parts)
    try:
        txt = txt.replace("\x07 ", "\u2022 ")
    except Exception:
        pass
    txt = re.sub(r"\s+", " ", txt)
    txt = re.sub(r"(\s*\n\s*)+", "\n\n", txt)
    return txt.strip()


def extract_dvb_text(url: str) -> str:
    try:
        m = re.search(r"/archives/(\d+)", url)
        post_id = m.group(1) if m else ""
        if not post_id:
            return extract_article_text(url)
        api = f"https://burmese.dvb.no/wp-json/wp/v2/posts/{post_id}"
        r = requests.get(api, headers=headers_for(api), timeout=20)
        r.raise_for_status()
        data = r.json()
        html = data.get("content", {}).get("rendered", "") if isinstance(data, dict) else ""
        return _strip_html_to_text(html)
    except Exception as e:
        logger.warning("extract_dvb_text error: %s", e)
        return extract_article_text(url)


def chunk_text(s: str, limit: int) -> List[str]:
    if limit <= 0:
        return [s]
    if len(s) <= limit:
        return [s]
    paras = s.split("\n\n")
    chunks: List[str] = []
    cur = ""
    for p in paras:
        p = p.strip()
        if not p:
            continue
        if len(p) > limit:
            if cur:
                chunks.append(cur)
                cur = ""
            start = 0
            while start < len(p):
                chunks.append(p[start:start + limit])
                start += limit
            continue
        candidate = (cur + ("\n\n" if cur else "") + p).strip()
        if len(candidate) <= limit:
            cur = candidate
        else:
            if cur:
                chunks.append(cur)
            cur = p
    if cur:
        chunks.append(cur)
    return chunks


def resolve_canonical(url: str) -> str:
    try:
        r = requests.get(url, headers=headers_for(url), timeout=20, allow_redirects=True)
        r.raise_for_status()
        final = r.url or url
        soup = BeautifulSoup(r.text, "html.parser")
        link = soup.find("link", rel=lambda v: v and "canonical" in str(v).lower())
        if isinstance(link, Tag) and link.has_attr("href"):
            return urljoin(final, link.get("href"))
        meta = soup.find("meta", property=lambda v: v and v.lower() == "og:url")
        if isinstance(meta, Tag) and meta.has_attr("content"):
            return urljoin(final, meta.get("content"))
        return final
    except Exception:
        return url


def _render_text(feed: 'Feed', it: Item) -> tuple[str, ParseMode]:
    date_str = fmt_date(it.date_iso, it.date_text)
    template = feed.template or "<b>{title}</b>\nDate: {date}\n\n{link}"
    txt = template.format(title=escape(it.title), date=date_str, link=it.link)
    return txt, ParseMode.HTML


async def send_item(bot: Bot, chat_id: str, it: Item, feed: Optional['Feed'] = None) -> None:
    if feed is None:
        date_str = fmt_date(it.date_iso, it.date_text)
        text = f"<b>{escape(it.title)}</b>\nDate: {date_str}\n\n{it.link}"
        mode = ParseMode.HTML
    else:
        text, mode = _render_text(feed, it)
    await bot.send_message(chat_id=chat_id, text=text, parse_mode=mode, disable_web_page_preview=False)


async def send_fulltext(bot: Bot, dest: str, it: Item, feed: Feed) -> None:
    link = it.link
    if feed.resolve and link:
        try:
            link = await asyncio.to_thread(resolve_canonical, link)
        except Exception as e:
            logger.warning("resolve_canonical failed: %s", e)
    try:
        if getattr(feed, "type", "") == "dvb":
            body = await asyncio.to_thread(extract_dvb_text, link)
        else:
            body = await asyncio.to_thread(extract_article_text, link)
    except Exception as e:
        logger.warning("article extraction failed: %s", e)
        body = ""
    date_str = fmt_date(it.date_iso, it.date_text)
    header = f"<b>{escape(it.title)}</b>\nDate: {date_str}\n\n{link}"
    if not body:
        await bot.send_message(chat_id=dest, text=header, parse_mode=ParseMode.HTML, disable_web_page_preview=False)
        return
    chunks = chunk_text(body, feed.split_len)
    start_idx = 0
    if chunks:
        first_candidate = f"{header}\n\n{escape(chunks[0])}"
        if len(first_candidate) <= feed.split_len:
            await bot.send_message(chat_id=dest, text=first_candidate, parse_mode=ParseMode.HTML, disable_web_page_preview=False)
            start_idx = 1
        else:
            await bot.send_message(chat_id=dest, text=header, parse_mode=ParseMode.HTML, disable_web_page_preview=False)
    else:
        await bot.send_message(chat_id=dest, text=header, parse_mode=ParseMode.HTML, disable_web_page_preview=False)
        return
    for i in range(start_idx, len(chunks)):
        await asyncio.sleep(0.2)
        await bot.send_message(chat_id=dest, text=escape(chunks[i]), parse_mode=ParseMode.HTML, disable_web_page_preview=True)


def fetch_dvb(base: str) -> List[Item]:
    try:
        u = (base or "").strip()
        if "/wp-json/" not in u:
            u = "https://burmese.dvb.no/wp-json/wp/v2/posts?per_page=10&_fields=id,link,date,title,content"
        r = requests.get(u, headers=headers_for(u), timeout=20)
        r.raise_for_status()
        arr = r.json()
        out: List[Item] = []
        if not isinstance(arr, list):
            return out
        for e in arr:
            if not isinstance(e, dict):
                continue
            link = str(e.get("link") or "")
            title_obj = e.get("title") or {}
            title = title_obj.get("rendered", "") if isinstance(title_obj, dict) else str(title_obj or "")
            date = str(e.get("date") or "")
            if not title or not link:
                continue
            out.append(Item(id=link, title=str(title), link=link, date_text=date, date_iso=date))
        return out
    except Exception as e:
        logger.warning("fetch_dvb error: %s", e)
        return []


async def run_once_multi(token: str, chat: str) -> None:
    feeds = load_config(default_chat=chat)
    seen_map = load_seen()

    async with Bot(token=token) as bot:
        for f in feeds:
            try:
                if f.type == "rss":
                    items = await asyncio.to_thread(fetch_rss, f.url)
                elif f.type == "dvb":
                    items = await asyncio.to_thread(fetch_dvb, f.url)
                elif f.type == "eleven":
                    items = await asyncio.to_thread(fetch_eleven, f.url)
                    # Only consider latest 5 items for Eleven
                    if items:
                        items = items[:5]
                elif f.type == "bbc":
                    items = await asyncio.to_thread(fetch_list)
                else:
                    items = []
            except Exception as e:
                logger.warning("fetch items failed for %s: %s", f.key, e)
                continue
            logger.info("feed=%s type=%s fetched=%d", f.key, f.type, len(items) if items else 0)
            if not items:
                continue
            key = f.key
            sent_ids = set(seen_map.get(key, []))
            new_items = [it for it in items if it.id not in sent_ids]
            logger.info("feed=%s new_items=%d", f.key, len(new_items))
            if not new_items:
                continue
            new_items_sorted = sorted(new_items, key=parse_dt_key)
            dest = f.chat_id or chat
            for it in new_items_sorted:
                try:
                    if f.fulltext:
                        await send_fulltext(bot, dest, it, feed=f)
                    else:
                        await send_item(bot, dest, it, feed=f)
                except Exception as e:
                    logger.warning("send failed for %s: %s", it.link, e)
                sent_ids.add(it.id)
            seen_map[key] = sorted(sent_ids)
            save_seen(seen_map)
            logger.info("feed=%s seen_saved ids=%d", f.key, len(seen_map.get(key, [])))


async def main_loop(token: str, chat: str) -> None:
    while True:
        logger.info("run_once_multi start")
        await run_once_multi(token, chat)
        logger.info("sleeping %ss", POLL_SEC)
        await asyncio.sleep(POLL_SEC)
