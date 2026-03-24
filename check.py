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


def safe_json(r):
    """Helper to print response and return JSON or None."""
    print(f"  -> Status: {r.status_code}, Text: {r.text[:500]}")
    try:
        return r.json()
    except Exception as e:
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
    print(f"Calling place_order(pair={pair}, side={side}, quantity={quantity}, price={price}, order_type={order_type})...")
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
    print(f"  -> Order Response: {r.status_code} {r.text}")
    return safe_json(r)


# ------------------------------------------------------------------
# Strategy functions (unchanged except added debug prints)
# ------------------------------------------------------------------

def get_available_pairs():
    print("Fetching available trading pairs...")
    ex_info = get_ex_info()
    if ex_info is None:
        print("get_ex_info returned None, aborting.")
        return []
    available_pairs = []
    if isinstance(ex_info, dict) and 'TradePairs' in ex_info:
        trade_pairs = ex_info['TradePairs']
        if isinstance(trade_pairs, dict):
            available_pairs = list(trade_pairs.keys())
    elif isinstance(ex_info, dict) and 'symbols' in ex_info:
        available_pairs = [s.get('symbol') for s in ex_info['symbols']]
    elif isinstance(ex_info, list):
        available_pairs = [item.get('symbol') for item in ex_info if 'symbol' in item]
    print(f"Found {len(available_pairs)} pairs: {available_pairs[:10]}...")
    return available_pairs


def get_historical_prices(pair):
    print(f"Getting historical prices for {pair}...")
    klines = get_klines(pair, interval="1d", limit=30)
    if not isinstance(klines, list):
        print(f"  -> klines not a list, got {type(klines)}")
        return []
    prices = []
    for candle in klines:
        try:
            close_price = float(candle[4])
            prices.append(close_price)
        except (IndexError, ValueError):
            continue
    print(f"  -> Retrieved {len(prices)} price points")
    return prices


def calculate_stock_statistics(prices):
    if not prices or len(prices) < 2:
        return None, None
    mean_price = statistics.mean(prices)
    std_dev = statistics.stdev(prices)
    return mean_price, std_dev


def get_todays_low(pair):
    print(f"Getting today's low for {pair}...")
    klines = get_klines(pair, interval="1d", limit=1)
    if isinstance(klines, list) and len(klines) > 0:
        try:
            low = float(klines[0][3])   # low price index
            print(f"  -> Today's low: {low}")
            return low
        except (IndexError, ValueError):
            pass
    print("  -> Could not retrieve today's low")
    return None


def execute_strategy():
    print("\n" + "="*40)
    print(f"Executing Strategy Cycle at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*40)

    pairs = get_available_pairs()
    if not pairs:
        print("No pairs found. Skipping this cycle.")
        return

    # Find the pair with the lowest risk (std dev) among those with std dev <= 2
    lowest_risk_pair = None
    min_std_dev = float('inf')
    for pair in pairs:
        historical_prices = get_historical_prices(pair)
        _, std_dev = calculate_stock_statistics(historical_prices)
        if std_dev is not None:
            if std_dev <= 2.0 and std_dev < min_std_dev:
                min_std_dev = std_dev
                lowest_risk_pair = pair

    if not lowest_risk_pair:
        print("No pairs found with risk (StdDev) <= 2. Skipping cycle.")
        return

    print(f"=> Selected Pair: {lowest_risk_pair} (StdDev: {min_std_dev:.2f})")

    try:
        ticker_data = get_ticker(lowest_risk_pair)
        if not isinstance(ticker_data, dict):
            print("Ticker data invalid, skipping cycle.")
            return
        current_price = float(ticker_data.get('price', ticker_data.get('lastPrice', 0)))
        todays_low = get_todays_low(lowest_risk_pair)
        if current_price == 0 or todays_low is None:
            print("Failed to fetch valid pricing data. Skipping cycle.")
            return

        buy_threshold = todays_low * 1.25
        print(f"Current Price: {current_price:.2f} | Today's Low: {todays_low:.2f} | Buy Threshold: {buy_threshold:.2f}")

        if current_price >= buy_threshold:
            print(f"Condition Met! Current price ({current_price:.2f}) is >= the 1.25x low threshold ({buy_threshold:.2f}).")
            balance_data = get_balance()
            if balance_data is None:
                print("Balance data invalid, cannot trade.")
                return

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
            else:
                investment_amount = available_usd * 0.05
                quantity_to_buy = investment_amount / current_price
                print(f"Allocating 5% of balance (${investment_amount:.2f}) to buy {quantity_to_buy:.6f} {lowest_risk_pair}")
                place_order(lowest_risk_pair, "BUY", quantity_to_buy, order_type="MARKET")
                print("Order placement attempted!")
        else:
            print("Condition NOT met. Price has not surged 25% above today's low. Waiting for next cycle.")

    except Exception as e:
        print(f"Error in strategy execution: {e}")


if __name__ == '__main__':
    print("Starting Continuous Quant Bot (DEBUG MODE)...")
    WAIT_TIME_SECONDS = 10
    while True:
        try:
            execute_strategy()
        except Exception as e:
            print(f"An unexpected error occurred in the main loop: {e}")
        print(f"\nSleeping for {WAIT_TIME_SECONDS} seconds before the next check...")
        time.sleep(WAIT_TIME_SECONDS)
