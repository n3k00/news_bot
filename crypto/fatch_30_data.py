import ccxt
import pandas as pd
import time
from datetime import datetime, timedelta

# --- Parameters များကို သတ်မှတ်ခြင်း ---
SYMBOL = 'TON/USDT'     # လေ့လာလိုသော Coin
TIMEFRAME = '1h'        # 1-hour K-line
DAYS_TO_FETCH = 30      # လွန်ခဲ့သော ရက် ၃၀ စာ ဒေတာ

# --- Exchange Object ကို စတင်တည်ဆောက်ခြင်း ---
# Binance API ကို အသုံးပြုမည်။ (ccxt သည် အခြား Exchange များကိုလည်း ပံ့ပိုးသည်)
exchange = ccxt.binance()

def fetch_data(symbol, timeframe, days):
    """
    သတ်မှတ်ထားသော Exchange မှ K-line (OHLCV) ဒေတာများကို ဆွဲထုတ်ခြင်း
    """
    
    # 30 ရက်စာအတွက် လိုအပ်သော နာရီအရေအတွက်ကို တွက်ချက်ခြင်း
    limit = days * 24
    
    print(f"Fetching {limit} bars of {symbol} on {timeframe}...")

    # Data ဆွဲထုတ်မည့် အချိန်စမှတ်ကို တွက်ချက်ခြင်း (လွန်ခဲ့သော ၃၀ ရက်)
    # ccxt API သည် milliseconds ဖြင့် အလုပ်လုပ်သည်
    since = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)

    ohlcv = []
    
    # API rate limits များကြောင့် တစ်ခါတည်း အများကြီးမဆွဲဘဲ ခွဲဆွဲရန် လိုအပ်နိုင်သော်လည်း 
    # ဒီ code မှာတော့ လွယ်ကူစေရန် တစ်ကြိမ်တည်း ဆွဲထုတ်ထားသည်
    
    try:
        # fetch_ohlcv() method ဖြင့် ဒေတာဆွဲထုတ်ခြင်း
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
    except Exception as e:
        print(f"Error fetching data: {e}")
        return None

    # Pandas DataFrame အဖြစ် ပြောင်းလဲခြင်း
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    # timestamp ကို ဖတ်လို့ရတဲ့ Date/Time format အဖြစ် ပြောင်းလဲခြင်း
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    
    # timestamp ကို Index အဖြစ် သတ်မှတ်ခြင်း
    df.set_index('timestamp', inplace=True)
    
    return df

# --- Data ဆွဲထုတ်ပြီး DataFrame အား ပြသခြင်း ---
ton_data = fetch_data(SYMBOL, TIMEFRAME, DAYS_TO_FETCH)

if ton_data is not None:
    print("\n--- Data Fetching အောင်မြင်ပါသည် ---")
    print(ton_data.head()) # ပထမဆုံး အချက် ၅ ခုကို ပြသ
    print(f"\nစုစုပေါင်း Row အရေအတွက်: {len(ton_data)}")
    print(f"Index စတင်ချိန်: {ton_data.index.min()}")
    print(f"Index ပြီးဆုံးချိန်: {ton_data.index.max()}")