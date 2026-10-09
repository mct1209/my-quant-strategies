#!/usr/bin/env python3
# -*- coding: utf-8 -*-

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

# =============================================================================
# CONFIG & ENVIRONMENT ARGS
# =============================================================================

VERSION = "TPE90 V3.10 AUTO-UNIVERSE MULTI-ASSET"

# 雲端執行輸出目錄 (專案內 results 資料夾)
OUTPUT_DIR = os.path.join(os.cwd() if hasattr(os, 'cwd') else os.getcwd(), "results")

# 透過環境變數取得篩選模式 (預設 ALL: 代表顯示 BUY 與 WATCH)
# 可選模式: "BUY", "WATCH", "ALL"
FILTER_MODE = os.environ.get("FILTER_MODE", "ALL").upper()

MAX_WORKERS = 4
REQUEST_TIMEOUT = 15
MIN_BARS = 180
DOWNLOAD_PERIOD = "2y"

# ---------------------------------------------------------------------
# Strategy Parameters
# ---------------------------------------------------------------------

BUY_SCORE_MIN = 94
WATCH_SCORE_MIN = 82
BREAKOUT_LOOKBACK = 20

STOP_MIN_PCT = 2.0
STOP_MAX_PCT = 3.2
TARGET_R = 2.50
ATR_PERIOD = 14

BIAS_BUY_MAX = 4.5
BIAS_HARD_MAX = 6.0
RET5_MAX = 5.0
RET10_MAX = 8.0

RSI_MIN = 50
RSI_MAX = 68
RSI_OVERHEAT = 70
ADX_MIN = 18

VOL_MIN = 1.20
VOL_MAX = 3.00
VOL_HARD_MAX = 3.50

UPPER_SHADOW_MAX = 0.35
CLOSE_POSITION_MIN = 0.65

# ---------------------------------------------------------------------
# Universe Settings
# ---------------------------------------------------------------------

INCLUDE_TW_STOCK = True
INCLUDE_TW_ETF = True
INCLUDE_US_ETF = True

US_ETF_CANDIDATES = [
    # Broad Market
    ("SPY", "SPDR S&P 500 ETF"),
    ("VOO", "Vanguard S&P 500 ETF"),
    ("IVV", "iShares Core S&P 500 ETF"),
    ("VTI", "Vanguard Total Stock Market ETF"),
    ("QQQ", "Invesco QQQ"),
    ("DIA", "SPDR Dow Jones Industrial Average ETF"),
    ("IWM", "iShares Russell 2000 ETF"),

    # Nasdaq / Growth
    ("QQQM", "Invesco NASDAQ 100 ETF"),
    ("SCHG", "Schwab US Large-Cap Growth ETF"),
    ("VUG", "Vanguard Growth ETF"),
    ("MGK", "Vanguard Mega Cap Growth ETF"),

    # Dividend
    ("SCHD", "Schwab US Dividend Equity ETF"),
    ("VYM", "Vanguard High Dividend Yield ETF"),
    ("DGRO", "iShares Core Dividend Growth ETF"),
    ("HDV", "iShares Core High Dividend ETF"),

    # Technology
    ("XLK", "Technology Select Sector SPDR Fund"),
    ("VGT", "Vanguard Information Technology ETF"),
    ("SOXX", "iShares Semiconductor ETF"),
    ("SMH", "VanEck Semiconductor ETF"),
    ("IGV", "iShares Expanded Tech-Software ETF"),

    # Financial
    ("XLF", "Financial Select Sector SPDR Fund"),
    ("KRE", "SPDR S&P Regional Banking ETF"),

    # Healthcare
    ("XLV", "Health Care Select Sector SPDR Fund"),
    ("IBB", "iShares Biotechnology ETF"),

    # Energy
    ("XLE", "Energy Select Sector SPDR Fund"),
    ("XOP", "SPDR S&P Oil & Gas Exploration ETF"),

    # Industrial
    ("XLI", "Industrial Select Sector SPDR Fund"),

    # Consumer
    ("XLY", "Consumer Discretionary Select Sector SPDR Fund"),
    ("XLP", "Consumer Staples Select Sector SPDR Fund"),

    # Real Estate
    ("XLRE", "Real Estate Select Sector SPDR Fund"),

    # Bonds
    ("TLT", "iShares 20+ Year Treasury Bond ETF"),
    ("IEF", "iShares 7-10 Year Treasury Bond ETF"),
    ("SHY", "iShares 1-3 Year Treasury Bond ETF"),
    ("BND", "Vanguard Total Bond Market ETF"),
    ("AGG", "iShares Core U.S. Aggregate Bond ETF"),

    # Gold / Commodity
    ("GLD", "SPDR Gold Shares"),
    ("IAU", "iShares Gold Trust"),
    ("SLV", "iShares Silver Trust"),
    ("DBC", "Invesco DB Commodity Index Tracking Fund"),

    # International
    ("VEA", "Vanguard FTSE Developed Markets ETF"),
    ("VWO", "Vanguard FTSE Emerging Markets ETF"),
    ("VXUS", "Vanguard Total International Stock ETF"),
    ("EFA", "iShares MSCI EAFE ETF"),
    ("EEM", "iShares MSCI Emerging Markets ETF"),

    # Japan / Europe
    ("EWJ", "iShares MSCI Japan ETF"),
    ("EWG", "iShares MSCI Germany ETF"),
    ("EWU", "iShares MSCI United Kingdom ETF"),

    # China
    ("MCHI", "iShares MSCI China ETF"),
    ("FXI", "iShares China Large-Cap ETF"),

    # Clean Energy
    ("ICLN", "iShares Global Clean Energy ETF"),

    # AI / Innovation
    ("ARKK", "ARK Innovation ETF"),
    ("BOTZ", "Global X Robotics & Artificial Intelligence ETF"),
    ("AIQ", "Global X Artificial Intelligence & Technology ETF"),
]

# =============================================================================
# HTTP SESSION & HELPERS
# =============================================================================

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,*/*",
    }
)

def safe_float(x, default=np.nan):
    try:
        if pd.isna(x):
            return default
        return float(x)
    except Exception:
        return default

def normalize_code(x):
    if x is None:
        return ""
    x = str(x).strip()
    return x.replace(".0", "")

PRICE_ALIASES = {
    "open": "Open",
    "high": "High",
    "low": "Low",
    "close": "Close",
    "adj close": "Adj Close",
    "adjclose": "Adj Close",
    "volume": "Volume",
}

def flatten_yf_columns(df):
    if df is None or df.empty:
        return df
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        chosen = 0
        for level in range(df.columns.nlevels):
            values = [str(v).strip().lower() for v in df.columns.get_level_values(level)]
            hits = sum(v in PRICE_ALIASES for v in values)
            if hits >= 3:
                chosen = level
                break
        df.columns = [str(v) for v in df.columns.get_level_values(chosen)]

    rename = {}
    for c in df.columns:
        key = str(c).strip().lower().replace("_", " ")
        if key in PRICE_ALIASES:
            rename[c] = PRICE_ALIASES[key]

    if rename:
        df = df.rename(columns=rename)

    if df.columns.duplicated().any():
        df = df.loc[:, ~df.columns.duplicated(keep="first")]

    return df

# =============================================================================
# TECHNICAL INDICATORS
# =============================================================================

def calculate_atr(df, period=14):
    prev_close = df["Close"].shift(1)
    tr = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - prev_close).abs(),
            (df["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()

def calculate_rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def calculate_macd(close):
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    return macd, signal, hist

def calculate_adx(df, period=14):
    high, low, close = df["High"], df["Low"], df["Close"]
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=df.index,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=df.index,
    )

    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)

    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / period, adjust=False).mean()
    return adx, plus_di, minus_di

def prepare_indicators(df):
    df = df.copy()
    df["MA20"] = df["Close"].rolling(20).mean()
    df["MA60"] = df["Close"].rolling(60).mean()
    df["MA120"] = df["Close"].rolling(120).mean()

    df["MA20_SLOPE"] = (df["MA20"] / df["MA20"].shift(5) - 1) * 100
    df["MA60_SLOPE"] = (df["MA60"] / df["MA60"].shift(10) - 1) * 100

    df["ATR"] = calculate_atr(df, ATR_PERIOD)
    df["ATR_PCT"] = (df["ATR"] / df["Close"]) * 100
    df["RSI"] = calculate_rsi(df["Close"], 14)

    df["MACD"], df["MACD_SIGNAL"], df["MACD_HIST"] = calculate_macd(df["Close"])
    df["ADX"], df["PLUS_DI"], df["MINUS_DI"] = calculate_adx(df, 14)

    df["VOL_MA20"] = df["Volume"].rolling(20).mean()
    df["VOL_RATIO"] = df["Volume"] / df["VOL_MA20"]

    df["HIGH20_PREV"] = df["High"].rolling(BREAKOUT_LOOKBACK).max().shift(1)
    df["HIGH60_PREV"] = df["High"].rolling(60).max().shift(1)
    df["HIGH120_PREV"] = df["High"].rolling(120).max().shift(1)

    df["BIAS20"] = (df["Close"] / df["MA20"] - 1) * 100
    df["RET5"] = (df["Close"] / df["Close"].shift(5) - 1) * 100
    df["RET10"] = (df["Close"] / df["Close"].shift(10) - 1) * 100

    return df

# =============================================================================
# SIGNAL EVALUATION
# =============================================================================

def evaluate_signal(df, i, market_ok=True):
    if i < 130:
        return None

    row = df.iloc[i]
    required = [
        "Open", "High", "Low", "Close", "Volume",
        "MA20", "MA60", "MA20_SLOPE", "MA60_SLOPE",
        "ATR", "RSI", "MACD", "MACD_SIGNAL", "MACD_HIST",
        "ADX", "PLUS_DI", "MINUS_DI", "VOL_RATIO",
        "HIGH20_PREV", "HIGH60_PREV", "HIGH120_PREV",
        "BIAS20", "RET5", "RET10",
    ]

    for c in required:
        if pd.isna(row[c]):
            return None

    close = float(row["Close"])
    open_p = float(row["Open"])
    high = float(row["High"])
    low = float(row["Low"])
    volume = float(row["Volume"])

    ma20 = float(row["MA20"])
    ma60 = float(row["MA60"])
    atr = float(row["ATR"])
    rsi = float(row["RSI"])

    macd = float(row["MACD"])
    macd_signal = float(row["MACD_SIGNAL"])
    macd_hist = float(row["MACD_HIST"])

    adx = float(row["ADX"])
    plus_di = float(row["PLUS_DI"])
    minus_di = float(row["MINUS_DI"])

    vol_ratio = float(row["VOL_RATIO"])
    high20 = float(row["HIGH20_PREV"])
    high60 = float(row["HIGH60_PREV"])
    high120 = float(row["HIGH120_PREV"])

    bias20 = float(row["BIAS20"])
    ret5 = float(row["RET5"])
    ret10 = float(row["RET10"])

    breakout20 = close > high20
    breakout60 = close > high60

    if not breakout20:
        return None

    # Trend
    trend_score = 0
    if close > ma20: trend_score += 10
    if ma20 > ma60: trend_score += 10
    if float(row["MA20_SLOPE"]) > 0: trend_score += 5
    if float(row["MA60_SLOPE"]) > 0: trend_score += 5

    # Momentum
    momentum_score = 0
    if RSI_MIN <= rsi <= RSI_MAX: momentum_score += 8
    if macd > macd_signal: momentum_score += 7
    if macd_hist > 0: momentum_score += 5
    if plus_di > minus_di: momentum_score += 3
    if adx >= ADX_MIN: momentum_score += 2

    # Volume
    flow_score = 0
    if VOL_MIN <= vol_ratio <= VOL_MAX: flow_score += 10
    elif 1.0 <= vol_ratio < VOL_MIN: flow_score += 4
    if vol_ratio <= VOL_HARD_MAX: flow_score += 3
    if volume > float(df["Volume"].rolling(5).mean().iloc[i]): flow_score += 3
    if close > open_p: flow_score += 4

    # Candle
    candle_score = 0
    total_range = high - low
    if total_range <= 0: return None

    upper_shadow = high - max(open_p, close)
    upper_shadow_ratio = upper_shadow / total_range
    close_position = (close - low) / total_range

    if upper_shadow_ratio <= UPPER_SHADOW_MAX: candle_score += 7
    if close_position >= CLOSE_POSITION_MIN: candle_score += 8

    # Position
    high120_distance = (close / high120 - 1) * 100
    position_score = 5 if -10 <= high120_distance <= 0 else 2

    # Anti Chase
    anti_chase = True
    if bias20 > BIAS_HARD_MAX or bias20 > BIAS_BUY_MAX or ret5 > RET5_MAX or ret10 > RET10_MAX:
        anti_chase = False
    if rsi > RSI_OVERHEAT:
        return None

    # False Breakout
    false_breakout = False
    false_reasons = []
    if close_position < 0.55:
        false_breakout = True
        false_reasons.append("WEAK_CLOSE")
    if upper_shadow_ratio > 0.45:
        false_breakout = True
        false_reasons.append("LONG_UPPER_SHADOW")
    if vol_ratio > VOL_HARD_MAX:
        false_breakout = True
        false_reasons.append("VOLUME_CLIMAX")
    if rsi > 72:
        false_breakout = True
        false_reasons.append("RSI_OVERHEAT")

    breakout_distance = (close / high20 - 1) * 100
    if breakout_distance > 4.0:
        false_breakout = True
        false_reasons.append("BREAKOUT_TOO_FAR")

    if not market_ok:
        return None

    # Score Calculation
    score = trend_score + momentum_score + flow_score + candle_score + position_score
    if breakout60: score += 8
    if bias20 <= 3: score += 5
    if 55 <= rsi <= 64: score += 3
    if ret5 <= 3: score += 3

    # Risk Control
    atr_stop_pct = (atr / close * 100 * 1.25)
    stop_pct = min(max(atr_stop_pct, STOP_MIN_PCT), STOP_MAX_PCT)
    stop_loss = close * (1 - stop_pct / 100)
    risk = close - stop_loss
    if risk <= 0: return None
    target = close + TARGET_R * risk
    rr = (target - close) / risk

    # Status Judgement
    if false_breakout: status = "WATCH"
    elif score >= BUY_SCORE_MIN and anti_chase: status = "BUY"
    elif score >= WATCH_SCORE_MIN: status = "WATCH"
    else: return None

    reasons = []
    if breakout20: reasons.append("BREAKOUT20")
    if breakout60: reasons.append("BREAKOUT60")
    if close > ma20: reasons.append("ABOVE_MA20")
    if ma20 > ma60: reasons.append("MA20_GT_MA60")
    if float(row["MA60_SLOPE"]) > 0: reasons.append("MA60_UP")
    if RSI_MIN <= rsi <= RSI_MAX: reasons.append("RSI_OK")
    if macd > macd_signal: reasons.append("MACD_BULL")
    if macd_hist > 0: reasons.append("MACD_HIST_POS")
    if adx >= ADX_MIN: reasons.append("ADX_OK")
    if plus_di > minus_di: reasons.append("DI_PLUS")
    if VOL_MIN <= vol_ratio <= VOL_MAX: reasons.append("VOL_CONFIRM")
    if close_position >= CLOSE_POSITION_MIN: reasons.append("STRONG_CLOSE")
    if upper_shadow_ratio <= UPPER_SHADOW_MAX: reasons.append("NO_LONG_SHADOW")
    if bias20 <= 3: reasons.append("LOW_CHASE")
    if ret5 <= RET5_MAX: reasons.append("RET5_OK")
    if breakout60: reasons.append("60D_CONFIRM")
    if false_breakout: reasons.append("FALSE_BREAKOUT_RISK")

    return {
        "status": status,
        "score": round(score, 2),
        "close": round(close, 2),
        "RSI": round(rsi, 2),
        "ADX": round(adx, 2),
        "VOL_RATIO": round(vol_ratio, 2),
        "MA20_BIAS": round(bias20, 2),
        "RET5": round(ret5, 2),
        "RET10": round(ret10, 2),
        "ATR_PCT": round(float(row["ATR_PCT"]), 2),
        "HIGH120_DISTANCE": round(high120_distance, 2),
        "stop": round(stop_loss, 2),
        "target": round(target, 2),
        "RR": round(rr, 2),
        "anti_chase": anti_chase,
        "false_breakout": false_breakout,
        "false_reason": "|".join(false_reasons),
        "reason": "|".join(reasons),
    }

# =============================================================================
# DATA FETCHING & UNIVERSE
# =============================================================================

def download_history(ticker):
    for attempt in range(3):
        try:
            df = yf.download(
                ticker,
                period=DOWNLOAD_PERIOD,
                interval="1d",
                auto_adjust=False,
                progress=False,
                threads=False,
            )
            df = flatten_yf_columns(df)

            if df is None or df.empty:
                time.sleep(0.5)
                continue

            need = ["Open", "High", "Low", "Close", "Volume"]
            if any(c not in df.columns for c in need):
                return None, "missing_ohlcv"

            df = df[need].copy()
            for c in need:
                df[c] = pd.to_numeric(df[c], errors="coerce")

            df = df.dropna(subset=["Open", "High", "Low", "Close"])

            if len(df) < MIN_BARS:
                return None, "too_short"

            df = prepare_indicators(df)
            return df, "ok"

        except Exception as e:
            if attempt == 2:
                return None, f"error:{e}"
            time.sleep(0.8)

    return None, "download_failed"

def market_filter():
    df, status = download_history("0050.TW")
    if df is None:
        print("[0050] 無法取得大盤 ETF，預設暫停做多。")
        return False

    last = df.iloc[-1]
    close = float(last["Close"])
    ma20 = float(last["MA20"])
    ma60 = float(last["MA60"])
    slope60 = float(last["MA60_SLOPE"])

    ok = close > ma20 and ma20 > ma60 and slope60 > 0
    print(f"[0050] Close={close:.2f} MA20={ma20:.2f} MA60={ma60:.2f} MA60Slope={slope60:.2f}%")
    print("目前大盤：允許做多" if ok else "目前大盤：防禦模式")
    return ok

def get_twse_universe():
    stocks, etfs = [], []
    url = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
    try:
        r = SESSION.get(url, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            for x in data:
                code = normalize_code(x.get("公司代號", x.get("有價證券代號", "")))
                name = str(x.get("公司名稱", x.get("有價證券名稱", ""))).strip()
                if len(code) != 4 or not code.isdigit():
                    continue
                security_type = str(x.get("有價證券種類", x.get("證券種類", "")))
                if "ETF" in security_type.upper():
                    etfs.append((code + ".TW", name, "TW_ETF"))
                else:
                    stocks.append((code + ".TW", name, "TW_STOCK"))
    except Exception as e:
        print(f"[TWSE OpenAPI 失敗，改用 ISIN 備援]: {e}")
        return get_twse_isin_fallback()

    return stocks, etfs

def get_twse_isin_fallback():
    stocks, etfs = [], []
    urls = [
        "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2",
        "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4",
    ]
    for url in urls:
        try:
            r = SESSION.get(url, timeout=REQUEST_TIMEOUT)
            r.encoding = "big5"
            tables = pd.read_html(r.text)
            if not tables:
                continue
            df = tables[0]
            for _, row in df.iterrows():
                text = " ".join(str(v) for v in row.tolist())
                m = re.search(r"\b(\d{4,6})\b", text)
                if not m:
                    continue
                code = m.group(1)
                if len(code) != 4:
                    continue
                parts = text.split()
                if len(parts) < 2:
                    continue
                name = parts[1]
                if "ETF" in text.upper():
                    etfs.append((code + ".TW", name, "TW_ETF"))
                else:
                    stocks.append((code + ".TW", name, "TW_STOCK"))
        except Exception as e:
            print(f"[TWSE fallback error]: {e}")
    return stocks, etfs

# =============================================================================
# EXPORT & MOBILE README GENERATOR
# =============================================================================

def save_results(results, market_ok):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    date_str = datetime.datetime.now().strftime("%Y%m%d")
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mkt_str = "🟢 允許做多 (Bullish)" if market_ok else "🔴 防禦模式 (Defensive)"

    # 根據動態設定篩選模式過濾結果
    filtered_results = []
    for r in results:
        if FILTER_MODE == "BUY" and r["status"] == "BUY":
            filtered_results.append(r)
        elif FILTER_MODE == "WATCH" and r["status"] == "WATCH":
            filtered_results.append(r)
        elif FILTER_MODE == "ALL":
            filtered_results.append(r)

    df_res = pd.DataFrame(filtered_results)

    if not df_res.empty:
        cols_order = [
            "symbol", "name", "category", "status", "score", "close",
            "RSI", "VOL_RATIO", "MA20_BIAS", "RET5", "RET10", "ATR_PCT",
            "stop", "target", "RR", "reason"
        ]
        df_res = df_res[cols_order]
        df_res = df_res.sort_values(by=["status", "score"], ascending=[True, False])

    # 輸出 CSV
    csv_path = os.path.join(OUTPUT_DIR, f"scan_{FILTER_MODE.lower()}_{date_str}.csv")
    latest_csv_path = os.path.join(OUTPUT_DIR, "latest_result.csv")

    df_res.to_csv(csv_path, index=False, encoding="utf-8-sig")
    df_res.to_csv(latest_csv_path, index=False, encoding="utf-8-sig")

    # 生成手機極致優化的專案首頁 README.md
    root_readme_path = os.path.join(os.getcwd(), "README.md")

    with open(root_readme_path, "w", encoding="utf-8") as f:
        f.write(f"# 📊 TPE90 量化選股掃描儀\n\n")
        f.write(f"> **版本**: `{VERSION}`  \n")
        f.write(f"> **更新時間**: `{now_str}`  \n")
        f.write(f"> **大盤趨勢 (0050.TW)**: {mkt_str}  \n")
        f.write(f"> **目前顯示模式**: `{FILTER_MODE}`（符合筆數: {len(df_res)} 檔）\n\n")
        f.write("---\n\n")

        if not df_res.empty:
            # 針對手機橫向捲動優化的 Markdown 表格
            f.write("### 🎯 篩選結果標的明細\n\n")

            # 使用口語化的表頭提升行動端可讀性
            rename_map = {
                "symbol": "代號",
                "name": "名稱",
                "category": "類別",
                "status": "訊號",
                "score": "評分",
                "close": "現價",
                "VOL_RATIO": "量能比",
                "MA20_BIAS": "20日乖離%",
                "stop": "停損價",
                "target": "目標價",
                "RR": "風報比",
                "reason": "觸發因子"
            }
            display_df = df_res[list(rename_map.keys())].rename(columns=rename_map)

            # 高亮顯示 BUY 與 WATCH 狀態
            display_df["訊號"] = display_df["訊號"].apply(lambda x: f"🔥 {x}" if x == "BUY" else f"👀 {x}")

            f.write(display_df.to_markdown(index=False))
            f.write("\n\n---\n")
            f.write("*備註：完整數據（含 RSI、ADX、ATR% 等）已儲存至 `results/latest_result.csv`。*\n")
        else:
            f.write("### ⚪ 今日無符合此篩選條件之標的\n")

    print(f"\n[完成] 掃描報告已更新至首頁 README.md (篩選模式: {FILTER_MODE})")

# =============================================================================
# MAIN EXECUTOR
# =============================================================================

def process_target(target, market_ok):
    symbol, name, category = target
    df, status = download_history(symbol)
    if df is None:
        return None

    res = evaluate_signal(df, len(df) - 1, market_ok=market_ok)
    if res:
        res["symbol"] = symbol
        res["name"] = name
        res["category"] = category
        return res
    return None

def main():
    print(f"=== 啟動 {VERSION} 量化掃描引擎 ===")
    print(f"當前指定篩選過濾模式: {FILTER_MODE}")
    market_ok = market_filter()

    universe = []
    if INCLUDE_TW_STOCK or INCLUDE_TW_ETF:
        tw_stocks, tw_etfs = get_twse_universe()
        if INCLUDE_TW_STOCK: universe.extend(tw_stocks)
        if INCLUDE_TW_ETF: universe.extend(tw_etfs)

    if INCLUDE_US_ETF:
        for symbol, name in US_ETF_CANDIDATES:
            universe.append((symbol, name, "US_ETF"))

    seen = set()
    unique_universe = []
    for u in universe:
        if u[0] not in seen:
            seen.add(u[0])
            unique_universe.append(u)

    print(f"全市場標的池掃描中，總計 {len(unique_universe)} 檔標的...")

    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_target, target, market_ok): target for target in unique_universe}
        for future in as_completed(futures):
            res = future.result()
            if res:
                results.append(res)

    print(f"多因子篩選完畢，共獲取 {len(results)} 檔候選標的。")
    save_results(results, market_ok)

if __name__ == "__main__":
    main()