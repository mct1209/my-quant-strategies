#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
============================================================================================
TW STOCK + ETF SIGNAL V6.0 (Institutional Quant Edition - GitHub Actions Optimized)
============================================================================================
"""

import os
import re
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import StringIO
import numpy as np
import pandas as pd
import requests
import yfinance as yf

warnings.filterwarnings('ignore')

VERSION = 'TW Stock ETF Signal V6.0 (Quant Master)'

# 雲端執行輸出目錄 (專案內 results 資料夾)
OUTPUT_DIR = os.path.join(os.getcwd(), 'results')

# 透過環境變數取得篩選模式 (預設 ALL: 顯示 BUY / WATCH / SELL)
# 可選模式: "ALL", "BUY", "WATCH", "SELL"
FILTER_MODE = os.environ.get('FILTER_MODE', 'ALL').upper()

# 網址設定
RANK_URL = (
    'https://www.moneydj.com/ETF/X/Rank/Rank0001.xdjhtm'
    '?eRank=up&eOrd=t800500&eMid=TW&eArea=47&eTarget=0&eCoin=0&eTWcoin=0&ePeriod=1D&eTab=2'
)

# 系統參數
MAX_WORKERS = 4
REQUEST_SLEEP = 0.15
MIN_BARS = 120

# 技術分析濾網參數 (Quant Filter Criteria)
BIAS_BUY_MAX, BIAS_WATCH_MAX = 5.0, 7.5
VOL_MIN, VOL_MAX, VOL_HARD_MAX = 1.30, 3.50, 4.00
ETF_VOL_MIN, ETF_ADX_MIN, BREADTH_MIN = 1.10, 15, 0.30
RSI_MIN, RSI_MAX, ADX_MIN = 50, 78, 16
ATR_PERIOD, ATR_STOP_MULT, TARGET_R = 14, 1.50, 2.00
BUY_SCORE_MIN, WATCH_SCORE_MIN, TOP_N = 75, 62, 50

CORE = ['2330', '2454', '2383', '3037', '3017', '2059', '3653']

SESSION = requests.Session()
SESSION.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json,text/plain,*/*',
})

SNAPSHOT = [
    ('00913', '兆豐台灣晶圓製造', 14.06), ('00733', '富邦臺灣中小', 11.27), ('020040', '元大上櫃ESG龍頭N', 10.77),
    ('020000', '富邦特選蘋果N', 10.43), ('00927', '群益半導體收益', 10.26), ('00935', '野村臺灣新科技50', 10.14),
    ('00888', '永豐台灣ESG', 9.53), ('00891', '中信關鍵半導體', 9.07), ('00904', '台新臺灣半導體30', 8.12),
    ('00894', '中信小資高價30', 7.33), ('00947', '台新臺灣IC設計', 7.31), ('0050', '元大台灣50', 5.80),
    ('006208', '富邦台50', 5.79), ('00850', '元大臺灣ESG永續', 5.75), ('00922', '國泰台灣領袖50', 5.13)
]

def strategy_classifier(code, name):
    n = str(name)
    c = str(code)
    if c.startswith('0200'):
        return 'ETN', '指標證券，追蹤籃子，無實體資產不建議長期持有'
    if c.endswith('A') or '主動' in n:
        return '主動ETF', '無固定指數，依基金經理人選股'
    if any(k in n for k in ('晶圓', '半導體', 'IC設計')):
        return '半導體主題', '聚焦半導體產業鏈'
    if any(k in n for k in ('ESG', '淨零', '綠能', '公司治理')):
        return 'ESG/永續', 'ESG篩選後進行市值/股息加權'
    if any(k in n for k in ('中小', '富櫃', '高價')):
        return '中小型股', '鎖定中小型股爆發力'
    if any(k in n for k in ('高息', '高股息', '優息')):
        return '高股息因子', '重視現金流，非典型動能突破標的'
    if any(k in n for k in ('台灣50', '台50', '摩台', '加權', 'MSCI台灣', '藍籌', '領袖')):
        return '寬基市值型', '追蹤大盤大市值標的'
    return '主題/因子型', '請參照公開說明書'

def excluded_filter(code, name):
    text = f'{code}{name}'
    if re.search(r'[LR]$', str(code)) or any(k in text for k in ('正2', '正二', '反1', '反一', '槓桿')):
        return '槓桿/反向標的'
    return ''

def fetch_rank():
    try:
        r = SESSION.get(RANK_URL, timeout=15)
        r.raise_for_status()
        dfs = pd.read_html(StringIO(r.text))
        df = max(dfs, key=len)
        df.columns = [str(c).strip() for c in df.columns]

        code_col = next(c for c in df.columns if '代碼' in c or 'Code' in c)
        name_col = next(c for c in df.columns if '名稱' in c or 'Name' in c)
        month_col = next(c for c in df.columns if '一個月' in c or '1M' in c)

        out = df[[code_col, name_col, month_col]].copy()
        out.columns = ['代碼', '名稱', '一個月']
        out['一個月'] = pd.to_numeric(out['一個月'].astype(str).str.replace(',', '', regex=False), errors='coerce')
        out = out.dropna(subset=['代碼', '一個月'])
    except Exception as e:
        print(f'[排名] MoneyDJ 抓取失敗 ({e})，啟動 2026 備用快照...')
        out = pd.DataFrame(SNAPSHOT, columns=['代碼', '名稱', '一個月'])

    out['剔除'] = [excluded_filter(c, n) for c, n in zip(out['代碼'], out['名稱'])]
    kept = out[out['剔除'] == ''].sort_values('一個月', ascending=False).head(TOP_N).reset_index(drop=True)

    rows = []
    for i, row in kept.iterrows():
        style, logic = strategy_classifier(row['代碼'], row['名稱'])
        suffix = '.TWO' if str(row['代碼']) in {'006201', '006204'} else '.TW'
        rows.append({
            'ticker': f"{row['代碼']}{suffix}",
            'name': row['名稱'],
            '類別': 'ETF',
            '策略': style,
            '邏輯': logic,
            '一個月': row['一個月'],
            '近月名次': i + 1
        })
    return rows

def is_ordinary_stock(code):
    c = str(code).strip()
    return c.isdigit() and len(c) == 4 and not c.startswith(('00', '01'))

def fetch_json_safe(url):
    try:
        r = SESSION.get(url, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f'[API Error] {url}: {e}')
        return []

def get_stocks():
    rows = []
    data_twse = fetch_json_safe('https://openapi.twse.com.tw/v1/opendata/t187ap03_L')
    for r in data_twse:
        code = r.get('公司代號') or r.get('Code')
        name = r.get('公司簡稱') or r.get('Name') or r.get('公司名稱')
        if code and name and is_ordinary_stock(code):
            rows.append({
                'ticker': f'{code}.TW', 'name': str(name).strip(),
                '類別': '個股', '策略': '上市普通股', '邏輯': '突破動能',
                '一個月': np.nan, '近月名次': np.nan
            })

    data_tpex = fetch_json_safe('https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O')
    for r in data_tpex:
        code = r.get('SecuritiesCompanyCode') or r.get('CompanyCode')
        name = r.get('CompanyAbbreviation') or r.get('CompanyName')
        if code and name and is_ordinary_stock(code):
            rows.append({
                'ticker': f'{code}.TWO', 'name': str(name).strip(),
                '類別': '個股', '策略': '上櫃普通股', '邏輯': '突破動能',
                '一個月': np.nan, '近月名次': np.nan
            })

    return list({r['ticker']: r for r in rows}.values())

def compute_rsi(close, p=14):
    d = close.diff()
    gain = d.clip(lower=0).ewm(alpha=1/p, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1/p, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def compute_adx(df, p=14):
    up = df['High'].diff()
    dn = -df['Low'].diff()
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)

    pc = df['Close'].shift(1)
    tr = pd.concat([
        df['High'] - df['Low'],
        (df['High'] - pc).abs(),
        (df['Low'] - pc).abs()
    ], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1/p, adjust=False).mean()
    pdi = 100 * plus_dm.ewm(alpha=1/p, adjust=False).mean() / atr.replace(0, np.nan)
    mdi = 100 * minus_dm.ewm(alpha=1/p, adjust=False).mean() / atr.replace(0, np.nan)

    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    adx_val = dx.ewm(alpha=1/p, adjust=False).mean()
    return adx_val, pdi, mdi

def prepare_indicators(df):
    df = df.copy()
    df['MA20'] = df['Close'].rolling(20).mean()
    df['MA60'] = df['Close'].rolling(60).mean()

    pc = df['Close'].shift(1)
    tr = pd.concat([
        df['High'] - df['Low'],
        (df['High'] - pc).abs(),
        (df['Low'] - pc).abs()
    ], axis=1).max(axis=1)

    df['ATR'] = tr.rolling(ATR_PERIOD).mean()
    df['RSI'] = compute_rsi(df['Close'])

    ema12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['MACD_SIGNAL'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_HIST'] = df['MACD'] - df['MACD_SIGNAL']

    df['ADX'], df['PLUS_DI'], df['MINUS_DI'] = compute_adx(df)
    df['VOL_RATIO'] = df['Volume'] / df['Volume'].rolling(20).mean().replace(0, np.nan)
    df['HIGH20_PREV'] = df['High'].rolling(20).max().shift(1)
    return df

def download_data(ticker):
    for attempt in range(3):
        try:
            df = yf.download(ticker, period='1y', interval='1d', auto_adjust=True, progress=False, threads=False)
            if df is None or df.empty:
                raise ValueError("DataFrame is Empty")

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            cols = ['Open', 'High', 'Low', 'Close', 'Volume']
            if not all(c in df.columns for c in cols):
                raise ValueError("Missing Columns")

            df = df[cols].apply(pd.to_numeric, errors='coerce').dropna()
            if len(df) < MIN_BARS:
                return None
            return prepare_indicators(df)
        except Exception:
            time.sleep(0.3 * (attempt + 1))
    return None

def analyze_signal(df):
    row = df.iloc[-1]
    close, high, low, op = float(row.Close), float(row.High), float(row.Low), float(row.Open)
    ma20, ma60, atr = float(row.MA20), float(row.MA60), float(row.ATR)
    rsi_v, adx_v, vr = float(row.RSI), float(row.ADX), float(row.VOL_RATIO)

    if min(close, high, low, ma20, ma60, atr) <= 0 or pd.isna(vr):
        return None

    bias = ((close / ma20) - 1) * 100
    rng = high - low
    cp = (close - low) / rng if rng > 0 else 0
    ush = (high - max(op, close)) / rng if rng > 0 else 0

    breakout_20 = close >= float(row.HIGH20_PREV)
    bull_align = (close > ma20 > ma60) and (float(row.MACD_HIST) > 0) and (float(row.PLUS_DI) > float(row.MINUS_DI))

    score = 0
    score += 15 if breakout_20 else 0
    score += 10 if close > ma20 else 0
    score += 10 if ma20 > ma60 else 0
    score += 15 if (RSI_MIN <= rsi_v <= RSI_MAX) else 0
    score += 15 if (VOL_MIN <= vr <= VOL_MAX) else 0
    score += 10 if cp >= 0.60 else 0
    score += 10 if ush <= 0.30 else 0
    score += 10 if bias <= 4.0 else 0
    score += 5 if adx_v >= ADX_MIN else 0

    stop_price = close - (ATR_STOP_MULT * atr)
    target_price = close + (TARGET_R * ATR_STOP_MULT * atr)

    base_info = {
        '分數': score,
        '最新收盤': round(close, 2),
        'RSI': round(rsi_v, 2),
        'ADX': round(adx_v, 2),
        '量能倍數': round(vr, 2),
        'MA20乖離%': round(bias, 2),
        '建議停損價': round(stop_price, 2),
        '目標獲利價': round(target_price, 2)
    }

    if (close < ma20 and ma20 < ma60) or (rsi_v < 40):
        return {**base_info, '動作': 'SELL', '理由': '跌破均線或RSI動能散失'}
    if rsi_v > 82 or bias > BIAS_WATCH_MAX:
        return {**base_info, '動作': 'SELL', '理由': '指標嚴重過熱或乖離過高'}

    if breakout_20 and bull_align and (cp >= 0.50) and (vr <= VOL_HARD_MAX):
        if score >= BUY_SCORE_MIN and bias <= BIAS_BUY_MAX:
            action = 'BUY'
        elif score >= WATCH_SCORE_MIN:
            action = 'WATCH'
        else:
            action = None

        if action:
            return {**base_info, '動作': action, '理由': '強勢突破20日高點且多頭排列'}

    return None

def check_market_breadth(cache):
    hit = 0
    valid_count = 0
    for code in CORE:
        ticker = f'{code}.TW'
        df = cache.get(ticker) or download_data(ticker)
        cache[ticker] = df
        if df is not None:
            valid_count += 1
            row = df.iloc[-1]
            if float(row.Close) > float(row.MA20) > float(row.MA60):
                hit += 1
    return (hit / valid_count) if valid_count > 0 else 0.0

def scan_worker(item, market_ok, core_ratio):
    time.sleep(REQUEST_SLEEP)
    df = download_data(item['ticker'])
    if df is None:
        return None

    info = analyze_signal(df)
    if not info:
        return None

    if not market_ok and info['動作'] == 'BUY':
        info['動作'] = 'WATCH'
        info['理由'] += ' | (大盤未達多頭趨勢，強制降級)'

    reasons = []
    if item['類別'] == 'ETF':
        if item['策略'] == 'ETN':
            reasons.append('ETN不建議操作')
        if info['動作'] == 'BUY' and info['ADX'] < ETF_ADX_MIN:
            reasons.append('ADX趨勢力道不足')
        if info['動作'] == 'BUY' and info['量能倍數'] < ETF_VOL_MIN:
            reasons.append('ETF成交量能不足')
        if '主動' in item['策略'] and core_ratio < BREADTH_MIN:
            reasons.append('權值核心廣度不足')

    if reasons and info['動作'] == 'BUY':
        info['動作'] = 'WATCH'
        info['理由'] += ' | ' + ' | '.join(reasons)

    raw_action = info['動作']
    symbol_code = item['ticker'].split('.')[0]

    if raw_action == 'BUY':
        signal_icon = f"🔥 {raw_action}"
    elif raw_action == 'WATCH':
        signal_icon = f"👀 {raw_action}"
    elif raw_action == 'SELL':
        signal_icon = f"⚠️ {raw_action}"
    else:
        signal_icon = raw_action

    return {
        '代碼': symbol_code,
        '名稱': item['name'],
        '訊號': signal_icon,
        'raw_action': raw_action,
        '類別': item['類別'],
        '策略': item['策略'],
        '分數': info['分數'],
        '最新收盤': info['最新收盤'],
        '建議停損價': info['建議停損價'],
        '目標獲利價': info['目標獲利價'],
        '觸發原因': info['理由'],
        '操作建議': 'T+1開盤進場，若跳空開高>2.5%放棄；觸及停損價無條件執行'
    }

def save_results(results):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = pd.Timestamp.now().strftime('%Y%m%d')

    filtered_results = []
    for r in results:
        raw_act = r.get('raw_action', '')
        if FILTER_MODE == 'BUY' and raw_act == 'BUY':
            filtered_results.append(r)
        elif FILTER_MODE == 'WATCH' and raw_act == 'WATCH':
            filtered_results.append(r)
        elif FILTER_MODE == 'SELL' and raw_act == 'SELL':
            filtered_results.append(r)
        elif FILTER_MODE == 'ALL':
            filtered_results.append(r)

    df_res = pd.DataFrame(filtered_results)
    if not df_res.empty and 'raw_action' in df_res.columns:
        df_res = df_res.drop(columns=['raw_action'])

    sig_csv = os.path.join(OUTPUT_DIR, f'tw_stock_etf_{FILTER_MODE.lower()}_{timestamp}.csv')
    latest_csv = os.path.join(OUTPUT_DIR, 'tw_stock_etf_latest.csv')

    if not df_res.empty:
        df_res.to_csv(sig_csv, index=False, encoding='utf-8-sig')
        df_res.to_csv(latest_csv, index=False, encoding='utf-8-sig')
    else:
        empty_df = pd.DataFrame([{"說明": f"今日無符合 {FILTER_MODE} 條件之訊號"}])
        empty_df.to_csv(sig_csv, index=False, encoding='utf-8-sig')
        empty_df.to_csv(latest_csv, index=False, encoding='utf-8-sig')

    print(f"\n[完成] 策略 TW Stock ETF Signal V6.0 掃描完畢 (過濾模式: {FILTER_MODE})，結果已寫入 {latest_csv}")

def main():
    print("=" * 60)
    print(f"{VERSION} 啟動掃描引擎")
    print(f"當前指定過濾模式: {FILTER_MODE}")
    print("=" * 60)

    etfs = fetch_rank()
    stocks = get_stocks()
    universe = stocks + etfs
    print(f"掃描標的總數：{len(universe)} 檔 (個股 + ETF)")

    bench_df = download_data('0050.TW')
    market_ok = False
    if bench_df is not None:
        b_row = bench_df.iloc[-1]
        market_ok = float(b_row.Close) > float(b_row.MA20) > float(b_row.MA60)

    print(f"0050 大盤狀態：{'多頭環境 (允許BUY)' if market_ok else '防禦/震盪 (強制降級為 WATCH)'}")

    data_cache = {}
    core_ratio = check_market_breadth(data_cache)
    print(f"核心權值股多頭排列比例：{core_ratio:.1%}")

    results = []
    print("開始執行全市場掃描...")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(scan_worker, item, market_ok, core_ratio) for item in universe]
        for n, f in enumerate(as_completed(futures), 1):
            if n % 200 == 0 or n == len(universe):
                print(f"掃描進度: {n}/{len(universe)} ({n/len(universe):.1%})")
            res = f.result()
            if res:
                results.append(res)

    save_results(results)

if __name__ == '__main__':
    main()