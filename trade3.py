#!/usr/bin/env python
# -*- coding: utf-8 -*-

import requests
import hashlib
import hmac
import time
import json
from dotenv import load_dotenv
import os

load_dotenv()

API_KEY = os.getenv("API_KEY")
SECRET = os.getenv("SECRET")
BASE_URL = os.getenv("BASE_URL")

print(f"✅ Loaded API_KEY: {API_KEY[:5]}...  BASE_URL: {BASE_URL}")

# ---------- API Helpers ----------
def generate_signature(params):
    query_string = '&'.join(["{}={}".format(k, params[k]) for k in sorted(params.keys())])
    us = SECRET.encode('utf-8')
    m = hmac.new(us, query_string.encode('utf-8'), hashlib.sha256)
    return m.hexdigest()

def safe_json(r):
    try:
        return r.json()
    except json.JSONDecodeError:
        print(f"⚠️ JSON decode error. Status: {r.status_code}, Text: {r.text[:200]}")
        return None

def get_ex_info():
    r = requests.get(BASE_URL + "/v3/exchangeInfo")
    return safe_json(r)

def get_ticker(pair):
    payload = {"timestamp": int(time.time() * 1000), "pair": pair}
    headers = {"RST-API-KEY": API_KEY, "MSG-SIGNATURE": generate_signature(payload)}
    r = requests.get(BASE_URL + "/v3/ticker", params=payload, headers=headers)
    if r.status_code != 200:
        print(f"  ❌ Ticker error for {pair}: {r.status_code} {r.text[:100]}")
        return None
    data = safe_json(r)
    # The structure: {"Success":true, "Data": { pair : { "LastPrice": ..., "Change": ... } } }
    if data and data.get('Success') and 'Data' in data and pair in data['Data']:
        return data['Data'][pair]
    return None

def get_balance():
    payload = {"timestamp": int(time.time() * 1000)}
    headers = {"RST-API-KEY": API_KEY, "MSG-SIGNATURE": generate_signature(payload)}
    r = requests.get(BASE_URL + "/v3/balance", params=payload, headers=headers)
    return safe_json(r)

def place_order(pair, side, quantity):
    payload = {
        "pair": pair,
        "side": side,
        "type": "MARKET",
        "quantity": quantity,
        "timestamp": int(time.time() * 1000),
    }
    headers = {"RST-API-KEY": API_KEY, "MSG-SIGNATURE": generate_signature(payload)}
    r = requests.post(BASE_URL + "/v3/order", data=payload, headers=headers)
    print(f"  📡 Order response: {r.status_code} {r.text[:200]}")
    return safe_json(r)

def get_available_pairs():
    ex_info = get_ex_info()
    if isinstance(ex_info, dict) and 'TradePairs' in ex_info:
        pairs = list(ex_info['TradePairs'].keys())
        print(f"📊 Found {len(pairs)} trading pairs.")
        return pairs
    print("❌ No TradePairs found in exchange info.")
    return []

def execute_trade(pair, shares=1):
    """Buy a specific pair with given shares. Returns True if successful."""
    ticker = get_ticker(pair)
    if not ticker:
        print(f"  ❌ Cannot get ticker data for {pair}")
        return False
    price = ticker.get('LastPrice')
    if price is None:
        print(f"  ❌ No price found in ticker data: {ticker}")
        return False
    price = float(price)

    # Check balance
    bal = get_balance()
    usd_balance = 0.0
    if isinstance(bal, list):
        for asset in bal:
            if asset.get('asset') == 'USD':
                usd_balance = float(asset.get('free', 0))
                break
    elif isinstance(bal, dict) and 'balances' in bal:
        for asset in bal['balances']:
            if asset.get('asset') == 'USD':
                usd_balance = float(asset.get('free', 0))
                break
    else:
        print(f"  ❌ Unexpected balance format: {bal}")
        return False

    cost = shares * price
    if usd_balance >= cost:
        print(f"💰 Buying {shares} share(s) of {pair} @ ${price:.4f} (cost ${cost:.2f})")
        order_res = place_order(pair, "BUY", shares)
        if order_res:
            print("✅ TRADE SUCCESSFUL!")
            return True
        else:
            print("❌ Order failed.")
            return False
    else:
        print(f"  ❌ Insufficient funds: need ${cost:.2f}, have ${usd_balance:.2f}")
        # Try buying a smaller quantity if possible
        max_shares = int(usd_balance // price)
        if max_shares > 0:
            print(f"  Trying to buy {max_shares} share(s) instead.")
            return execute_trade(pair, max_shares)
        else:
            return False

def find_best_performer(pairs):
    """Find pair with highest 24h price change (Change field)."""
    best_pair = None
    best_change = -float('inf')
    for pair in pairs:
        ticker = get_ticker(pair)
        if not ticker:
            continue
        change = ticker.get('Change')
        if change is not None:
            try:
                change = float(change)
                if change > best_change:
                    best_change = change
                    best_pair = pair
                    print(f"  🏆 New best: {pair} ({change*100:.2f}%)")
            except:
                pass
        time.sleep(0.2)
    return best_pair

# ---------- Main ----------
if __name__ == '__main__':
    print("\n🚀 Starting bot – will buy 1 share within 1 minute.\n")

    # 1. Get all pairs
    pairs = get_available_pairs()
    if not pairs:
        print("❌ No pairs. Exiting.")
        exit(1)

    start_time = time.time()
    TIMEOUT = 60  # seconds

    # 2. Wait up to 1 minute, then fallback to best performer
    while time.time() - start_time < TIMEOUT:
        # We can optionally look for a suitable pair, but with no low price we skip.
        # Instead, we just wait and then do fallback.
        print(f"⏳ Waiting for fallback ({int(TIMEOUT - (time.time()-start_time))}s left)...")
        time.sleep(10)

    # 3. Fallback: best performer
    print("\n⏰ Timeout reached. Falling back to best performer (highest 24h change).")
    best = find_best_performer(pairs)
    if best:
        print(f"🏆 Best performer: {best}")
        if execute_trade(best, shares=1):
            print("\n🎉 Bot finished – trade completed.")
            exit(0)
        else:
            print("⚠️ Best performer trade failed.")

    # 4. Emergency: first pair
    print("\n🔥 Emergency fallback: buying first available pair.")
    first = pairs[0]
    print(f"📡 Attempting to buy {first} with quantity 1.")
    if execute_trade(first, shares=1):
        print("\n🎉 Bot finished – trade completed.")
    else:
        print("\n❌ All attempts failed. Check API keys and connection.")
