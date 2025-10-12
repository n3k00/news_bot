# news_push_instantview.py
# pip install requests beautifulsoup4 python-telegram-bot==20.* python-dotenv
import os, json, re, asyncio
import logging, warnings
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from urllib.parse import urljoin
from datetime import datetime, timezone
from pathlib import Path
from html import escape
import feedparser
import yaml
import requests
from bs4 import BeautifulSoup, Tag
from telegram import Bot
from telegram.constants import ParseMode
from dotenv import load_dotenv

LIST_URL   = "https://www.bbc.com/burmese.lite"
HEADERS    = {"User-Agent": "Mozilla/5.0"}
# Persist seen.json next to this script (stable across CWDs)
BASE_DIR   = Path(__file__).resolve().parent
SEEN_PATH  = BASE_DIR / "seen.json"
POLL_SEC   = 300
LIVE_PAT   = re.compile(r"(တိုက်ရိုက်(?:ထုတ်လွှင့်မှု|ထုတ်လွင့်မှု)?|live\b)", re.I)


# -------------------- Silence warnings/log noise --------------------
def _silence_noise() -> None:
    try:
        # Lower log level for noisy libs
        logging.basicConfig(level=logging.ERROR)
        logging.getLogger().setLevel(logging.ERROR)
        for name in ("telegram", "httpx", "urllib3", "asyncio", "bs4"):
            logging.getLogger(name).setLevel(logging.ERROR)

        # Suppress Python warnings from common sources
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
        # Fallback: ignore all remaining warnings
        warnings.filterwarnings("ignore")
    except Exception:
        # Never fail just because of logging/warnings setup
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
    type: str  # "rss" | "bbc"
    url: str
    chat_id: Optional[str] = None
    template: Optional[str] = None
    parse_mode: str = "HTML"  # HTML|Markdown
    resolve: bool = False      # resolve canonical URL before sending
    fulltext: bool = False     # fetch and send full article text
    split_len: int = 3500      # max characters per message part

# -------------------- Seen tracking --------------------
def load_seen() -> Dict[str, List[str]]:
    try:
        with open(SEEN_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    if isinstance(data, list):
        # backward-compat: single bucket
        return {"default": [str(x) for x in data]}
    if isinstance(data, dict):
        feeds = data.get("feeds") if isinstance(data, dict) else None
        if isinstance(feeds, dict):
            return {str(k): [str(i) for i in v] for k, v in feeds.items()}
        return {str(k): [str(i) for i in v] for k, v in data.items() if isinstance(v, list)}
    return {}

def save_seen(mapper: Dict[str, List[str]]) -> None:
    payload = {"feeds": {k: sorted(set(v)) for k, v in mapper.items()}}
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

# -------------------- Fetch news list --------------------
def fetch_list() -> List[Item]:
    try:
        r = requests.get(LIST_URL, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except requests.RequestException:
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    ul = soup.select_one("ul.bbc-14jdpb9") or soup.find("ul", class_="bbc-14jdpb9")
    if not isinstance(ul, Tag):
        return []
    out: List[Item] = []
    for li in ul.select("li"):
        h3 = li.select_one("h3")
        if not isinstance(h3, Tag): continue
        for el in h3.select("span[data-testid='visually-hidden-text'], span.bbc-m04vo2"):
            el.decompose()
        title = h3.get_text(" ", strip=True)
        a = h3.select_one("a[href]") or li.select_one("a[href]")
        href_val = a.get("href") if isinstance(a, Tag) else None
        href = href_val if isinstance(href_val, str) else ""
        link = urljoin(LIST_URL, href) if href else ""
        t = li.find("time")
        date_text = t.get_text(strip=True) if isinstance(t, Tag) else ""
        date_iso  = t.get("datetime", "") if isinstance(t, Tag) and t.has_attr("datetime") else ""
        raw = h3.get_text(" ", strip=True)
        if not title or not link: continue
        if "/live/" in link.lower() or LIVE_PAT.search(raw) or h3.select_one("svg.first-promo"):
            continue
        out.append(Item(id=link, title=title, link=link, date_text=date_text, date_iso=date_iso))
    return out

# -------------------- Fetch RSS --------------------
def fetch_rss(feed_url: str) -> List[Item]:
    try:
        r = requests.get(feed_url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        parsed = feedparser.parse(r.content)
    except Exception:
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

# -------------------- Config --------------------
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
        except Exception:
            pass
    if feeds:
        return feeds
    # Fallback defaults
    base = [Feed(key="bbc_burmese", type="bbc", url=LIST_URL, chat_id=default_chat, template=None, parse_mode="HTML")]
    # If default_chat present, also add Myanmar Now RSS
    base.append(Feed(key="myanmarnow", type="rss", url="https://myanmar-now.org/mm/feed/", chat_id=default_chat, template=None, parse_mode="HTML", resolve=True, fulltext=True))
    return base

# -------------------- Helpers --------------------
def fmt_date(dt_iso: str, fallback_text: str) -> str:
    if dt_iso: return dt_iso
    return fallback_text or datetime.now(timezone.utc).strftime("%Y-%m-%d")

def parse_iso(dt_iso: str) -> Optional[datetime]:
    if not dt_iso: return None
    s = dt_iso.strip()
    if s.endswith("Z"): s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        # Normalize to UTC naive for consistent comparisons
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except Exception:
        return None

def parse_dt_key(it: Item):
    dt = parse_iso(it.date_iso)
    return (dt or datetime.min, it.link)

# -------------------- Push message --------------------
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

def extract_article_text(url: str) -> str:
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception:
        return ""
    soup = BeautifulSoup(r.text, "html.parser")
    _clean_soup(soup)
    node = _extract_main_node(soup)
    if not isinstance(node, Tag):
        return ""
    # Gather paragraphs and list items
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
    # Collapse excessive whitespace
    txt = re.sub(r"\s+", " ", txt)
    txt = re.sub(r"(\s*\n\s*)+", "\n\n", txt)
    return txt.strip()

def chunk_text(s: str, limit: int) -> List[str]:
    if limit <= 0:
        return [s]
    if len(s) <= limit:
        return [s]
    # Split on paragraph boundaries first
    paras = s.split("\n\n")
    chunks: List[str] = []
    cur = ""
    for p in paras:
        p = p.strip()
        if not p:
            continue
        # If paragraph itself is longer than limit, hard split it
        if len(p) > limit:
            # Flush current chunk first
            if cur:
                chunks.append(cur)
                cur = ""
            start = 0
            while start < len(p):
                chunks.append(p[start:start + limit])
                start += limit
            continue
        # Try to append to current chunk
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

async def send_fulltext(bot: Bot, dest: str, it: Item, feed: Feed) -> None:
    # Resolve canonical URL first if configured
    link = it.link
    if feed.resolve and link:
        link = resolve_canonical(link)
    body = extract_article_text(link)
    date_str = fmt_date(it.date_iso, it.date_text)
    header = f"<b>{escape(it.title)}</b>\n🗓 {date_str}\n\n{link}"
    if not body:
        await bot.send_message(chat_id=dest, text=header, parse_mode=ParseMode.HTML, disable_web_page_preview=False)
        return
    # Build messages: header and as many chunks as needed
    chunks = chunk_text(body, feed.split_len)
    start_idx = 0
    if chunks:
        first_candidate = f"{header}\n\n{escape(chunks[0])}"
        if len(first_candidate) <= feed.split_len:
            await bot.send_message(chat_id=dest, text=first_candidate, parse_mode=ParseMode.HTML, disable_web_page_preview=False)
            start_idx = 1
        else:
            # Send header alone if combined exceeds limit
            await bot.send_message(chat_id=dest, text=header, parse_mode=ParseMode.HTML, disable_web_page_preview=False)
    else:
        # No chunks, already handled body empty above, but keep safe
        await bot.send_message(chat_id=dest, text=header, parse_mode=ParseMode.HTML, disable_web_page_preview=False)
        return
    # Send remaining chunks
    for i in range(start_idx, len(chunks)):
        await bot.send_message(chat_id=dest, text=escape(chunks[i]), parse_mode=ParseMode.HTML, disable_web_page_preview=True)
def resolve_canonical(url: str) -> str:
    try:
        r = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
        r.raise_for_status()
        final = r.url or url
        soup = BeautifulSoup(r.text, "html.parser")
        # Prefer <link rel="canonical">
        link = soup.find("link", rel=lambda v: v and "canonical" in str(v).lower())
        if isinstance(link, Tag) and link.has_attr("href"):
            return urljoin(final, link.get("href"))
        # Fallback to og:url
        meta = soup.find("meta", property=lambda v: v and v.lower()=="og:url")
        if isinstance(meta, Tag) and meta.has_attr("content"):
            return urljoin(final, meta.get("content"))
        return final
    except Exception:
        return url
def _render_text(feed: 'Feed', it: Item) -> tuple[str, ParseMode]:
    date_str = fmt_date(it.date_iso, it.date_text)
    template = feed.template or "<b>{title}</b>\n🗓 {date}\n\n{link}"
    txt = template.format(title=escape(it.title), date=date_str, link=it.link)
    mode = ParseMode.HTML if str(feed.parse_mode).upper() == "HTML" else ParseMode.MARKDOWN
    return txt, mode

async def send_item(bot: Bot, chat_id: str, it: Item, feed: Optional['Feed']=None) -> None:
    if feed is None:
        date_str = fmt_date(it.date_iso, it.date_text)
        text = f"<b>{escape(it.title)}</b>\n🗓 {date_str}\n\n{it.link}"
        mode = ParseMode.HTML
    else:
        text, mode = _render_text(feed, it)
    await bot.send_message(chat_id=chat_id, text=text, parse_mode=mode, disable_web_page_preview=False)

async def push_instantview(bot: Bot, chat_id: str, it: Item) -> None:
    # caption includes link so Telegram generates Instant View preview
    date_str = fmt_date(it.date_iso, it.date_text)
    caption = f"*{it.title}*\n🗓 {date_str}\n\n{it.link}"

    # send with link preview on (disable_web_page_preview=False)
    await bot.send_message(
        chat_id=chat_id,
        text=f"<b>{escape(it.title)}</b>\n🗓 {date_str}\n\n{it.link}",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=False
    )

# -------------------- Main logic --------------------
async def run_once() -> None:
    load_dotenv()
    if not os.getenv("BOT_TOKEN") or not os.getenv("CHAT_ID"):
        base = os.path.dirname(os.path.abspath(__file__))
        fallback = os.path.join(base, ".env")
        if os.path.exists(fallback):
            load_dotenv(fallback)
    token = os.getenv("BOT_TOKEN")
    chat  = os.getenv("CHAT_ID")
    if not token or not chat:
        raise RuntimeError("BOT_TOKEN / CHAT_ID မရှိ")

    items = fetch_list()
    if not items: return

    seen = load_seen()
    new_items = [it for it in items if it.id not in seen]
    if not new_items: return

    new_items_sorted = sorted(new_items, key=parse_dt_key)  # old → new
    async with Bot(token=token) as bot:
        for it in new_items_sorted:
            await push_instantview(bot, chat, it)
            seen.add(it.id)
            save_seen(seen)

async def run_once_multi() -> None:
    load_dotenv()
    if not os.getenv("BOT_TOKEN") or not os.getenv("CHAT_ID"):
        base = os.path.dirname(os.path.abspath(__file__))
        fallback = os.path.join(base, ".env")
        if os.path.exists(fallback):
            load_dotenv(fallback)
    token = os.getenv("BOT_TOKEN")
    chat  = os.getenv("CHAT_ID")
    if not token or not chat:
        raise RuntimeError("BOT_TOKEN / CHAT_ID ????")

    feeds = load_config(default_chat=chat)
    seen_map = load_seen()

    async with Bot(token=token) as bot:
        for f in feeds:
            items: List[Item]
            if f.type == "rss":
                items = fetch_rss(f.url)
            else:
                items = fetch_list()
            if not items:
                continue
            key = f.key
            sent_ids = set(seen_map.get(key, []))
            new_items = [it for it in items if it.id not in sent_ids]
            if not new_items:
                continue
            new_items_sorted = sorted(new_items, key=parse_dt_key)
            dest = f.chat_id or chat
            for it in new_items_sorted:
                if f.fulltext and f.type == "rss":
                    await send_fulltext(bot, dest, it, feed=f)
                else:
                    use_it = it
                    if f.resolve and it.link:
                        new_link = resolve_canonical(it.link)
                        if new_link and new_link != it.link:
                            use_it = Item(id=it.id, title=it.title, link=new_link, date_text=it.date_text, date_iso=it.date_iso)
                    await send_item(bot, dest, use_it, feed=f)
                sent_ids.add(it.id)
                seen_map[key] = list(sent_ids)
                save_seen(seen_map)

async def main_loop() -> None:
    while True:
        try:
            await run_once_multi()
        except Exception as e:
            print("error:", e)
        await asyncio.sleep(POLL_SEC)

if __name__ == "__main__":
    _silence_noise()
    asyncio.run(main_loop())
