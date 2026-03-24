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

def place_order_trial(pair, side, quantity):
    """Try multiple endpoint and parameter combinations."""
    # List of possible endpoints (relative to BASE_URL)
    endpoints = [
        "/v3/order",
        "/v3/orders",
        "/v3/order/place",
        "/v3/trade",
        "/v3/trade/place",
        "/api/v3/order",
        "/api/v3/orders",
    ]
    # Parameter sets (field names)
    param_sets = [
        {"pair": pair, "side": side, "type": "MARKET", "quantity": quantity},
        {"symbol": pair, "side": side, "type": "MARKET", "quantity": quantity},
        {"market": pair, "side": side, "type": "MARKET", "amount": quantity},
        {"pair": pair, "side": side, "orderType": "MARKET", "quantity": quantity},
        {"symbol": pair, "side": side, "orderType": "MARKET", "quantity": quantity},
    ]
    # Also try with pair without slash (e.g., ZENUSD)
    pair_no_slash = pair.replace('/', '')
    param_sets_no_slash = [
        {"pair": pair_no_slash, "side": side, "type": "MARKET", "quantity": quantity},
        {"symbol": pair_no_slash, "side": side, "type": "MARKET", "quantity": quantity},
    ]
    all_param_sets = param_sets + param_sets_no_slash

    for endpoint in endpoints:
        for params in all_param_sets:
            # Add timestamp
            payload = params.copy()
            payload["timestamp"] = int(time.time() * 1000)
            headers = {"RST-API-KEY": API_KEY, "MSG-SIGNATURE": generate_signature(payload)}
            url = BASE_URL + endpoint
            # Try POST with form-encoded data
            try:
                print(f"Trying: POST {url} with data {payload}")
                r = requests.post(url, data=payload, headers=headers)
                print(f"  Status: {r.status_code} {r.text[:200]}")
                if r.status_code == 200:
                    return safe_json(r)
            except Exception as e:
                print(f"  Exception: {e}")
            # Also try POST with JSON body
            try:
                print(f"Trying: POST {url} with json {payload}")
                r = requests.post(url, json=payload, headers=headers)
                print(f"  Status: {r.status_code} {r.text[:200]}")
                if r.status_code == 200:
                    return safe_json(r)
            except Exception as e:
                print(f"  Exception: {e}")
    return None

def get_cheapest_pair(pairs):
    cheapest = None
    min_price = float('inf')
    for pair in pairs:
        ticker = get_ticker(pair)
        if not ticker:
            continue
        price = ticker.get('LastPrice')
        if price is None:
            continue
        price = float(price)
        if price < min_price:
            min_price = price
            cheapest = pair
            print(f"New cheapest: {pair} @ ${price:.4f}")
        time.sleep(0.2)
    return cheapest, min_price

if __name__ == '__main__':
    print("Bot started – will buy 1 share of the cheapest pair immediately.")

    # 1. Get all pairs
    ex_info = get_ex_info()
    if not ex_info or 'TradePairs' not in ex_info:
        print("Could not get exchange info. Exiting.")
        exit(1)
    pairs = list(ex_info['TradePairs'].keys())
    print(f"Found {len(pairs)} pairs.")

    # 2. Find cheapest pair
    cheapest, price = get_cheapest_pair(pairs)
    if not cheapest:
        print("Could not determine cheapest pair. Exiting.")
        exit(1)
    print(f"Cheapest pair: {cheapest} @ ${price:.4f}")

    # 3. Check balance
    bal = get_balance()
    if not bal or not bal.get('Success'):
        print("Balance check failed.")
        exit(1)
    spot = bal.get('SpotWallet', {})
    usd_balance = float(spot.get('USD', {}).get('Free', 0))
    print(f"USD balance: ${usd_balance:.2f}")

    # 4. Buy 1 share
    cost = price * 1
    if usd_balance < cost:
        print(f"Insufficient funds: need ${cost:.2f}, have ${usd_balance:.2f}")
        exit(1)

    print(f"Attempting to buy 1 share of {cheapest} at ${price:.4f}...")
    order_res = place_order_trial(cheapest, "BUY", 1)
    if order_res:
        print("Order successful!")
        print("Response:", order_res)
    else:
        print("All order attempts failed. Check API documentation.")
