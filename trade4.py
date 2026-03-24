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

# --- API CORE FUNCTIONS ---

def generate_signature(params):
    query_string = '&'.join(["{}={}".format(k, params[k])
                             for k in sorted(params.keys())])
    us = SECRET.encode('utf-8')
    m = hmac.new(us, query_string.encode('utf-8'), hashlib.sha256)
    return m.hexdigest()

def safe_json(r):
    """Helper to print response and return parsed JSON or None."""
    try:
        return r.json()
    except json.JSONDecodeError:
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
    headers = {
        "RST-API-KEY": API_KEY,
        "MSG-SIGNATURE": generate_signature(payload)
    }
    r = requests.get(BASE_URL + "/v3/ticker", params=payload, headers=headers)
    return r.json()

def get_balance():
    payload = {"timestamp": int(time.time()) * 1000}
    headers = {
        "RST-API-KEY": API_KEY,
        "MSG-SIGNATURE": generate_signature(payload)
    }
    r = requests.get(BASE_URL + "/v3/balance", params=payload, headers=headers)
    return safe_json(r)

def get_klines(pair, interval="1d", limit=30):
    try:
        # Format the pair to remove the slash (e.g., "ZEN/USD" -> "ZENUSD")
        formatted_pair = pair.replace('/', '')
        
        # Changed "pair" to "symbol" in the payload, which is standard for klines
        payload = {
            "symbol": formatted_pair, 
            "interval": interval, 
            "limit": limit,
            "timestamp": int(time.time()) * 1000
        }
        
        headers = {
            "RST-API-KEY": API_KEY,
            "MSG-SIGNATURE": generate_signature(payload)
        }
        
        # Sent request with headers
        r = requests.get(BASE_URL + "/v3/kline", params=payload, headers=headers, timeout=5)
        
        # Debugging print to see the exact error text if it fails
        if r.status_code != 200:
            print(f"-> klines status {r.status_code} for {pair} | Response: {r.text}")
            
        return r.json() if r.status_code == 200 else []
    except Exception as e:
        print(f"Exception in get_klines for {pair}: {e}")
        return []

def place_order(pair, side, quantity, price=None, order_type="MARKET"):
    payload = {
        "pair": pair,
        "side": side,
        "type": order_type,
        "quantity": quantity,
        "timestamp": int(time.time()) * 1000,
    }
    headers = {
        "RST-API-KEY": API_KEY,
        "MSG-SIGNATURE": generate_signature(payload)
    }
    r = requests.post(BASE_URL + "/v3/order", data=payload, headers=headers)
    return safe_json(r)

# --- HELPER FUNCTIONS ---

def get_available_pairs():
    ex_info = get_ex_info()
    if isinstance(ex_info, dict) and 'TradePairs' in ex_info:
        return list(ex_info['TradePairs'].keys())
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
        if low: return float(low)
    return None

def calculate_stock_statistics(prices):
    if not prices or len(prices) < 2:
        return None, None
    return statistics.mean(prices), statistics.stdev(prices)

def get_cheapest_pair(available_pairs):
    try:
        all_tickers = get_ticker() 
        cheapest_pair, min_price = None, float('inf')
        if isinstance(all_tickers, list):
            for t in all_tickers:
                symbol = t.get('symbol', '')
                if symbol in available_pairs:
                    price = float(t.get('price', t.get('lastPrice', 0)))
                    if 0 < price < min_price:
                        min_price, cheapest_pair = price, symbol
        return cheapest_pair, min_price
    except:
        return None, 0

# --- STRATEGY EXECUTION ---

def execute_strategy():
    print(f"\n[SCANNING] Starting Cycle: {time.strftime('%H:%M:%S')}")
    pairs = get_available_pairs()
    if not pairs: return False
    
    lowest_risk_pair, min_std_dev, is_fallback = None, float('inf'), False
    
    # 1. Strategy Search
    for pair in pairs:
        hist = get_historical_prices(pair)
        mean_p, std_d = calculate_stock_statistics(hist)
        if std_d is not None and std_d <= 2.0 and std_d < min_std_dev:
            min_std_dev, lowest_risk_pair = std_d, pair
                
    # 2. Fallback Logic
    if not lowest_risk_pair:
        lowest_risk_pair, _ = get_cheapest_pair(pairs)
        is_fallback = True
        
    if not lowest_risk_pair: return False
        
    # 3. Decision & Execution
    try:
        ticker = get_ticker(lowest_risk_pair)
        curr_p = float(ticker.get('price', ticker.get('lastPrice', 0)))
        condition_met = False
        
        if not is_fallback:
            low_p = get_todays_low(lowest_risk_pair)
            if low_p and curr_p >= (low_p * 1.25): condition_met = True
        else:
            condition_met = True 
            
        if condition_met:
            # Check Balance before buying
            bal = get_balance()
            avail_usd = 0.0
            assets = bal if isinstance(bal, list) else bal.get('balances', [])
            for a in assets:
                if a.get('asset') == 'USD': avail_usd = float(a.get('free', 0))
            
            qty = 10.0
            cost = qty * curr_p
            
            if avail_usd >= cost:
                # PLACE THE ORDER
                order_res = place_order(lowest_risk_pair, "BUY", qty)
                
                # --- NEW: SUCCESS REPORTING ---
                print("*" * 50)
                print(f"SUCCESS: Bought {qty} shares of {lowest_risk_pair} at ${curr_p:.2f}")
                
                # Fetch final balance for confirmation
                final_bal = get_balance()
                final_usd = 0.0
                final_assets = final_bal if isinstance(final_bal, list) else final_bal.get('balances', [])
                for fa in final_assets:
                    if fa.get('asset') == 'USD': final_usd = float(fa.get('free', 0))
                
                print(f"REMAINING BALANCE: ${final_usd:.2f} USD")
                print("*" * 50)
                return True
            else:
                print(f"Skipping: Need ${cost:.2f} for {lowest_risk_pair}, but only have ${avail_usd:.2f}")
    except Exception as e:
        print(f"Error during trade: {e}")
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
            time.sleep(10)
            
    print("\nTarget reached. Bot finished.")
