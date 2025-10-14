import requests

url = "https://burmese.dvb.no/wp-json/wp/v2/posts?per_page=10&_fields=id,link,date,title,content"

# စစ်ဆေးမှု ပိုများတဲ့ website တွေအတွက် header တွေကို ပိုဖြည့်ပေးခြင်း
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.60 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'DNT': '1', # Do Not Track request
    'Connection': 'keep-alive',
    # Referer ကို dvb.no ရဲ့ ပင်မ စာမျက်နှာ ထည့်ပေးခြင်း
    'Referer': 'https://burmese.dvb.no/' 
}

try:
    response = requests.get(url, headers=headers, timeout=10)
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        print("Successful!")
    elif response.status_code == 403:
        print("Still Forbidden (403). Check IP or Firewall rules.")

except requests.exceptions.RequestException as e:
    print(f"An error occurred: {e}")