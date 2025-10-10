# pip install requests beautifulsoup4
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import textwrap
from datetime import datetime

URL = "https://www.bbc.com/burmese/articles/cn7636k5vpeo.lite"
HEADERS = {"User-Agent": "Mozilla/5.0"}

def fetch_article(url: str):
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # Title
    h1 = soup.find("h1")
    title = h1.get_text(" ", strip=True) if h1 else ""

    # Main body: article/tag အောက်က <p> တွေကိုပဲ ယူ
    article = soup.find("article") or soup.find("main") or soup
    # figure/aside/ad စတဲ့ non-text block တွေ မပါစေရန် filter
    paras = []
    for p in article.find_all("p"):
        # အချို့ရေးသားမှုမဟုတ်တဲ့ <p> တွေကို ပြတ်တောက်ဖို့ ဆတ်ဆတ်လတ်လတ် စစ်
        txt = p.get_text(" ", strip=True)
        if not txt:
            continue
        # "Image caption" စတဲ့ meta စာသားတွေဖြုတ်ချင်ရင် ဒီမှာ rule ထပ်တင်နိုင်
        if "အဖတ်အများဆုံး" in txt:
            continue

        paras.append(txt)

    return title, paras

def save_txt(title: str, paras: list[str], url: str, path: str = "article.txt"):
    with open(path, "w", encoding="utf-8") as f:
        f.write(title + "\n\n")
        '''
        for p in paras:
            f.write(p + "\n\n")
        
        '''
        wrapper = textwrap.TextWrapper(width=80)  # စာတန်း 80 အထိ wrap
        for p in paras:
            wrapped = wrapper.fill(p)  # စာပိုဒ်ပုံစံပြန်ပြင်
            f.write(wrapped + "\n\n")  # paragraph ချင်းတစ်လုံးခြား
        f.write(f"Source: {url}\n")
        f.write(f"Saved at: {datetime.now().isoformat(timespec='seconds')}\n")

if __name__ == "__main__":
    t, ps = fetch_article(URL)
    save_txt(t, ps, URL, "article.txt")
    print("Saved to article.txt")
