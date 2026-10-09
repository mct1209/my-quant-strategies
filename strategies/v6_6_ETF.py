#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
============================================================================================
TPE90 V6.6 TW ALL-ASSET SIGNAL GENERATOR (GITHUB ACTIONS OPTIMIZED)
============================================================================================
"""

import os
import re
import sys
import time
import datetime
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import requests
import yfinance as yf

warnings.filterwarnings("ignore")

# ============================================================
# CONFIGURATION & ENVIRONMENT
# ============================================================

VERSION = "TPE90 V6.6 TW ALL-ASSET QUANT & SIGNAL ENGINE"

# 雲端執行輸出目錄 (專案內 results 資料夾)
OUTPUT_DIR = os.path.join(os.getcwd(), "results")

# 透過環境變數取得篩選模式 (預設 ALL: 顯示 BUY / WATCH / SELL)
# 可選模式: "ALL", "BUY", "WATCH", "SELL"
FILTER_MODE = os.environ.get("FILTER_MODE", "ALL").upper()

MAX_WORKERS = 4
REQUEST_TIMEOUT = 12

MIN_BARS = 180
HISTORY_PERIOD = "2y"

MARKET_TICKERS = ["0050.TW", "^TWII"]

# Breakthrough & Filter Rules
BREAKOUT_LOOKBACK = 20
VOL_MIN = 1.30
VOL_MAX = 3.50
RSI_MIN = 52
RSI_MAX = 68
BIAS_BUY_MAX = 4.00
RETURN_5D_MAX = 5.00

CLOSE_POSITION_MIN = 0.65
UPPER_SHADOW_MAX = 0.30

ATR_PERIOD = 14
ATR_STOP_MULT = 1.80
TARGET_R = 2.00
MAX_HOLD_DAYS = 12

BUY_SCORE_MIN = 80
WATCH_SCORE_MIN = 70

# Asset Selection Switches
INCLUDE_LEVERAGED_ETF = False

# ============================================================
# UTILITIES & NETWORK
# ============================================================

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
})

def clean_text(x):
    return re.sub(r"\s+", " ", str(x).replace("\xa0", " ")).strip()

def valid_code(code):
    code = clean_text(code)
    return bool(re.fullmatch(r"\d{4,6}[A-Z]?", code))

def calculate_atr(df, period=14):
    prev_close = df["Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()

def calculate_rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    ag = gain.ewm(alpha=1 / period, adjust=False).mean()
    al = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = ag / al.replace(0, np.nan)
    return 100 - 100 / (1 + rs)

def prepare_indicators(df):
    df = df.copy().sort_index()
    df["MA5"] = df["Close"].rolling(5).mean()
    df["MA20"] = df["Close"].rolling(20).mean()
    df["MA60"] = df["Close"].rolling(60).mean()
    df["MA120"] = df["Close"].rolling(120).mean()

    df["ATR"] = calculate_atr(df, ATR_PERIOD)
    df["RSI"] = calculate_rsi(df["Close"], 14)

    df["VOL_MA20"] = df["Volume"].rolling(20).mean()
    df["VOL_RATIO"] = df["Volume"] / df["VOL_MA20"]

    df["HIGH_LOOKBACK_PREV"] = df["High"].rolling(BREAKOUT_LOOKBACK).max().shift(1)

    df["RET5"] = df["Close"].pct_change(5) * 100
    df["BIAS20"] = (df["Close"] / df["MA20"] - 1) * 100

    return df

# ============================================================
# FULL TW UNIVERSE FETCHING (TWSE + TPEX + ETF)
# ============================================================

LEVERAGED_WORDS = ["槓桿", "反向", "兩倍", "2X", "3X", "反1", "正2", "正向2", "多2", "空2"]
BOND_WORDS = ["債", "債券", "公司債", "公債", "高收益債", "投資級債", "美債"]
FOREIGN_WORDS = ["美國", "美股", "標普", "S&P", "NASDAQ", "那斯達克", "道瓊", "日本", "韓國", "越南", "中國", "香港", "半導體", "費城"]
ETF_HINTS = ["ETF", "指數", "基金", "高股息", "債", "原油", "黃金", "科技"]

def is_etf_like(code, name):
    code, name = clean_text(code).upper(), clean_text(name).upper()
    if re.fullmatch(r"0\d{4,5}[A-Z]?", code):
        return True
    if any(w.upper() in name for w in ETF_HINTS) and len(code) >= 5:
        return True
    return False

def classify_etf(name):
    s = clean_text(name).upper()
    if any(w.upper() in s for w in LEVERAGED_WORDS):
        return "LEVERAGED"
    if any(w.upper() in s for w in BOND_WORDS):
        return "TW_ETF_BOND"
    if any(w.upper() in s for w in FOREIGN_WORDS):
        return "TW_ETF_FOREIGN"
    return "TW_ETF_DOMESTIC"

def fetch_universe():
    print("[全宇宙掃描] 啟動證交所 (TWSE) 與櫃買中心 (TPEx) 全市場清單抓取...")
    urls = [
        ("https://openapi.twse.com.tw/v1/opendata/t187ap03_L?TYPEK=正股,ETF", "TWSE"),
        ("https://openapi.twse.com.tw/v1/opendata/t187ap03_L", "TWSE"),
        ("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O", "TPEX")
    ]

    unique = {}
    for url, market in urls:
        try:
            r = SESSION.get(url, timeout=REQUEST_TIMEOUT)
            if r.status_code == 200:
                for row in r.json():
                    c = row.get("公司代號") or row.get("證券代號") or row.get("SecuritiesCompanyCode") or row.get("Code")
                    n = row.get("公司名稱") or row.get("公司簡稱") or row.get("證券名稱") or row.get("CompanyName")
                    if c and n and valid_code(c):
                        c_str = clean_text(c)
                        n_str = clean_text(n)
                        if c_str not in unique:
                            unique[c_str] = (c_str, n_str, market)
        except Exception:
            continue

    records = []
    for code, name, market in unique.values():
        if len(code) == 4 and not is_etf_like(code, name):
            asset_type = "TW_STOCK"
        elif is_etf_like(code, name):
            asset_type = classify_etf(name)
        else:
            continue

        if asset_type == "LEVERAGED" and not INCLUDE_LEVERAGED_ETF:
            continue
        if any(x in name for x in ["認購", "認售", "權證", "ETN"]):
            continue

        records.append({
            "代碼": code,
            "名稱": name,
            "市場": market,
            "資產類型": asset_type,
            "Yahoo": f"{code}.TW" if market == "TWSE" else f"{code}.TWO",
        })

    df = pd.DataFrame(records).drop_duplicates("代碼")
    df = df.sort_values(["資產類型", "代碼"]).reset_index(drop=True)
    return df

def download_history(ticker):
    try:
        df = yf.download(ticker, period=HISTORY_PERIOD, interval="1d", progress=False, threads=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
        if len(df) < MIN_BARS:
            return None
        return prepare_indicators(df)
    except Exception:
        return None

# ============================================================
# QUANT EVALUATION & DAILY SIGNAL SCAN
# ============================================================

def evaluate_signal(df, i, market_ok=True, allow_watch=True):
    if i < 120: return None
    r = df.iloc[i]

    close, op, high, low = float(r["Close"]), float(r["Open"]), float(r["High"]), float(r["Low"])
    atr_v, ma20, ma60, ma120 = float(r["ATR"]), float(r["MA20"]), float(r["MA60"]), float(r["MA120"])
    rsi_v, vol_ratio = float(r["RSI"]), float(r["VOL_RATIO"])
    high_prev, ret5, bias20 = float(r["HIGH_LOOKBACK_PREV"]), float(r["RET5"]), float(r["BIAS20"])

    day_range = high - low
    if day_range <= 0 or atr_v <= 0: return None

    close_pos = (close - low) / day_range
    upper_shadow = (high - max(op, close)) / day_range
    breakout_atr = (close - high_prev) / atr_v if atr_v > 0 else 0

    if not market_ok: return None
    if not (close > ma20 and ma20 > ma60): return None
    if not (close >= high_prev and breakout_atr >= 0.20): return None
    if bias20 > BIAS_BUY_MAX or ret5 > RETURN_5D_MAX: return None
    if not (VOL_MIN <= vol_ratio <= VOL_MAX and RSI_MIN <= rsi_v <= RSI_MAX): return None
    if close_pos < CLOSE_POSITION_MIN or upper_shadow > UPPER_SHADOW_MAX: return None

    score = 70
    if ma20 > ma60 > ma120: score += 10
    if breakout_atr >= 0.40: score += 8
    if 55 <= rsi_v <= 63: score += 6
    if 1.5 <= vol_ratio <= 2.5: score += 6

    stop = close - ATR_STOP_MULT * atr_v
    risk = close - stop
    target = close + TARGET_R * risk
    rr = (target - close) / risk if risk > 0 else 0

    if rr < 1.8: return None

    status = "BUY" if score >= BUY_SCORE_MIN else ("WATCH" if allow_watch and score >= WATCH_SCORE_MIN else None)
    if not status: return None

    return {
        "status": status, "score": score, "close": close, "RSI": rsi_v,
        "VOL_RATIO": vol_ratio, "MA20_BIAS": bias20, "RET5": ret5,
        "stop": stop, "target": target, "RR": rr
    }

def scan_daily_signals(record, market_ok):
    df = download_history(record["Yahoo"])
    if df is None or df.empty:
        return None

    last_idx = len(df) - 1
    info = evaluate_signal(df, last_idx, market_ok=market_ok, allow_watch=True)

    latest = df.iloc[last_idx]
    prev = df.iloc[last_idx - 1]
    is_sell = (latest["Close"] < latest["MA5"]) and (prev["Close"] >= prev["MA5"])

    if not info and not is_sell:
        return None

    raw_status = "NONE"
    signal_type = "無"
    if info:
        raw_status = info["status"]
        signal_type = f"🔥 {info['status']}"
    elif is_sell:
        raw_status = "SELL"
        signal_type = "⚠️ SELL (平倉/減碼)"

    return {
        "代碼": record["代碼"],
        "名稱": record["名稱"],
        "市場": record["市場"],
        "資產類型": record["資產類型"],
        "raw_status": raw_status,
        "訊號": signal_type,
        "綜合分數": info["score"] if info else "-",
        "最新收盤": round(latest["Close"], 2),
        "量能倍數": round(latest["VOL_RATIO"], 2) if "VOL_RATIO" in latest else "-",
        "MA20乖離%": round(latest["BIAS20"], 2) if "BIAS20" in latest else "-",
        "建議買進價": round(info["close"], 2) if info else "-",
        "建議停損價": round(info["stop"], 2) if info else "-",
        "目標獲利價": round(info["target"], 2) if info else "-",
        "操作建議": "T+1 開盤市價執行；若開盤 Gap > +2% 或 < -1.5% 則取消" if info else "建議觸發平倉條件，停利/平倉觀望"
    }

# ============================================================
# EXPORT & SAVE RESULTS
# ============================================================

def save_results(active_signals, market_ok):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d")
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 根據過濾模式篩選
    filtered_signals = []
    for s in active_signals:
        raw = s.get("raw_status", "")
        if FILTER_MODE == "BUY" and raw == "BUY":
            filtered_signals.append(s)
        elif FILTER_MODE == "WATCH" and raw == "WATCH":
            filtered_signals.append(s)
        elif FILTER_MODE == "SELL" and raw == "SELL":
            filtered_signals.append(s)
        elif FILTER_MODE == "ALL":
            filtered_signals.append(s)

    sig_df = pd.DataFrame(filtered_signals)
    if not sig_df.empty and "raw_status" in sig_df.columns:
        sig_df = sig_df.drop(columns=["raw_status"])

    # 輸出 CSV 至 results/ 目錄
    sig_csv = os.path.join(OUTPUT_DIR, f"tpe90_v66_{FILTER_MODE.lower()}_{timestamp}.csv")
    latest_csv = os.path.join(OUTPUT_DIR, "tpe90_v66_latest.csv")

    if not sig_df.empty:
        sig_df.to_csv(sig_csv, index=False, encoding="utf-8-sig")
        sig_df.to_csv(latest_csv, index=False, encoding="utf-8-sig")
    else:
        empty_df = pd.DataFrame([{"說明": f"今日無符合 {FILTER_MODE} 條件之訊號"}])
        empty_df.to_csv(sig_csv, index=False, encoding="utf-8-sig")
        empty_df.to_csv(latest_csv, index=False, encoding="utf-8-sig")

    print(f"\n[完成] 策略 TPE90 V6.6 掃描完畢 (模式: {FILTER_MODE})，結果已寫入 {latest_csv}")

# ============================================================
# MAIN EXECUTOR
# ============================================================

def main():
    print(f"=== 啟動 {VERSION} ===")
    print(f"當前指定過濾模式: {FILTER_MODE}")

    # 1. 大盤環境評估
    mkt_df = download_history("0050.TW")
    mkt_ok = False
    if mkt_df is not None:
        r = mkt_df.iloc[-1]
        mkt_ok = (r["Close"] > r["MA20"]) and (r["MA20"] > r["MA60"])
        print(f"[0050 大盤濾網] 最新收盤: {r['Close']:.2f} | MA20: {r['MA20']:.2f} | 狀態: {'允許做多' if mkt_ok else '防禦觀望'}")

    # 2. 獲取全台股與 ETF 清單
    universe_df = fetch_universe()
    total_count = len(universe_df)
    print(f"成功加載全市場標的：共 {total_count} 檔，開始多線程即時訊號掃描...")

    records = universe_df.to_dict("records")
    active_signals = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(scan_daily_signals, r, mkt_ok) for r in records]
        for f in as_completed(futures):
            res = f.result()
            if res:
                active_signals.append(res)

    save_results(active_signals, mkt_ok)

if __name__ == "__main__":
    main()