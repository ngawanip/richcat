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

print(f"Loaded API_KEY: {API_KEY[:5]}...  BASE_URL: {BASE_URL}")

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
    payload = {"timestamp": int(time.time() * 1000), "pair": pair}
    headers = {"RST-API-KEY": API_KEY, "MSG-SIGNATURE": generate_signature(payload)}
    r = requests.get(BASE_URL + "/v3/ticker", params=payload, headers=headers)
    if r.status_code != 200:
        print(f"Ticker error for {pair}: {r.status_code} {r.text[:100]}")
        return None
    data = safe_json(r)
    if data and data.get('Success') and 'Data' in data and pair in data['Data']:
        return data['Data'][pair]
    return None

def get_balance():
    payload = {"timestamp": int(time.time() * 1000)}
    headers = {"RST-API-KEY": API_KEY, "MSG-SIGNATURE": generate_signature(payload)}
    r = requests.get(BASE_URL + "/v3/balance", params=payload, headers=headers)
    return safe_json(r)

def place_order(pair, side, quantity):
    # Try multiple endpoint variations
    endpoints = ["/v3/order", "/v3/orders"]
    payload_variants = [
        {"pair": pair, "side": side, "type": "MARKET", "quantity": quantity},
        {"symbol": pair, "side": side, "type": "MARKET", "quantity": quantity},
    ]
    for endpoint in endpoints:
        for payload in payload_variants:
            # Add timestamp and signature
            payload["timestamp"] = int(time.time() * 1000)
            headers = {"RST-API-KEY": API_KEY, "MSG-SIGNATURE": generate_signature(payload)}
            url = BASE_URL + endpoint
            print(f"Trying order: {url} with payload {payload}")
            r = requests.post(url, data=payload, headers=headers)
            print(f"  Status: {r.status_code} {r.text[:200]}")
            if r.status_code == 200:
                return safe_json(r)
            # If 200, success
            # If 404, try next
            # If 400, maybe wrong format, but still try next
    return None

def get_available_pairs():
    ex_info = get_ex_info()
    if isinstance(ex_info, dict) and 'TradePairs' in ex_info:
        pairs = list(ex_info['TradePairs'].keys())
        print(f"Found {len(pairs)} trading pairs.")
        return pairs
    print("No TradePairs found in exchange info.")
    return []

def execute_trade(pair, shares=1):
    ticker = get_ticker(pair)
    if not ticker:
        print(f"Cannot get ticker data for {pair}")
        return False
    price = ticker.get('LastPrice')
    if price is None:
        print(f"No price found in ticker data: {ticker}")
        return False
    price = float(price)

    bal = get_balance()
    usd_balance = 0.0
    if isinstance(bal, dict):
        if bal.get('Success'):
            spot = bal.get('SpotWallet')
            if spot and isinstance(spot, dict):
                usd_data = spot.get('USD')
                if usd_data:
                    usd_balance = float(usd_data.get('Free', 0))
        elif 'balances' in bal:
            for asset in bal['balances']:
                if asset.get('asset') == 'USD':
                    usd_balance = float(asset.get('free', 0))
                    break
    elif isinstance(bal, list):
        for asset in bal:
            if asset.get('asset') == 'USD':
                usd_balance = float(asset.get('free', 0))
                break
    else:
        print(f"Unexpected balance format: {bal}")
        return False

    cost = shares * price
    if usd_balance >= cost:
        print(f"Buying {shares} share(s) of {pair} @ ${price:.4f} (cost ${cost:.2f})")
        order_res = place_order(pair, "BUY", shares)
        if order_res:
            print("Trade successful")
            return True
        else:
            print("Order failed")
            return False
    else:
        print(f"Insufficient funds: need ${cost:.2f}, have ${usd_balance:.2f}")
        max_shares = int(usd_balance // price)
        if max_shares > 0:
            print(f"Trying to buy {max_shares} share(s) instead.")
            return execute_trade(pair, max_shares)
        else:
            return False

def find_best_performer(pairs):
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
                    print(f"New best: {pair} ({change*100:.2f}%)")
            except:
                pass
        time.sleep(0.2)
    return best_pair

if __name__ == '__main__':
    print("Starting bot – will buy 1 share within 1 minute")

    pairs = get_available_pairs()
    if not pairs:
        print("No pairs. Exiting.")
        exit(1)

    # Wait 1 minute
    TIMEOUT = 60
    start = time.time()
    while time.time() - start < TIMEOUT:
        remaining = int(TIMEOUT - (time.time() - start))
        print(f"Waiting {remaining} seconds before fallback...")
        time.sleep(10)

    print("Timeout reached. Falling back to best performer.")
    best = find_best_performer(pairs)
    if best:
        print(f"Best performer: {best}")
        if execute_trade(best, shares=1):
            print("Trade completed. Bot finished.")
            exit(0)
        else:
            print("Best performer trade failed.")

    print("Emergency fallback: buying first pair.")
    first = pairs[0]
    print(f"Attempting to buy {first} with quantity 1.")
    if execute_trade(first, shares=1):
        print("Trade completed. Bot finished.")
    else:
        print("All attempts failed. Check API keys and connection.")
