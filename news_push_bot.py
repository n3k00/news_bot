# news_push_instantview.py
# pip install requests beautifulsoup4 python-telegram-bot==20.* python-dotenv
import os, json, re, asyncio
import logging, warnings
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urljoin
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup, Tag
from telegram import Bot
from telegram.constants import ParseMode
from dotenv import load_dotenv

LIST_URL   = "https://www.bbc.com/burmese.lite"
HEADERS    = {"User-Agent": "Mozilla/5.0"}
SEEN_PATH  = "seen.json"
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

# -------------------- Seen tracking --------------------
def load_seen() -> set[str]:
    try:
        with open(SEEN_PATH, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        try:
            with open(os.path.join("NewsBot", "seen.json"), "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()

def save_seen(s: set[str]) -> None:
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(s), f, ensure_ascii=False, indent=2)

# -------------------- Fetch news list --------------------
def fetch_list() -> List[Item]:
    r = requests.get(LIST_URL, headers=HEADERS, timeout=20); r.raise_for_status()
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
        link = urljoin(LIST_URL, a["href"]) if isinstance(a, Tag) else ""
        t = li.find("time")
        date_text = t.get_text(strip=True) if isinstance(t, Tag) else ""
        date_iso  = t.get("datetime", "") if isinstance(t, Tag) and t.has_attr("datetime") else ""
        raw = h3.get_text(" ", strip=True)
        if not title or not link: continue
        if "/live/" in link.lower() or LIVE_PAT.search(raw) or h3.select_one("svg.first-promo"):
            continue
        out.append(Item(id=link, title=title, link=link, date_text=date_text, date_iso=date_iso))
    return out

# -------------------- Helpers --------------------
def fmt_date(dt_iso: str, fallback_text: str) -> str:
    if dt_iso: return dt_iso
    return fallback_text or datetime.now(timezone.utc).strftime("%Y-%m-%d")

def parse_iso(dt_iso: str) -> Optional[datetime]:
    if not dt_iso: return None
    s = dt_iso.strip()
    if s.endswith("Z"): s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None

def parse_dt_key(it: Item):
    dt = parse_iso(it.date_iso)
    return (dt or datetime.min.replace(tzinfo=None), it.link)

# -------------------- Push message --------------------
async def push_instantview(bot: Bot, chat_id: str, it: Item) -> None:
    # caption includes link so Telegram generates Instant View preview
    date_str = fmt_date(it.date_iso, it.date_text)
    caption = f"*{it.title}*\n🗓 {date_str}\n\n{it.link}"

    # send with link preview on (disable_web_page_preview=False)
    await bot.send_message(
        chat_id=chat_id,
        text=caption,
        parse_mode=ParseMode.MARKDOWN,
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

async def main_loop() -> None:
    while True:
        try:
            await run_once()
        except Exception as e:
            print("error:", e)
        await asyncio.sleep(POLL_SEC)

if __name__ == "__main__":
    _silence_noise()
    asyncio.run(main_loop())
