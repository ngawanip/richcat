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

print(f"Loaded API_KEY: {API_KEY[:5]}... SECRET: {SECRET[:5]}... BASE_URL: {BASE_URL}")

# --- API CORE FUNCTIONS ---

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

def get_server_time():
    r = requests.get(BASE_URL + "/v3/serverTime")
    return safe_json(r)

def get_ex_info():
    r = requests.get(BASE_URL + "/v3/exchangeInfo")
    return safe_json(r)

def get_ticker(pair=None):
    payload = {"timestamp": int(time.time()) * 1000}
    if pair:
        payload["pair"] = pair
    headers = {"RST-API-KEY": API_KEY, "MSG-SIGNATURE": generate_signature(payload)}
    r = requests.get(BASE_URL + "/v3/ticker", params=payload, headers=headers)
    print(f"  -> get_ticker({pair}) status: {r.status_code}")
    # print raw response if not 200 or suspicious
    if r.status_code != 200:
        print(f"  -> Response: {r.text[:200]}")
    return safe_json(r)

def get_balance():
    payload = {"timestamp": int(time.time()) * 1000}
    headers = {"RST-API-KEY": API_KEY, "MSG-SIGNATURE": generate_signature(payload)}
    r = requests.get(BASE_URL + "/v3/balance", params=payload, headers=headers)
    print(f"  -> get_balance status: {r.status_code}")
    if r.status_code != 200:
        print(f"  -> Response: {r.text[:200]}")
    return safe_json(r)

def get_klines(pair, interval="1d", limit=30):
    try:
        payload = {"pair": pair, "interval": interval, "limit": limit}
        r = requests.get(BASE_URL + "/v3/klines", params=payload, timeout=5)
        if r.status_code == 200:
            return r.json()
        else:
            print(f"  -> klines status {r.status_code} for {pair}")
            return []
    except Exception as e:
        print(f"  -> klines error: {e}")
        return []

def place_order(pair, side, quantity, price=None, order_type="MARKET"):
    payload = {
        "pair": pair,
        "side": side,
        "type": order_type,
        "quantity": quantity,
        "timestamp": int(time.time()) * 1000,
    }
    headers = {"RST-API-KEY": API_KEY, "MSG-SIGNATURE": generate_signature(payload)}
    r = requests.post(BASE_URL + "/v3/order", data=payload, headers=headers)
    print(f"  -> place_order status: {r.status_code}, response: {r.text[:200]}")
    return safe_json(r)

# --- HELPER FUNCTIONS ---

def get_available_pairs():
    ex_info = get_ex_info()
    if isinstance(ex_info, dict) and 'TradePairs' in ex_info:
        pairs = list(ex_info['TradePairs'].keys())
        print(f"Found {len(pairs)} pairs.")
        return pairs
    print("No TradePairs found in exchange info.")
    return []

def get_historical_prices(pair):
    klines = get_klines(pair, interval="1d", limit=30)
    prices = []
    if isinstance(klines, list):
        for candle in klines:
            try:
                prices.append(float(candle[4]))
            except:
                continue
    return prices

def get_todays_low(pair):
    ticker = get_ticker(pair)
    if isinstance(ticker, dict):
        low = ticker.get('lowPrice') or ticker.get('low') or ticker.get('minPrice')
        if low:
            return float(low)
    return None

def calculate_stock_statistics(prices):
    if not prices or len(prices) < 2:
        return None, None
    return statistics.mean(prices), statistics.stdev(prices)

def get_cheapest_pair(available_pairs):
    try:
        all_tickers = get_ticker()   # no pair -> expects list of tickers
        print(f"  -> get_cheapest_pair: all_tickers type = {type(all_tickers)}")
        if not isinstance(all_tickers, list):
            print(f"  -> Unexpected type, cannot get cheapest. all_tickers = {all_tickers}")
            return None, 0
        cheapest_pair = None
        min_price = float('inf')
        for t in all_tickers:
            symbol = t.get('symbol')
            if symbol in available_pairs:
                price = float(t.get('price', t.get('lastPrice', 0)))
                if 0 < price < min_price:
                    min_price = price
                    cheapest_pair = symbol
        if cheapest_pair:
            print(f"  -> Cheapest: {cheapest_pair} @ {min_price}")
        else:
            print("  -> No cheap pair found.")
        return cheapest_pair, min_price
    except Exception as e:
        print(f"  -> Error in get_cheapest_pair: {e}")
        return None, 0

# --- STRATEGY EXECUTION ---

def execute_strategy():
    print(f"\n[SCANNING] Starting Cycle: {time.strftime('%H:%M:%S')}")
    pairs = get_available_pairs()
    if not pairs:
        print("No pairs available, skipping.")
        return False
    
    lowest_risk_pair, min_std_dev, is_fallback = None, float('inf'), False
    
    # 1. Strategy Search
    for pair in pairs:
        hist = get_historical_prices(pair)
        mean_p, std_d = calculate_stock_statistics(hist)
        if std_d is not None and std_d <= 2.0 and std_d < min_std_dev:
            min_std_dev, lowest_risk_pair = std_d, pair
                
    # 2. Fallback Logic
    if not lowest_risk_pair:
        print("No low-risk pair found, using cheapest fallback.")
        lowest_risk_pair, cheapest_price = get_cheapest_pair(pairs)
        is_fallback = True
        print(f"Fallback selected: {lowest_risk_pair} at ${cheapest_price}")
        
    if not lowest_risk_pair:
        print("No pair selected, skipping.")
        return False
        
    # 3. Decision & Execution
    try:
        ticker = get_ticker(lowest_risk_pair)
        print(f"Ticker for {lowest_risk_pair}: {ticker}")
        if not isinstance(ticker, dict):
            print("Invalid ticker data, skipping.")
            return False
        curr_p = float(ticker.get('price', ticker.get('lastPrice', 0)))
        print(f"Current price: {curr_p}")
        condition_met = False
        
        if not is_fallback:
            low_p = get_todays_low(lowest_risk_pair)
            print(f"Today's low: {low_p}")
            if low_p and curr_p >= (low_p * 1.25):
                condition_met = True
                print("Condition met: price >= 1.25 * low")
            else:
                print("Condition not met.")
        else:
            condition_met = True
            print("Fallback: condition forced true.")
            
        if condition_met:
            bal = get_balance()
            print(f"Balance response: {bal}")
            avail_usd = 0.0
            if isinstance(bal, list):
                for a in bal:
                    if a.get('asset') == 'USD':
                        avail_usd = float(a.get('free', 0))
                        break
            elif isinstance(bal, dict) and 'balances' in bal:
                for a in bal['balances']:
                    if a.get('asset') == 'USD':
                        avail_usd = float(a.get('free', 0))
                        break
            else:
                print("Unexpected balance format.")
            
            print(f"Available USD: {avail_usd}")
            
            qty = 10.0
            cost = qty * curr_p
            if avail_usd >= cost:
                print(f"Attempting to buy {qty} shares of {lowest_risk_pair} at {curr_p}")
                order_res = place_order(lowest_risk_pair, "BUY", qty)
                print(f"Order result: {order_res}")
                
                # Final balance check
                final_bal = get_balance()
                final_usd = 0.0
                if isinstance(final_bal, list):
                    for fa in final_bal:
                        if fa.get('asset') == 'USD':
                            final_usd = float(fa.get('free', 0))
                            break
                elif isinstance(final_bal, dict) and 'balances' in final_bal:
                    for fa in final_bal['balances']:
                        if fa.get('asset') == 'USD':
                            final_usd = float(fa.get('free', 0))
                            break
                print(f"Remaining balance: ${final_usd:.2f}")
                print("*" * 50)
                print(f"SUCCESS: Bought {qty} shares of {lowest_risk_pair} at ${curr_p:.2f}")
                print("*" * 50)
                return True
            else:
                print(f"Insufficient funds: need ${cost:.2f}, have ${avail_usd:.2f}")
        else:
            print("Condition not met, waiting.")
    except Exception as e:
        print(f"Error during trade: {e}")
        import traceback
        traceback.print_exc()
    return False

# --- MAIN LOOP ---

if __name__ == '__main__':
    MAX_TRADES = 5
    trades_executed = 0
    
    print("Bot Active. Target: 5 Trades (10 shares each).")
    
    while trades_executed < MAX_TRADES:
        if execute_strategy():
            trades_executed += 1
            print(f"Progress: {trades_executed}/{MAX_TRADES} trades completed.")
        
        if trades_executed < MAX_TRADES:
            print("Sleeping 10 seconds...")
            time.sleep(10)
            
    print("\nTarget reached. Bot finished.")
