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
    print(f"  -> Status: {r.status_code}, Text: {r.text[:500]}")
    try:
        return r.json()
    except json.JSONDecodeError as e:
        print(f"  -> JSON decode error: {e}")
        return None

def get_server_time():
    print("Calling get_server_time()...")
    r = requests.get(BASE_URL + "/v3/serverTime")
    return safe_json(r)

def get_ex_info():
    print("Calling get_ex_info()...")
    r = requests.get(BASE_URL + "/v3/exchangeInfo")
    return safe_json(r)

def get_ticker(pair=None):
    print(f"Calling get_ticker(pair={pair})...")
    payload = {}
    if pair:
        payload["pair"] = pair
    r = requests.get(BASE_URL + "/v3/ticker", params=payload)
    return safe_json(r)

def get_balance():
    print("Calling get_balance()...")
    payload = {"timestamp": int(time.time()) * 1000}
    headers = {
        "RST-API-KEY": API_KEY,
        "MSG-SIGNATURE": generate_signature(payload)
    }
    r = requests.get(BASE_URL + "/v3/balance", params=payload, headers=headers)
    return safe_json(r)

def get_klines(pair, interval="1d", limit=30):
    print(f"Calling get_klines(pair={pair}, interval={interval}, limit={limit})...")
    payload = {
        "pair": pair,
        "interval": interval,
        "limit": limit
    }
    r = requests.get(BASE_URL + "/v3/klines", params=payload)
    return safe_json(r)

def place_order(pair, side, quantity, price=None, order_type="MARKET"):
    print(f"Calling place_order(pair={pair}, side={side}, quantity={quantity}, ...)")
    payload = {
        "pair": pair,
        "side": side,
        "type": order_type,
        "quantity": quantity,
        "timestamp": int(time.time()) * 1000,
    }
    if order_type == "LIMIT" and price:
        payload["price"] = price
    headers = {
        "RST-API-KEY": API_KEY,
        "MSG-SIGNATURE": generate_signature(payload)
    }
    r = requests.post(BASE_URL + "/v3/order", data=payload, headers=headers)
    print(f"Order Response: {r.status_code} {r.text}")
    return safe_json(r)


# --- HELPER FUNCTIONS ---

def get_available_pairs():
    ex_info = get_ex_info()
    available_pairs = []
    
    # Check if ex_info is dict and contains 'TradePairs'
    if isinstance(ex_info, dict) and 'TradePairs' in ex_info:
        # TradePairs is a dict where keys are the pair names (e.g., "ZEN/USD")
        trade_pairs = ex_info['TradePairs']
        if isinstance(trade_pairs, dict):
            available_pairs = list(trade_pairs.keys())
    # Fallback for other structures (if any)
    elif isinstance(ex_info, dict) and 'symbols' in ex_info:
        available_pairs = [s.get('symbol') for s in ex_info['symbols']]
    elif isinstance(ex_info, list):
        available_pairs = [item.get('symbol') for item in ex_info if 'symbol' in item]
    
    print(f"Found {len(available_pairs)} pairs: {available_pairs}")
    return available_pairs

def get_historical_prices(pair):
    klines = get_klines(pair, interval="1d", limit=30)
    prices = []
    if isinstance(klines, list):
        for candle in klines:
            try:
                # Index 4 is Close Price
                prices.append(float(candle[4]))
            except (IndexError, ValueError, TypeError):
                continue
    return prices

def get_todays_low(pair):
    klines = get_klines(pair, interval="1d", limit=1)
    if isinstance(klines, list) and len(klines) > 0:
        try:
            # Index 3 is Low Price
            return float(klines[0][3])
        except (IndexError, ValueError, TypeError):
            pass
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
            for ticker in all_tickers:
                symbol = ticker.get('symbol', '')
                if symbol in available_pairs:
                    price = float(ticker.get('price', ticker.get('lastPrice', 0)))
                    if 0 < price < min_price:
                        min_price, cheapest_pair = price, symbol
        return cheapest_pair, min_price
    except Exception as e:
        print(f"Error finding cheapest: {e}")
        return None, 0

# --- DIAGNOSTIC TEST FUNCTION ---

def test_data_connection():
    """Confirms API connectivity and data integrity before trading."""
    print("\n" + "="*40 + "\nRUNNING DATA DIAGNOSTIC TEST\n" + "="*40)
    try:
        # Test 1: Server Time
        st = get_server_time()
        if not st:
            raise ValueError("Server time endpoint returned invalid data")
        print(f"[OK] Server Time: {st}")

        # Test 2: Available Pairs
        pairs = get_available_pairs()
        if not pairs:
            raise ValueError("No pairs found")
        print(f"[OK] Pairs found: {len(pairs)} (Sample: {pairs[0]})")

        # Test 3: Klines for first pair
        test_pair = pairs[0]
        klines = get_klines(test_pair, limit=1)
        if isinstance(klines, list) and len(klines) > 0:
            print(f"[OK] Raw Kline Sample for {test_pair}: {klines[0]}")
            print(f"     Interpretation -> Low: {klines[0][3]}, Close: {klines[0][4]}")
        else:
            # If klines failed, print the actual response to help debug
            print(f"[WARNING] Kline data for {test_pair} is not a valid list.")
            print("        This may indicate that the pair format is wrong (e.g., ZEN/USD vs ZENUSD).")
            print("        Check the API documentation or try with a different pair.")
            # We'll still continue, but trading might fail later
            print("        Diagnostic will proceed, but trading may be unreliable.")
            # Return False to stop the bot, or continue? We'll continue with caution.
            # For now, we'll return False to prevent trading.
            return False

        print("\nDIAGNOSTIC PASSED - Data is reliable.\n" + "="*40 + "\n")
        return True

    except Exception as e:
        print(f"[CRITICAL ERROR] Diagnostic failed: {e}")
        return False

# --- STRATEGY EXECUTION ---

def execute_strategy():
    print(f"\nCycle Start: {time.strftime('%H:%M:%S')}")
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
            if low_p and curr_p >= (low_p * 1.25):
                condition_met = True
        else:
            condition_met = True # Fallback buys immediately
            
        if condition_met:
            bal = get_balance()
            # Simplified balance extraction
            avail_usd = 0.0
            assets = bal if isinstance(bal, list) else bal.get('balances', [])
            for a in assets:
                if a.get('asset') == 'USD': avail_usd = float(a.get('free', 0))
            
            if avail_usd > 0:
                qty = min((avail_usd * 0.05) / curr_p, 1000.0)
                print(f"BUYING {lowest_risk_pair}: Qty {qty:.4f} @ ${curr_p}")
                place_order(lowest_risk_pair, "BUY", qty)
                return True
    except Exception as e:
        print(f"Execution Error: {e}")
    return False

# --- MAIN LOOP ---

if __name__ == '__main__':
    print("Initializing Quant Bot...")
    
    if test_data_connection():
        trades_executed = 0
        while trades_executed < 10:
            if execute_strategy():
                trades_executed += 1
                print(f"Trade Count: {trades_executed}/10")
            time.sleep(10)
    else:
        print("Bot failed to start due to data errors.")
