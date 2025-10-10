# extract_all_m3u8_dynamic.py
# usage:
#   pip install playwright
#   playwright install
#   python extract_all_m3u8_dynamic.py "https://celeb.cx/creator/kiri-amari-8948/videos" -o output.txt
#   # cookies/headers လိုရင် --cookie/--header ကို ထပ်ထည့်ပါ

import re, sys, json, argparse
from pathlib import Path
from playwright.sync_api import sync_playwright

def extract_m3u8(text: str) -> list[str]:
    # html/js/string အတွင်းရှိ .m3u8 URL များကို ရှာ
    urls = re.findall(r'https?://[^\s"\'<>]+?\.m3u8', text, flags=re.IGNORECASE)
    # order-preserving unique
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u); out.append(u)
    return out

def main():
    p = argparse.ArgumentParser(description="Extract .m3u8 links from a JS-rendered page.")
    p.add_argument("url", help="Target page URL")
    p.add_argument("-o", "--out", default="output.txt", help="Output txt (default: output.txt)")
    p.add_argument("--wait", type=float, default=5.0, help="Seconds to wait after load (default 5)")
    p.add_argument("--cookie", action="append", default=[], help='Cookie string like "name=value" (repeatable)')
    p.add_argument("--header", action="append", default=[], help='Extra header "Name: Value" (repeatable)')
    args = p.parse_args()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context()

        # custom headers
        if args.header:
            add_headers = {}
            for h in args.header:
                if ":" in h:
                    k, v = h.split(":", 1)
                    add_headers[k.strip()] = v.strip()
            context = browser.new_context(extra_http_headers=add_headers)

        # cookies
        if args.cookie:
            cookies = []
            for c in args.cookie:
                if "=" in c:
                    name, value = c.split("=", 1)
                    cookies.append({
                        "name": name.strip(),
                        "value": value.strip(),
                        "url": args.url
                    })
            if cookies:
                context.add_cookies(cookies)

        page = context.new_page()
        page.goto(args.url, wait_until="domcontentloaded")
        # extra wait for lazy JS render
        page.wait_for_timeout(int(args.wait * 1000))

        # 1) full HTML after render
        html = page.content()

        # 2) plus any inline JS/JSON in script tags
        scripts_text = "\n".join(page.eval_on_selector_all("script", "els => els.map(e => e.innerText || '')"))
        all_text = html + "\n" + scripts_text

        urls = extract_m3u8(all_text)

        # write
        Path(args.out).write_text("\n".join(urls), encoding="utf-8")
        print(json.dumps({"count": len(urls), "saved_to": args.out, "urls": urls}, indent=2))

        context.close()
        browser.close()

if __name__ == "__main__":
    main()


#yt-dlp -a links.txt -o "%(autonumber)05d.%(ext)s"
#python explore.py "https://celeb.cx/creator/kiri-amari-8948/videos" -o links.txt