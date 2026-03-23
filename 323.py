 
 
#!/usr/bin/env python
# -*- coding: utf-8 -*-

import requests
import hashlib
import hmac
import time
import statistics

# Your Round 1 Competition API credentials
API_KEY = "l5zxW7pvWVSsyIOwu6rgovXKgcDGZDpr8RMfKTazfUnKsMthXhfMPEJHk5Q7IKjW"
SECRET = "9eSzPePYg47FcD6KkrWWSGZPIrErWer0tPyKzIG1qg1NB6hcLGkBeFZYciPLkrOQ"

BASE_URL = "https://mock-api.roostoo.com"


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
    print(f"Exchange Info Response: {r.status_code} {r.text[:500]}")  # Debug
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
    """
    Fetches historical candlestick (kline) data for a given pair.
    """
    payload = {
        "pair": pair,
        "interval": interval,
        "limit": limit
    }
    r = requests.get(BASE_URL + "/v3/klines", params=payload)
    return r.json()


def place_order(pair, side, quantity, price=None, order_type="MARKET"):
    """
    Places a buy or sell order.
    side: "BUY" or "SELL"
    order_type: "MARKET" or "LIMIT"
    """
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


# ==========================================
# FUNCTIONS FOR QUANT TRADING COMPETITION
# ==========================================

def get_available_pairs():
    print("Fetching available trading pairs...")
    ex_info = get_ex_info()
    
    available_pairs = []
    if 'symbols' in ex_info:
        for symbol_data in ex_info['symbols']:
            available_pairs.append(symbol_data.get('symbol', ''))
    elif type(ex_info) == list:
        available_pairs = [item.get('symbol') for item in ex_info if 'symbol' in item]
        
    print(f"Found {len(available_pairs)} pairs.")
    return available_pairs


def get_historical_prices(pair):
    """
    Fetches real historical closing prices from the API.
    """
    klines = get_klines(pair, interval="1d", limit=30)
    prices = []
    
    # Assuming standard Binance/Roostoo format: 
    # [ [Open time, Open, High, Low, Close, Volume, ...], ... ]
    if isinstance(klines, list) and len(klines) > 0:
        for candle in klines:
            try:
                # Index 4 is usually the closing price
                close_price = float(candle[4])
                prices.append(close_price)
            except (IndexError, ValueError):
                continue
                
    return prices


def calculate_stock_statistics(prices):
    if not prices or len(prices) < 2:
        return None, None

    mean_price = statistics.mean(prices)
    std_dev = statistics.stdev(prices)
    
    return mean_price, std_dev


if __name__ == '__main__':
    print("--- V2 Strategy Execution ---")
    
    # 1. Find all available stocks/pairs
    pairs = get_available_pairs()
    if not pairs:
        print("No pairs found. Exiting.")
        exit()
    
    # 2. Find the stock with the minimum risk
    lowest_risk_pair = None
    min_std_dev = float('inf')
    target_mean = 0
    
    print("\n--- Analyzing Risk for All Pairs ---")
    for pair in pairs:
        historical_prices = get_historical_prices(pair)
        mean, std_dev = calculate_stock_statistics(historical_prices)
        
        if std_dev is not None:
            print(f"{pair} -> Mean: {mean:.2f}, Risk (StdDev): {std_dev:.2f}")
            if std_dev < min_std_dev:
                min_std_dev = std_dev
                lowest_risk_pair = pair
                target_mean = mean

    if not lowest_risk_pair:
        print("Could not calculate risk for any pairs. Exiting.")
        exit()

    print(f"\n=> Selected Pair with Minimum Risk: {lowest_risk_pair} (Risk: {min_std_dev:.2f})")
    
    # 3. Check if current price is lower than the mean
    try:
        ticker_data = get_ticker(lowest_risk_pair)
        current_price = float(ticker_data.get('price', ticker_data.get('lastPrice', 0)))
        
        if current_price == 0:
            print("Failed to fetch a valid current price from the API. Exiting.")
            exit()
            
        print(f"Current Price of {lowest_risk_pair}: {current_price:.2f} | Historical Mean: {target_mean:.2f}")
        
        if current_price < target_mean:
            print(f"Condition Met! Current price ({current_price:.2f}) is lower than mean ({target_mean:.2f}).")
            
            # 4. Buy 5% of available balance
            balance_data = get_balance()
            available_usd = 0.0
            
            # Parse the actual balance data. Adjust 'USD' to 'USDT' if your competition uses Tether.
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
            else:
                investment_amount = available_usd * 0.05
                quantity_to_buy = investment_amount / current_price
                
                print(f"Allocating 5% of balance (${investment_amount:.2f}) to buy {quantity_to_buy:.6f} {lowest_risk_pair}")
                
                # Execute the order
                place_order(lowest_risk_pair, "BUY", quantity_to_buy, order_type="MARKET")
                print("Order placement attempted!")
            
        else:
            print("Condition NOT met. Current price is higher than or equal to the mean. No action taken.")
            
    except Exception as e:
        print(f"Error fetching ticker or placing order: {e}")