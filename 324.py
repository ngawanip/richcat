#!/usr/bin/env python
# -*- coding: utf-8 -*-

import requests
import hashlib
import hmac
import time
import statistics

from dotenv import load_dotenv
import os

load_dotenv()

API_KEY = os.getenv("API_KEY")
SECRET = os.getenv("SECRET")
BASE_URL = os.getenv("BASE_URL")

def generate_signature(params):
    query_string = '&'.join(["{}={}".format(k, params[k])
                             for k in sorted(params.keys())])
    us = SECRET.encode('utf-8')
    m = hmac.new(us, query_string.encode('utf-8'), hashlib.sha256)
    return m.hexdigest()

def get_server_time():
    r = requests.get(BASE_URL + "/v3/serverTime")
    return r.json()

def get_ex_info():
    r = requests.get(BASE_URL + "/v3/exchangeInfo")
    return r.json()

def get_ticker(pair=None):
    payload = {}
    if pair:
        payload["pair"] = pair
    r = requests.get(
        BASE_URL + "/v3/ticker",
        params=payload,
    )
    return r.json()

def get_balance():
    payload = {
        "timestamp": int(time.time()) * 1000,
    }
    r = requests.get(
        BASE_URL + "/v3/balance",
        params=payload,
        headers={"RST-API-KEY": API_KEY,
             "MSG-SIGNATURE": generate_signature(payload)}
    )
    return r.json()

def get_klines(pair, interval="1d", limit=30):
    payload = {
        "pair": pair,
        "interval": interval,
        "limit": limit
    }
    r = requests.get(BASE_URL + "/v3/klines", params=payload)
    return r.json()

def place_order(pair, side, quantity, price=None, order_type="MARKET"):
    payload = {
        "pair": pair,
        "side": side,
        "type": order_type,
        "quantity": quantity,
        "timestamp": int(time.time()) * 1000,
    }
    if order_type == "LIMIT" and price:
        payload["price"] = price
        
    r = requests.post(
        BASE_URL + "/v3/order",
        data=payload,
        headers={"RST-API-KEY": API_KEY,
             "MSG-SIGNATURE": generate_signature(payload)}
    )
    print(f"Order Response: {r.status_code} {r.text}")
    return r.json()

def get_available_pairs():
    ex_info = get_ex_info()
    available_pairs = []
    if 'symbols' in ex_info:
        for symbol_data in ex_info['symbols']:
            available_pairs.append(symbol_data.get('symbol', ''))
    elif type(ex_info) == list:
        available_pairs = [item.get('symbol') for item in ex_info if 'symbol' in item]
    return available_pairs

def get_historical_prices(pair):
    klines = get_klines(pair, interval="1d", limit=30)
    prices = []
    if isinstance(klines, list) and len(klines) > 0:
        for candle in klines:
            try:
                # Index 4 is typically the Close price in OHLCV format
                close_price = float(candle[4])
                prices.append(close_price)
            except (IndexError, ValueError):
                continue
    return prices

def get_todays_low(pair):
    """Fetches the lowest price of the current day for a given pair."""
    klines = get_klines(pair, interval="1d", limit=1)
    if isinstance(klines, list) and len(klines) > 0:
        try:
            return float(klines[0][3])
        except (IndexError, ValueError):
            pass
    return None

def calculate_stock_statistics(prices):
    if not prices or len(prices) < 2:
        return None, None
    mean_price = statistics.mean(prices)
    std_dev = statistics.stdev(prices)
    return mean_price, std_dev

def get_cheapest_pair(available_pairs):
    """Fetches all tickers at once and returns the pair with the absolute lowest price."""
    try:
        all_tickers = get_ticker() 
        cheapest_pair = None
        min_price = float('inf')
        
        if isinstance(all_tickers, list):
            for ticker in all_tickers:
                symbol = ticker.get('symbol', '')
                if symbol in available_pairs:
                    price = float(ticker.get('price', ticker.get('lastPrice', 0)))
                    if 0 < price < min_price:
                        min_price = price
                        cheapest_pair = symbol
        return cheapest_pair, min_price
    except Exception as e:
        print(f"Error fetching cheapest pair: {e}")
        return None, 0

def execute_strategy():
    """
    Executes the trading strategy. 
    Returns True if a trade was successfully placed, False otherwise.
    """
    print("\n" + "="*40)
    print(f"Executing Strategy Cycle at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*40)
    
    pairs = get_available_pairs()
    if not pairs:
        print("No pairs found. Skipping this cycle.")
        return False
        
    print(f"Found {len(pairs)} trading pairs on the exchange. Evaluating risk data...")
    
    lowest_risk_pair = None
    min_std_dev = float('inf')
    is_fallback = False
    
    # 1. Primary Strategy: Find lowest risk pair
    for pair in pairs:
        historical_prices = get_historical_prices(pair)
        
        # DEBUG PRINT: Show what data is being pulled for each pair
        if not historical_prices:
            print(f"  [DEBUG] {pair}: No historical data found.")
            continue
            
        mean_price, std_dev = calculate_stock_statistics(historical_prices)
        
        if std_dev is not None:
            # DEBUG PRINT: Show the calculated math
            print(f"  [DEBUG] {pair} | Data Points: {len(historical_prices)} | Mean Price: ${mean_price:.4f} | Risk (StdDev): {std_dev:.4f}")
            
            if std_dev <= 2.0 and std_dev < min_std_dev:
                min_std_dev = std_dev
                lowest_risk_pair = pair
                
    print("-" * 40) # Visual separator
                
    # 2. Fallback Condition: Find the cheapest stock
    if not lowest_risk_pair:
        print("No pairs found with a risk (StdDev) <= 2. Activating fallback: Finding the cheapest stock...")
        lowest_risk_pair, fallback_price = get_cheapest_pair(pairs)
        
        if not lowest_risk_pair:
            print("Failed to find a fallback stock. Skipping cycle.")
            return False
            
        print(f"=> Fallback Strategy: Selected Cheapest Pair: {lowest_risk_pair} at ${fallback_price:.4f}")
        is_fallback = True
    else:
        print(f"=> TARGET ACQUIRED: Selected Pair: {lowest_risk_pair} (StdDev: {min_std_dev:.2f} <= 2.0)")
        
    # 3. Execution Logic
    try:
        ticker_data = get_ticker(lowest_risk_pair)
        current_price = float(ticker_data.get('price', ticker_data.get('lastPrice', 0)))
        
        if current_price <= 0:
            print(f"Failed to fetch a valid price for {lowest_risk_pair}. Skipping cycle.")
            return False

        condition_met = False
        
        if not is_fallback:
            todays_low = get_todays_low(lowest_risk_pair)
            if todays_low is None:
                print(f"Failed to fetch today's low for {lowest_risk_pair}. Skipping cycle.")
                return False
                
            buy_threshold = todays_low * 1.25
            print(f"  [EVALUATING TRADE] Pair: {lowest_risk_pair} | Current Price: ${current_price:.2f} | Today's Low: ${todays_low:.2f} | Buy Threshold (1.25x): ${buy_threshold:.2f}")
            
            if current_price >= buy_threshold:
                print(f"  >>> CONDITION MET! Current price (${current_price:.2f}) has crossed the 1.25x low threshold (${buy_threshold:.2f}).")
                condition_met = True
            else:
                print("  >>> CONDITION NOT MET. Price has not surged 25% above today's low. Waiting for next cycle.")
        else:
            print(f"  [EVALUATING TRADE] Fallback execution proceeding to buy {lowest_risk_pair} at ${current_price:.4f}...")
            condition_met = True
            
        # 4. Buy Logic
        if condition_met:
            balance_data = get_balance()
            available_usd = 0.0
            
            if isinstance(balance_data, list):
                for asset in balance_data:
                    if asset.get('asset') == 'USD': 
                        available_usd = float(asset.get('free', 0.0))
                        break
            elif isinstance(balance_data, dict) and 'balances' in balance_data:
                for asset in balance_data['balances']:
                    if asset.get('asset') == 'USD':
                        available_usd = float(asset.get('free', 0.0))
                        break
                        
            if available_usd <= 0:
                print("Insufficient USD balance to place an order.")
                return False
                
            investment_amount = available_usd * 0.05
            calculated_quantity = investment_amount / current_price
            
            quantity_to_buy = min(calculated_quantity, 1000.0)
            
            print(f"  >>> EXECUTING BUY: Allocating ${investment_amount:.2f} to buy {quantity_to_buy:.6f} shares of {lowest_risk_pair}")
            place_order(lowest_risk_pair, "BUY", quantity_to_buy, order_type="MARKET")
            print("Order placement command sent successfully!")
            return True 
            
        return False
            
    except Exception as e:
        print(f"Error fetching ticker or placing order: {e}")
        return False

if __name__ == '__main__':
    print("Starting Continuous Quant Bot...")
    WAIT_TIME_SECONDS = 10
    MAX_TRADES = 10
    trades_executed = 0
    
    while trades_executed < MAX_TRADES:
        try:
            trade_made = execute_strategy()
            if trade_made:
                trades_executed += 1
                print(f"*** Total Trades Executed: {trades_executed} / {MAX_TRADES} ***")
                
            if trades_executed >= MAX_TRADES:
                print(f"\nTarget of {MAX_TRADES} trades reached. Stopping the quant bot.")
                break
                
        except Exception as e:
            print(f"An unexpected error occurred in the main loop: {e}")
            
        print(f"\nSleeping for {WAIT_TIME_SECONDS} seconds before the next check...")
        time.sleep(WAIT_TIME_SECONDS)
