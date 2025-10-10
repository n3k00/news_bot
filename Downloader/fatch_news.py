# step10_ul_li_h2_text_all.py
import requests
from bs4 import BeautifulSoup
import re

LIVE_PAT = re.compile(r"(တိုက်ရိုက်(?:ထုတ်လွှင့်မှု|ထုတ်လွင့်မှု)?|live\b)", re.I)

url = "https://www.bbc.com/burmese.lite"  # သင် scrape ချင်တဲ့ URL
res = requests.get(url)
soup = BeautifulSoup(res.text, "html.parser")

# ul->li->h2 structure မှာ class bbc-145rmxj ပါတဲ့ h2 တွေ ရှာ
ul = soup.find("ul",class_="bbc-14jdpb9")
if not ul:
    print("Not Found")
else:
    print(len(ul.find_all("li")))
    with open("news.txt","w",encoding="utf-8") as f: 
        for li in ul.select("li"):

            #title
            h3 = li.select_one("h3")
            if not h3:
                continue
            title = h3.get_text(" ", strip=True)

            #link
            link = li.find("a")
            link = link['href'] if link and link.has_attr('href') else None

            #time
            # time (human text + machine datetime)
            t = li.find("time")
            date_text = t.get_text(strip=True) if t else ""
            date_iso = t.get("datetime", "") if t else ""

            # skip live items
            if "/live/" in (str(link) or "").lower() or LIVE_PAT.search(title) or h3.select_one("svg.first-promo"):
                continue

            f.write(title+"\n")
            f.write(str(link)+"\n")
            f.write(date_text+"\n")
            f.write(str(date_iso)+"\n\n")
    print("Successful")
