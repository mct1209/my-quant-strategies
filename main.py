#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import datetime
import pandas as pd

# 讀取傳入的參數，決定要跑哪個策略（預設跑全部 ALL）
RUN_TARGET = sys.argv[1].lower() if len(sys.argv) > 1 else "all"

OUTPUT_DIR = os.path.join(os.getcwd(), "results")
os.makedirs(OUTPUT_DIR, exist_ok=True)

def generate_combined_readme():
    """彙整所有策略產出的最新 CSV，產生手機首頁極致優化的總覽報告"""
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    root_readme = os.path.join(os.getcwd(), "README.md")

    with open(root_readme, "w", encoding="utf-8") as f:
        f.write("# 📊 量化多策略自動化掃描儀\n\n")
        f.write(f"> **最後更新時間**: `{now_str}` (CST)\n\n")
        f.write("---\n\n")

        csv_files = [x for x in os.listdir(OUTPUT_DIR) if x.endswith("_latest.csv")]

        if not csv_files:
            f.write("> ⚪ 目前尚未生成任何策略結果。\n")
            return

        for csv_file in sorted(csv_files):
            strat_name = csv_file.replace("_latest.csv", "").upper()
            csv_path = os.path.join(OUTPUT_DIR, csv_file)

            try:
                df = pd.read_csv(csv_path)
                f.write(f"### 🎯 策略名稱：`{strat_name}` (共 {len(df)} 檔標的)\n\n")
                if not df.empty:
                    # 選取關鍵欄位供手機快速閱覽
                    show_cols = [c for c in ["代號", "名稱", "訊號", "評分", "現價", "風報比", "觸發原因"] if c in df.columns]
                    if not show_cols:
                        show_cols = df.columns[:6]
                    f.write(df[show_cols].to_markdown(index=False))
                else:
                    f.write("⚪ 今日無符合條件標的。\n")
                f.write("\n\n---\n\n")
            except Exception as e:
                f.write(f"⚠️ 讀取策略 {strat_name} 失敗: {e}\n\n")

if __name__ == "__main__":
    print(f"=== 啟動多策略執行器 (目標策略: {RUN_TARGET}) ===")

    # 策略 1: TPE90_v3.10
    if RUN_TARGET in ["all", "v3_10"]:
        print("\n▶ 正在執行：v3_10 策略...")
        if os.path.exists("strategies/v3_10.py"):
        os.system("python strategies/v3_10.py")

    # 策略 2: TPE_v6.6_ETF
    if RUN_TARGET in ["all", "v6_6_ETF"]:
        print("\n▶ 正在執行：v6_6_ETF...")
        if os.path.exists("strategies/v6_6_ETF.py"):
        os.system("python strategies/v6_6_ETF.py")

    # 策略 3: TPE_v6.0
    if RUN_TARGET in ["all", "v6_0"]:
        print("\n▶ 正在執行：v6_0...")
        if os.path.exists("strategies/v6_0.py"):
        os.system("python strategies/v6_0.py")

    # 策略 4: TPE_v5.73_ETF
    if RUN_TARGET in ["all", "v5_73_ETF"]:
        print("\n▶ 正在執行：v5_73_ETF...")
        if os.path.exists("strategies/v5_73_ETF.py"):
        os.system("python strategies/v5_73_ETF.py")

    # 策略 5: TPE_v5.6
    if RUN_TARGET in ["all", "v5_6"]:
        print("\n▶ 正在執行：v5_6...")
        if os.path.exists("strategies/v5_6.py"):
        os.system("python strategies/v5_6.py")

    # 彙整產出總 Markdown 報告
    generate_combined_readme()
    print("\n[完成] 所有策略掃描完畢，專案首頁 README.md 已更新！")