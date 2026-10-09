#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
============================================================================================
TPE Pullback Reclaim V4.1 (GITHUB ACTIONS & MOBILE DISPLAY OPTIMIZED)
上升趨勢淺回檔 + 站回確認 + T+1 開盤建議
============================================================================================
"""

import os
import time
import warnings
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# ============================================================
# CONFIGURATION & ENVIRONMENT
# ============================================================

VERSION = "TPE Pullback Reclaim V4.1"

# 雲端執行輸出目錄 (專案內 results 資料夾)
OUTPUT_DIR = os.path.join(os.getcwd(), "results")

# 透過環境變數取得篩選模式 (預設 ALL: 顯示 BUY / WATCH / AVOID)
# 可選模式: "ALL", "BUY", "WATCH", "AVOID"
FILTER_MODE = os.environ.get("FILTER_MODE", "ALL").upper()

REQUEST_SLEEP = 0.05
WARMUP_DAYS = 420
MIN_BARS = 160
MARKET_SYMBOL = "0050.TW"

MIN_PRICE = 15.0
MIN_TURNOVER = 30_000_000

PULLBACK_LOOKBACK = 8
MIN_PULLBACK = 2.0
MAX_PULLBACK = 7.0
MAX_DIST_MA20 = 1.2
MAX_ATR_PCT = 3.2
RSI_LO, RSI_HI = 42.0, 62.0

ATR_STOP_MULT = 1.05
MIN_STOP, MAX_STOP = 1.8, 3.2
TARGET_R = 1.15

# 備援流動性清單（專案內無名單時自動啟用）
FALLBACK_UNIVERSE = [
    ("2330", "台積電", "2330.TW"),
    ("2317", "鴻海", "2317.TW"),
    ("2454", "聯發科", "2454.TW"),
    ("2308", "台達電", "2308.TW"),
    ("2303", "聯電", "2303.TW"),
    ("2881", "富邦金", "2881.TW"),
    ("2882", "國泰金", "2882.TW"),
    ("2891", "中信金", "2891.TW"),
    ("2886", "兆豐金", "2886.TW"),
    ("2412", "中華電", "2412.TW"),
    ("1301", "台塑", "1301.TW"),
    ("1303", "南亞", "1303.TW"),
    ("2002", "中鋼", "2002.TW"),
    ("2207", "和泰車", "2207.TW"),
    ("2912", "統一超", "2912.TW"),
    ("5871", "中租-KY", "5871.TW"),
    ("3034", "聯詠", "3034.TW"),
    ("2379", "瑞昱", "2379.TW"),
    ("6669", "緯穎", "6669.TW"),
    ("3443", "創意", "3443.TW"),
    ("2603", "長榮", "2603.TW"),
    ("2609", "陽明", "2609.TW"),
    ("2615", "萬海", "2615.TW"),
    ("3008", "大立光", "3008.TW"),
    ("3711", "日月光投控", "3711.TW"),
    ("2357", "華碩", "2357.TW"),
    ("2382", "廣達", "2382.TW"),
    ("3231", "緯創", "3231.TW"),
    ("2345", "智邦", "2345.TW"),
    ("3045", "台灣大", "3045.TW"),
    ("4904", "遠傳", "4904.TW"),
    ("6505", "台塑化", "6505.TW"),
    ("1326", "台化", "1326.TW"),
    ("1101", "台泥", "1101.TW"),
    ("9910", "豐泰", "9910.TW"),
    ("6415", "矽力*-KY", "6415.TW"),
    ("3661", "世芯-KY", "3661.TW"),
    ("3529", "力旺", "3529.TWO"),
    ("3105", "穩懋", "3105.TWO"),
    ("6488", "環球晶", "6488.TWO"),
]

# ============================================================
# TECHNICAL INDICATORS & UTILITIES
# ============================================================

def flatten(df):
    if df is None or df.empty:
        return df
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(c[0]) for c in df.columns]
    mapping = {
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume",
        "adj close": "Adj Close",
    }
    rename = {}
    for c in df.columns:
        key = str(c).strip().lower().replace("_", " ")
        if key in mapping:
            rename[c] = mapping[key]
    df = df.rename(columns=rename)
    if df.columns.duplicated().any():
        df = df.loc[:, ~df.columns.duplicated(keep="first")]
    return df

def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)

def atr(df, n=14):
    pc = df["Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - pc).abs(),
        (df["Low"] - pc).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()

def add_ind(df):
    df = df.copy()
    c, h, l, v = df["Close"], df["High"], df["Low"], df["Volume"]
    df["MA10"] = c.rolling(10).mean()
    df["MA20"] = c.rolling(20).mean()
    df["MA60"] = c.rolling(60).mean()
    df["RSI"] = rsi(c)
    df["ATR"] = atr(df)
    df["VOL_MA20"] = v.rolling(20).mean()
    df["VOL_RATIO"] = v / df["VOL_MA20"].replace(0, np.nan)
    df["TURNOVER_MA20"] = (c * v).rolling(20).mean()
    df["MA20_SLOPE"] = (df["MA20"] / df["MA20"].shift(5) - 1) * 100
    df["MA60_SLOPE"] = (df["MA60"] / df["MA60"].shift(10) - 1) * 100
    df["DIST_MA20"] = (c / df["MA20"] - 1) * 100
    df["LOW8_PREV"] = l.shift(1).rolling(8).min()
    df["CLOSE_POS"] = (c - l) / (h - l).replace(0, np.nan)
    return df

def download(symbol, start, end):
    try:
        df = yf.download(
            symbol, start=start, end=end, interval="1d",
            auto_adjust=False, progress=False, threads=False
        )
        df = flatten(df)
        if df is None or df.empty:
            hist = yf.Ticker(symbol).history(
                start=start, end=end, interval="1d", auto_adjust=False
            )
            df = flatten(hist)
        if df is None or df.empty:
            return None
        need = ["Open", "High", "Low", "Close", "Volume"]
        if any(c not in df.columns for c in need):
            return None
        df = df[need].apply(pd.to_numeric, errors="coerce")
        df = df.dropna(subset=["Open", "High", "Low", "Close"])
        df.index = pd.to_datetime(df.index).tz_localize(None)
        return df.sort_index()[~df.index.duplicated(keep="last")]
    except Exception:
        return None

def pullback_state(df, i):
    w = df.iloc[max(0, i - PULLBACK_LOOKBACK):i]
    if w.empty:
        return False, 0.0
    touched = ((w["Low"] <= w["MA20"] * 1.008) | (w["Close"] <= w["MA20"] * 1.01)).any()
    rh, rl = w["High"].max(), w["Low"].min()
    pb = (rh - rl) / rh * 100 if rh and rh > 0 else 0.0
    ok = bool(touched and MIN_PULLBACK <= pb <= MAX_PULLBACK)
    return ok, float(pb)

def diagnose(df, i, market_ok):
    fails = []
    reasons = []
    if i < 80:
        return "AVOID", [], ["BARS"]
    r, p = df.iloc[i], df.iloc[i - 1]
    close, ma20, ma60 = r["Close"], r["MA20"], r["MA60"]
    if any(pd.isna(x) for x in [close, ma20, ma60, r["ATR"], r["RSI"]]):
        return "AVOID", [], ["INDICATOR_NA"]
    if not market_ok:
        fails.append("MARKET_OFF")
    if close < MIN_PRICE:
        fails.append("PRICE")
    if pd.isna(r["TURNOVER_MA20"]) or r["TURNOVER_MA20"] < MIN_TURNOVER:
        fails.append("LIQUIDITY")
    atr_pct = r["ATR"] / close * 100 if close else np.nan
    if np.isfinite(atr_pct) and atr_pct > MAX_ATR_PCT:
        fails.append("ATR_HIGH")
    trend = close > ma60 and ma20 > ma60 and r["MA20_SLOPE"] >= 0.05 and r["MA60_SLOPE"] >= 0
    if trend:
        reasons.append("UPTREND")
    else:
        fails.append("TREND")
    if RSI_LO <= r["RSI"] <= RSI_HI:
        reasons.append("RSI_OK")
    else:
        fails.append("RSI")
    if -0.4 <= r["DIST_MA20"] <= MAX_DIST_MA20:
        reasons.append("NEAR_MA20")
    else:
        fails.append("DIST_MA20")
    if 0.70 <= r["VOL_RATIO"] <= 1.80:
        reasons.append("VOL_OK")
    else:
        fails.append("VOLUME")
    if r["CLOSE_POS"] >= 0.60 and close > r["Open"]:
        reasons.append("STRONG_CLOSE")
    else:
        fails.append("CANDLE")
    pb_ok, pb = pullback_state(df, i)
    if pb_ok:
        reasons.append(f"PULLBACK_{pb:.1f}")
    else:
        fails.append("PULLBACK")
    reclaim = close > ma20 and p["Close"] <= p["MA20"] * 1.002
    early = close >= ma20 * 0.998 and p["Close"] < p["MA20"] and r["CLOSE_POS"] >= 0.65
    if reclaim or early:
        reasons.append("RECLAIM")
    else:
        fails.append("NO_RECLAIM")

    hard_fail = {"PRICE", "LIQUIDITY", "INDICATOR_NA", "BARS"}
    if fails and set(fails) & hard_fail:
        action = "AVOID"
    elif not fails:
        action = "BUY"
    elif trend and "MARKET_OFF" not in fails and len(fails) <= 2:
        action = "WATCH"
    else:
        action = "AVOID"
    return action, reasons, fails

def stop_pct(entry, atr_v, swing):
    atr_p = (atr_v / entry) * 100 * ATR_STOP_MULT if atr_v and atr_v > 0 else 2.4
    sw = ((entry - swing) / entry) * 100 if swing and entry > swing else np.nan
    raw = max([x for x in [atr_p, sw] if np.isfinite(x)] or [2.4])
    return float(min(MAX_STOP, max(MIN_STOP, raw)))

def plan_prices(close, atr_v, swing):
    sp = stop_pct(close, atr_v, swing)
    stop = close * (1 - sp / 100)
    target = close * (1 + sp / 100 * TARGET_R)
    return sp, stop, target

def latest_row(df, code, name, symbol, market_ok):
    i = len(df) - 1
    r = df.iloc[i]
    action, reasons, fails = diagnose(df, i, market_ok)
    close = float(r["Close"])
    sp, stop, target = plan_prices(close, r["ATR"], r["LOW8_PREV"])
    if action == "BUY":
        exec_note = "🔥 BUY（建議進場）；次一交易日開盤買。"
    elif action == "WATCH":
        exec_note = "👀 WATCH（觀察）；尚未完全站回，等下一根收盤再確認。"
    else:
        exec_note = "⚪ AVOID（觀望）；條件未符合。"

    return {
        "代碼": code,
        "名稱": name,
        "代號": symbol,
        "訊號": f"🔥 {action}" if action == "BUY" else (f"👀 {action}" if action == "WATCH" else action),
        "raw_action": action,
        "最新收盤": round(close, 2),
        "建議停損價": round(stop, 2),
        "目標獲利價": round(target, 2),
        "停損幅度%": round(sp, 2),
        "風報比": TARGET_R,
        "RSI": round(float(r["RSI"]), 2),
        "MA20乖離%": round(float(r["DIST_MA20"]), 2),
        "量能倍數": round(float(r["VOL_RATIO"]), 2) if pd.notna(r["VOL_RATIO"]) else np.nan,
        "觸發原因": "|".join(reasons) if reasons else "-",
        "未過關": "|".join(fails) if fails else "-",
        "操作建議": exec_note
    }

def load_universe():
    # 優先嘗試讀取專案內的候選檔案
    possible_paths = ["stock_universe.csv", "strategies/stock_universe.csv"]
    for path in possible_paths:
        if os.path.exists(path):
            try:
                df = pd.read_csv(path)
                df.columns = [str(c).strip() for c in df.columns]
                code_col = next((c for c in df.columns if c in {"代號", "股票代號", "股號", "code", "Code", "symbol", "Symbol"}), df.columns[0])
                name_col = next((c for c in df.columns if c in {"名稱", "股票名稱", "股名", "name", "Name"}), code_col)
                mkt_col = next((c for c in df.columns if c in {"市場", "market", "Market", "交易所"}), None)
                rows = []
                for _, row in df.iterrows():
                    raw = str(row[code_col]).strip()
                    if raw.lower() in {"nan", "none", ""}: continue
                    code = raw.split(".")[0].replace(".0", "")
                    if not code.isdigit() or len(code) != 4: continue
                    mkt = str(row[mkt_col]) if mkt_col else ""
                    mu = mkt.upper()
                    symbol = code + ".TWO" if (raw.endswith(".TWO") or "TPEX" in mu or "TWO" in mu) else code + ".TW"
                    rows.append((code, str(row[name_col]).strip(), symbol))
                if rows:
                    return rows
            except Exception:
                pass

    print(f"[提示] 未找到專案名單或格式有誤，自動啟動內建熱門流動性清單 ({len(FALLBACK_UNIVERSE)} 檔)。")
    return list(FALLBACK_UNIVERSE)

# ============================================================
# EXPORT & SAVE RESULTS
# ============================================================

def save_results(signal_rows):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d")
    df_signals = pd.DataFrame(signal_rows)

    # 根據動態過濾模式進行數據篩選
    filtered_rows = []
    for r in signal_rows:
        raw_act = r.get("raw_action", "")
        if FILTER_MODE == "BUY" and raw_act == "BUY":
            filtered_rows.append(r)
        elif FILTER_MODE == "WATCH" and raw_act == "WATCH":
            filtered_rows.append(r)
        elif FILTER_MODE == "AVOID" and raw_act == "AVOID":
            filtered_rows.append(r)
        elif FILTER_MODE == "ALL":
            filtered_rows.append(r)

    df_res = pd.DataFrame(filtered_rows)
    if not df_res.empty and "raw_action" in df_res.columns:
        df_res = df_res.drop(columns=["raw_action"])

    # 輸出 CSV 至 results/ 資料夾
    sig_csv = os.path.join(OUTPUT_DIR, f"tpe_reclaim_{FILTER_MODE.lower()}_{timestamp}.csv")
    latest_csv = os.path.join(OUTPUT_DIR, "tpe_reclaim_latest.csv")

    if not df_res.empty:
        df_res.to_csv(sig_csv, index=False, encoding="utf-8-sig")
        df_res.to_csv(latest_csv, index=False, encoding="utf-8-sig")
    else:
        empty_df = pd.DataFrame([{"說明": f"今日無符合 {FILTER_MODE} 條件之訊號"}])
        empty_df.to_csv(sig_csv, index=False, encoding="utf-8-sig")
        empty_df.to_csv(latest_csv, index=False, encoding="utf-8-sig")

    print(f"\n[完成] 策略 TPE Pullback Reclaim V4.1 掃描完畢 (過濾模式: {FILTER_MODE})，結果已寫入 {latest_csv}")

# ============================================================
# MAIN EXECUTOR
# ============================================================

def main():
    print(f"=== 啟動 {VERSION} ===")
    print(f"當前指定過濾模式: {FILTER_MODE}")

    end = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    dl_start = (datetime.now() - timedelta(days=WARMUP_DAYS)).strftime("%Y-%m-%d")

    universe = load_universe()
    print(f"掃描標的池載入完畢，共計 {len(universe)} 檔。")

    mkt_raw = download(MARKET_SYMBOL, dl_start, end)
    if mkt_raw is None:
        last_mkt_ok = True
    else:
        mkt_ind = add_ind(mkt_raw)
        c = mkt_ind["Close"]
        ma20 = c.rolling(20).mean()
        ma60 = c.rolling(60).mean()
        slope = (ma60 / ma60.shift(10) - 1) * 100
        regime = ((c > ma60) & (ma20 > ma60) & (slope > -0.05)).fillna(False)
        last_mkt_ok = bool(regime.iloc[-1]) if len(regime) else True

    print(f"[大盤狀態 (0050.TW)]：{'🟢 允許做多' if last_mkt_ok else '🔴 防禦模式 (多單過濾停用)'}")

    signal_rows = []
    for n, (code, name, symbol) in enumerate(universe, 1):
        time.sleep(REQUEST_SLEEP)
        raw = download(symbol, dl_start, end)
        if raw is None or len(raw) < MIN_BARS:
            continue

        df = add_ind(raw).dropna(subset=["MA60", "RSI", "ATR"])
        if len(df) < 80:
            continue

        row = latest_row(df, code, name, symbol, last_mkt_ok)
        signal_rows.append(row)

    save_results(signal_rows)

if __name__ == "__main__":
    main()