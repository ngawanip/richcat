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
    return safe_json(r)

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
        print(f"  ❌ Cannot get price for {pair}")
        return False
    price = float(ticker.get('price', ticker.get('lastPrice', 0)))
    if price == 0:
        print(f"  ❌ Invalid price for {pair}")
        return False

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
        return False

# ---------- Strategy ----------
def find_suitable_pair(pairs):
    """Find first pair where price >= 1.25 * today's low."""
    for pair in pairs:
        ticker = get_ticker(pair)
        if not ticker:
            continue
        price = float(ticker.get('price', ticker.get('lastPrice', 0)))
        low = ticker.get('lowPrice') or ticker.get('low') or ticker.get('minPrice')
        if low is None:
            continue
        low = float(low)
        if price >= low * 1.25:
            print(f"🎯 Suitable pair found: {pair} (price {price:.2f} >= {low:.2f}*1.25)")
            return pair
    return None

def find_best_performer(pairs):
    """Find pair with highest 24h price change."""
    best_pair = None
    best_change = -float('inf')
    for pair in pairs:
        ticker = get_ticker(pair)
        if not ticker:
            continue
        change = ticker.get('priceChangePercent')
        if change is not None:
            try:
                change = float(change)
                if change > best_change:
                    best_change = change
                    best_pair = pair
                    print(f"  🏆 New best: {pair} ({change:.2f}%)")
            except:
                pass
        time.sleep(0.2)  # avoid rate limits
    return best_pair

# ---------- Main ----------
if __name__ == '__main__':
    print("\n🚀 Starting bot – will buy 1 share within 2 minutes.\n")

    # 1. Get all pairs
    pairs = get_available_pairs()
    if not pairs:
        print("❌ No pairs. Exiting.")
        exit(1)

    start_time = time.time()
    TIMEOUT = 120  # seconds

    # 2. Try to find a suitable pair
    suitable = None
    while time.time() - start_time < TIMEOUT:
        suitable = find_suitable_pair(pairs)
        if suitable:
            break
        print("⏳ No suitable pair yet, waiting 10 seconds...")
        time.sleep(10)

    # 3. If found, buy it
    if suitable:
        print(f"\n✅ Suitable pair found! Buying 1 share of {suitable}")
        if execute_trade(suitable, shares=1):
            print("\n🎉 Bot finished – trade completed.")
            exit(0)
        else:
            print("\n⚠️ Trade failed, falling back to best performer.")

    # 4. Fallback: best performer
    print("\n⏰ Timeout reached or no suitable pair. Falling back to best performer.")
    best = find_best_performer(pairs)
    if best:
        print(f"🏆 Best performer: {best}")
        if execute_trade(best, shares=1):
            print("\n🎉 Bot finished – trade completed.")
            exit(0)
        else:
            print("⚠️ Best performer trade failed.")

    # 5. Emergency: first pair
    print("\n🔥 Emergency fallback: buying first available pair.")
    first = pairs[0]
    if execute_trade(first, shares=1):
        print("\n🎉 Bot finished – trade completed.")
    else:
        print("\n❌ All attempts failed. Check API keys and connection.")
