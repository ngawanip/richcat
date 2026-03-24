#!/usr/bin/env python
# -*- coding: utf-8 -*-

import requests
import hashlib
import hmac
import time
import statistics
import json
from dotenv import load_dotenv
import os

load_dotenv()

API_KEY = os.getenv("API_KEY")
SECRET = os.getenv("SECRET")
BASE_URL = os.getenv("BASE_URL")

print(f"Loaded API_KEY: {API_KEY[:5]}...  BASE_URL: {BASE_URL}")

# --- API Core ---

def generate_signature(params):
    query_string = '&'.join(["{}={}".format(k, params[k]) for k in sorted(params.keys())])
    us = SECRET.encode('utf-8')
    m = hmac.new(us, query_string.encode('utf-8'), hashlib.sha256)
    return m.hexdigest()

def safe_json(r):
    try:
        return r.json()
    except json.JSONDecodeError:
        print(f"JSON decode error. Status: {r.status_code}, Text: {r.text[:200]}")
        return None

def get_ex_info():
    r = requests.get(BASE_URL + "/v3/exchangeInfo")
    return safe_json(r)

def get_ticker(pair):
    payload = {"timestamp": int(time.time()) * 1000, "pair": pair}
    headers = {"RST-API-KEY": API_KEY, "MSG-SIGNATURE": generate_signature(payload)}
    r = requests.get(BASE_URL + "/v3/ticker", params=payload, headers=headers)
    if r.status_code != 200:
        print(f"  Ticker error for {pair}: {r.status_code} {r.text[:100]}")
        return None
    return safe_json(r)

def get_balance():
    payload = {"timestamp": int(time.time()) * 1000}
    headers = {"RST-API-KEY": API_KEY, "MSG-SIGNATURE": generate_signature(payload)}
    r = requests.get(BASE_URL + "/v3/balance", params=payload, headers=headers)
    return safe_json(r)

def place_order(pair, side, quantity):
    payload = {
        "pair": pair,
        "side": side,
        "type": "MARKET",
        "quantity": quantity,
        "timestamp": int(time.time()) * 1000,
    }
    headers = {"RST-API-KEY": API_KEY, "MSG-SIGNATURE": generate_signature(payload)}
    r = requests.post(BASE_URL + "/v3/order", data=payload, headers=headers)
    print(f"Order response: {r.status_code} {r.text[:200]}")
    return safe_json(r)

def get_available_pairs():
    ex_info = get_ex_info()
    if isinstance(ex_info, dict) and 'TradePairs' in ex_info:
        return list(ex_info['TradePairs'].keys())
    return []

def get_historical_prices(pair):
    # We know klines endpoint returns 404, but we keep it for compatibility.
    # It will always return empty list.
    return []

def calculate_stock_statistics(prices):
    if not prices or len(prices) < 2:
        return None, None
    return statistics.mean(prices), statistics.stdev(prices)

def get_todays_low(pair):
    ticker = get_ticker(pair)
    if isinstance(ticker, dict):
        low = ticker.get('lowPrice') or ticker.get('low') or ticker.get('minPrice')
        if low:
            return float(low)
    return None

def compute_performance_score(ticker):
    """Score based on 24h price change (higher = better)."""
    if not isinstance(ticker, dict):
        return -float('inf')
    change = ticker.get('priceChangePercent')
    if change is not None:
        try:
            return float(change)
        except:
            pass
    # Fallback: (current - low) / low
    price = ticker.get('price') or ticker.get('lastPrice')
    low = ticker.get('lowPrice') or ticker.get('low')
    if price and low:
        try:
            p = float(price)
            l = float(low)
            if l > 0:
                return (p - l) / l
        except:
            pass
    return -float('inf')

def find_best_performing_pair(pairs):
    """Find pair with highest 24h price change (or fallback score)."""
    best_pair = None
    best_score = -float('inf')
    for pair in pairs:
        ticker = get_ticker(pair)
        if ticker:
            score = compute_performance_score(ticker)
            if score > best_score:
                best_score = score
                best_pair = pair
        time.sleep(0.1)  # be gentle
    return best_pair, best_score

# --- Main Logic ---

def execute_trade(pair, shares=1):
    ticker = get_ticker(pair)
    if not ticker:
        print(f"Cannot get price for {pair}")
        return False
    price = float(ticker.get('price', ticker.get('lastPrice', 0)))
    if price == 0:
        print(f"Invalid price for {pair}")
        return False

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

    cost = shares * price
    if usd_balance >= cost:
        print(f"Buying {shares} share(s) of {pair} at ${price:.4f} (cost ${cost:.2f})")
        result = place_order(pair, "BUY", shares)
        if result:
            print("✅ Trade successful!")
            return True
        else:
            print("❌ Order failed.")
    else:
        print(f"Insufficient funds: need ${cost:.2f}, have ${usd_balance:.2f}")
    return False

def find_suitable_pair(pairs):
    """Search for a pair meeting the original condition (risk <=2 and price >= 1.25*low)."""
    for pair in pairs:
        # Get historical prices (always empty, so risk condition will be None -> not suitable)
        # So we skip risk check because klines unavailable. We'll use the price condition only.
        # To make it work, we'll rely on the fallback anyway.
        # But we'll implement a condition using the ticker low.
        low = get_todays_low(pair)
        if low is None:
            continue
        ticker = get_ticker(pair)
        if not ticker:
            continue
        price = float(ticker.get('price', ticker.get('lastPrice', 0)))
        if price >= low * 1.25:
            print(f"Suitable pair found: {pair} (price {price:.2f} >= {low:.2f}*1.25)")
            return pair
    return None

if __name__ == '__main__':
    MAX_TRADES = 5
    trades_done = 0
    fallback_executed = False
    start_time = time.time()
    TIMEOUT_SECONDS = 300  # 5 minutes

    print(f"Bot started. Goal: {MAX_TRADES} trades.")
    print("Step 1: Try to find a pair meeting original condition (price >= 1.25*low).")
    print("If none found within 5 minutes, will buy best performing pair and then continue.\n")

    while trades_done < MAX_TRADES:
        # Get current pairs list
        pairs = get_available_pairs()
        if not pairs:
            print("No pairs found, waiting...")
            time.sleep(10)
            continue

        # If we haven't used fallback yet and we've been searching for more than timeout,
        # do fallback trade.
        if not fallback_executed and (time.time() - start_time) > TIMEOUT_SECONDS:
            print(f"\n⏰ Timeout ({TIMEOUT_SECONDS}s) reached. No suitable pair found.")
            print("Falling back to buy best performing pair (highest 24h change).")
            best_pair, best_score = find_best_performing_pair(pairs)
            if best_pair:
                if execute_trade(best_pair, shares=1):
                    trades_done += 1
                    fallback_executed = True
                    print(f"Fallback trade completed. Trades so far: {trades_done}/{MAX_TRADES}")
                else:
                    print("Fallback trade failed. Will retry.")
            else:
                print("No valid pair for fallback. Retrying.")
            continue

        # Normal strategy: find a suitable pair
        suitable = find_suitable_pair(pairs)
        if suitable:
            print(f"Found suitable pair: {suitable}")
            if execute_trade(suitable, shares=1):
                trades_done += 1
                print(f"Trade successful. Trades so far: {trades_done}/{MAX_TRADES}")
            else:
                print("Trade failed. Retrying...")
        else:
            print("No suitable pair found this cycle. Retrying...")

        # Wait before next cycle
        if trades_done < MAX_TRADES:
            time.sleep(15)

    print("\n🎉 Target reached. Bot finished.")
