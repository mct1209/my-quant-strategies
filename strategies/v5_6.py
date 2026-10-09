#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
============================================================================================
TW BREAKOUT SCAN V5.5 (GITHUB ACTIONS & MOBILE DISPLAY OPTIMIZED)
全台股多因子突破掃描引擎
============================================================================================
"""

import os
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import StringIO
import numpy as np
import pandas as pd
import requests
import yfinance as yf

warnings.filterwarnings('ignore')

VERSION = 'TW Breakout Scan V5.5 (Quant Master)'

# 雲端執行輸出目錄 (專案內 results 資料夾)
OUTPUT_DIR = os.path.join(os.getcwd(), 'results')

# 透過環境變數取得篩選模式 (預設 ALL: 顯示 BUY / WATCH)
# 可選模式: "ALL", "BUY", "WATCH"
FILTER_MODE = os.environ.get('FILTER_MODE', 'ALL').upper()

MAX_WORKERS = 4
REQUEST_SLEEP = .05
MIN_BARS = 160
HISTORY_PERIOD = '2y'

BREAKOUT_LOOKBACK = 20
BIAS_BUY_MAX = 4.5
BIAS_WATCH_MAX = 6.0
VOL_MIN = 1.50
VOL_MAX = 3.00
VOL_HARD_MAX = 3.50

UPPER_SHADOW_MAX = .35
CLOSE_POSITION_MIN = .65
RSI_MIN = 52
RSI_MAX = 68
ADX_MIN = 18

ATR_PERIOD = 14
ATR_STOP_MULT = 1.50
TARGET_R = 1.80
GAP_SKIP_PCT = 2.0
BUY_SCORE_MIN = 80
WATCH_SCORE_MIN = 68

SESSION = requests.Session()
SESSION.headers.update({
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/153.0.0.0 Safari/537.36',
    'Accept': 'application/json,text/plain,*/*'
})

ALIASES = {
    'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close',
    'adj close': 'Adj Close', 'adjclose': 'Adj Close', 'adj_close': 'Adj Close', 'volume': 'Volume'
}

def norm_code(x):
    s = str(x).strip()
    return s[:-3] if s.endswith(('.TW', '.TWO')) else s

def ordinary(code):
    c = norm_code(code)
    return c.isdigit() and len(c) == 4 and not c.startswith(('00', '01'))

def unique(stocks):
    d = {t: (t, n) for t, n in stocks if t and n}
    return sorted(d.values())

def fetch_json(url, timeout=25):
    r = SESSION.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()

def get_twse():
    stocks = []
    try:
        data = fetch_json('https://openapi.twse.com.tw/v1/opendata/t187ap03_L')
        for r in data:
            code = r.get('公司代號') or r.get('Code') or r.get('股票代號')
            name = r.get('公司名稱') or r.get('Name') or r.get('公司簡稱')
            if code is not None and name is not None and ordinary(code):
                stocks.append((f'{norm_code(code)}.TW', str(name).strip()))
        stocks = unique(stocks)
        if len(stocks) >= 500: return stocks, 'OpenAPI'
    except Exception as e:
        print('[TWSE] OpenAPI 失敗：', e)
    try:
        data = fetch_json('https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL')
        for r in data:
            code = r.get('Code') or r.get('證券代號')
            name = r.get('Name') or r.get('證券名稱')
            if code is not None and name is not None and ordinary(code):
                stocks.append((f'{norm_code(code)}.TW', str(name).strip()))
        stocks = unique(stocks)
        if len(stocks) >= 500: return stocks, 'STOCK_DAY_ALL fallback'
    except Exception as e:
        print('[TWSE] fallback 失敗：', e)
    return [], 'failed'

def get_tpex():
    urls = ['https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes', 'https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O']
    for url in urls:
        try:
            data = fetch_json(url)
            stocks = []
            for r in data:
                code = r.get('SecuritiesCompanyCode') or r.get('Code') or r.get('公司代號') or r.get('股票代號')
                name = r.get('CompanyName') or r.get('Name') or r.get('公司名稱') or r.get('公司簡稱')
                if code is not None and name is not None and ordinary(code):
                    stocks.append((f'{norm_code(code)}.TWO', str(name).strip()))
            stocks = unique(stocks)
            if len(stocks) >= 300: return stocks, 'OpenAPI'
        except Exception as e:
            print(f'[TPEx] {url} 失敗：{e}')
    for url in ['https://mopsfin.twse.com.tw/opendata/t187ap03_O.csv', 'https://mopsfin.twse.com.tw/opendata/t187ap03_O.csv?download=1']:
        try:
            r = SESSION.get(url, timeout=25)
            r.raise_for_status()
            stocks = []
            for enc in ['utf-8-sig', 'big5', 'cp950']:
                try:
                    df = pd.read_csv(StringIO(r.content.decode(enc, errors='ignore')), dtype=str, engine='python')
                    cols = [str(c).strip() for c in df.columns]
                    cc = next((c for c in cols if '公司代號' in c or '有價證券代號' in c or c.lower() == 'code'), None)
                    nc = next((c for c in cols if '公司名稱' in c or '有價證券名稱' in c or c.lower() == 'name'), None)
                    if cc and nc:
                        for _, row in df.iterrows():
                            code = norm_code(row.get(cc, ''))
                            name = str(row.get(nc, '')).strip()
                            if ordinary(code) and name: stocks.append((f'{code}.TWO', name))
                        stocks = unique(stocks)
                        if len(stocks) >= 300: return stocks, 'MOPS CSV fallback'
                except Exception: pass
        except Exception as e:
            print('[TPEx] MOPS CSV 失敗：', e)
    return [], 'failed'

def get_taiwan_stock_list():
    print('[資訊] 使用 TWSE / TPEx 官方 API 取得普通股清單...')
    twse, ts = get_twse()
    tpex, ps = get_tpex()
    stocks = unique(twse + tpex)
    print(f'[清單解析完成] TWSE={len(twse)} / TPEx={len(tpex)} / 合計={len(stocks)}')
    return stocks

def flatten(df):
    if df is None or df.empty: return df
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        chosen = 0
        for level in range(df.columns.nlevels):
            vals = [str(v).strip().lower() for v in df.columns.get_level_values(level)]
            if sum(v in ALIASES for v in vals) >= 3:
                chosen = level
                break
        df.columns = [str(v) for v in df.columns.get_level_values(chosen)]
    ren = {}
    for c in df.columns:
        k = str(c).strip().lower().replace('_', ' ')
        if k in ALIASES: ren[c] = ALIASES[k]
    df = df.rename(columns=ren)
    if df.columns.duplicated().any():
        df = df.loc[:, ~df.columns.duplicated(keep='first')]
    return df

def atr(df, p=14):
    pc = df.Close.shift(1)
    tr = pd.concat([df.High - df.Low, (df.High - pc).abs(), (df.Low - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(p).mean()

def rsi(close, p=14):
    d = close.diff()
    g = d.clip(lower=0)
    l = -d.clip(upper=0)
    ag = g.ewm(alpha=1/p, adjust=False).mean()
    al = l.ewm(alpha=1/p, adjust=False).mean()
    rs = ag / al.replace(0, np.nan)
    return 100 - 100 / (1 + rs)

def macd(close):
    a = close.ewm(span=12, adjust=False).mean()
    b = close.ewm(span=26, adjust=False).mean()
    m = a - b
    s = m.ewm(span=9, adjust=False).mean()
    return m, s, m - s

def adx(df, p=14):
    h, l, c = df.High, df.Low, df.Close
    up = h.diff()
    dn = -l.diff()
    plus = pd.Series(np.where((up > dn) & (up > 0), up, 0.), index=df.index)
    minus = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.), index=df.index)
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    a = tr.ewm(alpha=1/p, adjust=False).mean()
    pdi = 100 * plus.ewm(alpha=1/p, adjust=False).mean() / a.replace(0, np.nan)
    mdi = 100 * minus.ewm(alpha=1/p, adjust=False).mean() / a.replace(0, np.nan)
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1/p, adjust=False).mean(), pdi, mdi

def prepare(df):
    df = df.copy()
    df['MA20'] = df.Close.rolling(20).mean()
    df['MA60'] = df.Close.rolling(60).mean()
    df['MA120'] = df.Close.rolling(120).mean()
    df['MA20_SLOPE'] = (df.MA20 / df.MA20.shift(5) - 1) * 100
    df['MA60_SLOPE'] = (df.MA60 / df.MA60.shift(10) - 1) * 100
    df['ATR'] = atr(df, ATR_PERIOD)
    df['RSI'] = rsi(df.Close)
    df['MACD'], df['MACD_SIGNAL'], df['MACD_HIST'] = macd(df.Close)
    df['ADX'], df['PLUS_DI'], df['MINUS_DI'] = adx(df)
    df['VOL_MA20'] = df.Volume.rolling(20).mean()
    df['VOL_RATIO'] = df.Volume / df.VOL_MA20.replace(0, np.nan)
    df['HIGH20_PREV'] = df.High.rolling(20).max().shift(1)
    df['HIGH60_PREV'] = df.High.rolling(60).max().shift(1)
    df['HIGH120_PREV'] = df.High.rolling(120).max().shift(1)
    df['BIAS20'] = (df.Close / df.MA20 - 1) * 100
    df['ATR_PCT'] = df.ATR / df.Close * 100
    return df

def evaluate(df, i, market_ok=True):
    if i < 130: return None
    row = df.iloc[i]
    req = ['Close', 'High', 'Low', 'Open', 'Volume', 'MA20', 'MA60', 'ATR', 'RSI', 'MACD', 'MACD_SIGNAL', 'MACD_HIST', 'ADX', 'PLUS_DI', 'MINUS_DI', 'VOL_RATIO', 'HIGH20_PREV', 'HIGH60_PREV', 'HIGH120_PREV']
    if any(pd.isna(row[c]) for c in req): return None

    close, high, low, op = [float(row[x]) for x in ['Close', 'High', 'Low', 'Open']]
    vol = float(row.Volume)
    ma20 = float(row.MA20)
    ma60 = float(row.MA60)
    a = float(row.ATR)
    rv = float(row.RSI)
    m = float(row.MACD)
    ms = float(row.MACD_SIGNAL)
    mh = float(row.MACD_HIST)
    ax = float(row.ADX)
    pi = float(row.PLUS_DI)
    mi = float(row.MINUS_DI)
    vr = float(row.VOL_RATIO)
    h20 = float(row.HIGH20_PREV)
    h60 = float(row.HIGH60_PREV)
    h120 = float(row.HIGH120_PREV)
    bias = (close / ma20 - 1) * 100

    b20 = close > h20
    b60 = close > h60

    if not b20 or bias > BIAS_WATCH_MAX or not market_ok: return None

    trend = (8 if close > ma20 else 0) + (8 if ma20 > ma60 else 0) + (4 if float(row.MA20_SLOPE) > 0 else 0) + (5 if float(row.MA60_SLOPE) > 0 else 0)
    momentum = (8 if RSI_MIN <= rv <= RSI_MAX else 0) + (6 if m > ms else 0) + (5 if mh > 0 else 0) + (3 if pi > mi else 0) + (3 if ax >= ADX_MIN else 0)
    v5 = float(df.Volume.rolling(5).mean().iloc[i])
    flow = (10 if VOL_MIN <= vr <= VOL_MAX else 0) + (4 if vr <= VOL_HARD_MAX else 0) + (3 if vol > v5 else 0) + (3 if close > op else 0)

    rng = high - low
    if rng <= 0: return None

    ush = (high - max(op, close)) / rng
    cp = (close - low) / rng
    candle = (8 if ush <= UPPER_SHADOW_MAX else 0) + (7 if cp >= CLOSE_POSITION_MIN else 0)

    if cp < .55 or ush > .45 or vr > VOL_HARD_MAX or rv > 72: return None

    hd = (close / h120 - 1) * 100
    pos = 0 if hd > 0 else 8 if hd >= -5 else 5 if hd >= -10 else 2
    score = trend + momentum + flow + candle + pos + (8 if b60 else 0) + (5 if bias <= 3 else 0) + (3 if 55 <= rv <= 64 else 0)

    stop = close - ATR_STOP_MULT * a
    target = close + TARGET_R * (close - stop)
    risk = close - stop
    if risk <= 0: return None

    rr = (target - close) / risk
    if rr < 1.8: return None

    not_chase = bias <= BIAS_BUY_MAX
    status = 'BUY' if score >= BUY_SCORE_MIN and not_chase else 'WATCH' if score >= WATCH_SCORE_MIN else None
    if not status: return None

    checks = [
        (b20, 'BREAKOUT20'), (b60, 'BREAKOUT60'), (close > ma20, 'ABOVE_MA20'),
        (ma20 > ma60, 'MA20_GT_MA60'), (float(row.MA60_SLOPE) > 0, 'MA60_UP'),
        (RSI_MIN <= rv <= RSI_MAX, 'RSI_OK'), (m > ms, 'MACD_BULL'), (mh > 0, 'MACD_HIST_POS'),
        (ax >= ADX_MIN, 'ADX_OK'), (pi > mi, 'DI_PLUS'), (VOL_MIN <= vr <= VOL_MAX, 'VOL_CONFIRM'),
        (cp >= CLOSE_POSITION_MIN, 'STRONG_CLOSE'), (ush <= UPPER_SHADOW_MAX, 'NO_LONG_SHADOW'),
        (bias <= 3, 'LOW_CHASE'), (b60, '60D_CONFIRM')
    ]
    reasons = [n for ok, n in checks if ok]

    return {
        'status': status, 'score': round(score, 2), 'RSI': round(rv, 2), 'ADX': round(ax, 2),
        'VOL_RATIO': round(vr, 2), 'MA20_BIAS': round(bias, 2), 'HIGH120_DISTANCE': round(hd, 2),
        'ATR_PCT': round(a / close * 100, 2), 'MA20': round(ma20, 2), 'MA60': round(ma60, 2),
        'close': round(close, 2), 'stop': round(stop, 2), 'target': round(target, 2),
        'RR': round(rr, 2), 'reason': '|'.join(reasons)
    }

def download(ticker):
    last = None
    for k in range(3):
        try:
            df = flatten(yf.download(ticker, period=HISTORY_PERIOD, interval='1d', auto_adjust=False, progress=False, threads=False))
            if df is None or df.empty: raise RuntimeError('Yahoo 回傳空資料')
            need = ['Open', 'High', 'Low', 'Close', 'Volume']
            if any(c not in df.columns for c in need): raise RuntimeError(f'缺少欄位：{list(df.columns)}')
            df = df[need].copy()
            for c in need: df[c] = pd.to_numeric(df[c], errors='coerce')
            df = df.dropna(subset=['Open', 'High', 'Low', 'Close'])
            if len(df) < MIN_BARS: return None, 'too_short'
            return prepare(df), 'ok'
        except Exception as e:
            last = e
            time.sleep(.4 * (k + 1))
    return None, f'error:{last}'

def market_filter():
    df, s = download('0050.TW')
    if df is None:
        print('[0050] 下載失敗，預設允許做多：', s)
        return True
    x = df.iloc[-1]
    c = float(x.Close)
    m20 = float(x.MA20)
    m60 = float(x.MA60)
    sl = float(x.MA60_SLOPE)
    ok = c > m20 and m20 > m60 and sl > 0
    print(f'[0050 大盤濾網] Close={c:.2f} MA20={m20:.2f} MA60={m60:.2f} MA60Slope={sl:.2f}%')
    print('市場環境：允許做多' if ok else '市場環境：防禦模式，不產生 BUY')
    return ok

def scan(item, market_ok):
    ticker, name = item
    try:
        time.sleep(REQUEST_SLEEP)
        df, s = download(ticker)
        if df is None: return None
        info = evaluate(df, len(df) - 1, market_ok)
        if info is None: return None

        raw_act = info['status']
        symbol_code = ticker.split('.')[0]
        signal_icon = f"🔥 {raw_act}" if raw_act == "BUY" else f"👀 {raw_act}"

        return {
            '代碼': symbol_code,
            '名稱': name,
            '代號': ticker,
            '訊號': signal_icon,
            'raw_status': raw_act,
            '分數': info['score'],
            '最新收盤': info['close'],
            '建議停損價': info['stop'],
            '目標獲利價': info['target'],
            '量能倍數': info['VOL_RATIO'],
            'MA20乖離%': info['MA20_BIAS'],
            '觸發原因': info['reason'],
            '操作建議': 'T+1 開盤市價執行；若開盤 Gap > 2% 則取消進場'
        }
    except Exception:
        return None

def save_results(signals):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = pd.Timestamp.now().strftime('%Y%m%d')

    filtered_signals = []
    for s in signals:
        raw_act = s.get('raw_status', '')
        if FILTER_MODE == 'BUY' and raw_act == 'BUY':
            filtered_signals.append(s)
        elif FILTER_MODE == 'WATCH' and raw_act == 'WATCH':
            filtered_signals.append(s)
        elif FILTER_MODE == 'ALL':
            filtered_signals.append(s)

    df_res = pd.DataFrame(filtered_signals)
    if not df_res.empty and 'raw_status' in df_res.columns:
        df_res = df_res.drop(columns=['raw_status'])

    sig_csv = os.path.join(OUTPUT_DIR, f'tw_breakout_{FILTER_MODE.lower()}_{timestamp}.csv')
    latest_csv = os.path.join(OUTPUT_DIR, 'tw_breakout_latest.csv')

    if not df_res.empty:
        df_res.to_csv(sig_csv, index=False, encoding='utf-8-sig')
        df_res.to_csv(latest_csv, index=False, encoding='utf-8-sig')
    else:
        empty_df = pd.DataFrame([{"說明": f"今日無符合 {FILTER_MODE} 條件之訊號"}])
        empty_df.to_csv(sig_csv, index=False, encoding='utf-8-sig')
        empty_df.to_csv(latest_csv, index=False, encoding='utf-8-sig')

    print(f"\n[完成] 策略 TW Breakout Scan V5.5 掃描完畢 (過濾模式: {FILTER_MODE})，結果已寫入 {latest_csv}")

def main():
    print('=' * 60)
    print(f"{VERSION} 啟動掃描引擎")
    print(f"當前指定過濾模式: {FILTER_MODE}")
    print('=' * 60)

    market_ok = market_filter()
    stocks = get_taiwan_stock_list()

    if not stocks:
        print('[錯誤] 無法取得股票清單。')
        return

    total = len(stocks)
    print(f'開始對全台股 {total} 檔標的進行多線程突破掃描...')

    signals = []
    done = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        fs = {ex.submit(scan, s, market_ok): s for s in stocks}
        for f in as_completed(fs):
            done += 1
            if done % 200 == 0 or done == total:
                print(f'  -> 進度: [{done}/{total}] ({done/total*100:.1f}%)')
            res = f.result()
            if res:
                signals.append(res)

    save_results(signals)

if __name__ == '__main__':
    main()