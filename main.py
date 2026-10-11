import sys
import os
import subprocess
import pandas as pd
from datetime import datetime

def get_strategy_configs():
    """動態掃描 strategies/ 資料夾下的所有 .py 策略檔案"""
    strategies_dir = "strategies"
    configs = {}
    
    if not os.path.exists(strategies_dir):
        print(f"⚠️ 找不到 {strategies_dir} 資料夾！")
        return configs

    for f in sorted(os.listdir(strategies_dir)):
        if f.endswith(".py") and not f.startswith("_"):
            key = f.replace(".py", "")
            configs[key] = {
                'script': os.path.join(strategies_dir, f),
                'name': f"策略 {key}"
            }
    return configs

def run_script(script_path):
    if not os.path.exists(script_path):
        print(f"⚠️ 找不到腳本: {script_path}，跳過執行。")
        return False
    
    print(f"\n🚀 開始執行策略: {script_path} ...")
    try:
        subprocess.run([sys.executable, script_path], check=True)
        print(f"✅ {script_path} 執行成功！")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {script_path} 執行失敗，錯誤碼: {e.returncode}")
        return False

def find_latest_csv(key):
    """靈活比對 results/ 目錄下與策略最相符的 latest CSV"""
    results_dir = "results"
    if not os.path.exists(results_dir):
        return None

    csv_files = [f for f in os.listdir(results_dir) if f.endswith(".csv")]
    if not csv_files:
        return None

    clean_key = key.lower().replace("_", "").replace("etf", "")
    
    candidates = []
    for f in csv_files:
        clean_f = f.lower().replace("_", "").replace("-", "")
        if "latest" in f.lower() and (clean_key in clean_f or key.lower() in f.lower()):
            candidates.append(os.path.join(results_dir, f))

    if not candidates:
        for f in csv_files:
            clean_f = f.lower().replace("_", "")
            if clean_key in clean_f or key.lower() in f.lower():
                candidates.append(os.path.join(results_dir, f))

    if candidates:
        return sorted(candidates)[-1]
    
    return None

def update_readme_summary():
    readme_path = "README.md"
    if not os.path.exists(readme_path):
        print("⚠️ 未找到 README.md，無法更新摘要。")
        return

    strategy_config = get_strategy_configs()
    today_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    markdown_content = f"## 📊 各策略最新掃描結果與訊號篩選（更新時間：{today_str}）\n\n"
    markdown_content += "> 💡 **提示**：以下表格自動彙整自 `results/`，並已針對 **Buy / Watch / Sell** 訊號進行篩選與優先排序。\n\n"

    for key, info in strategy_config.items():
        markdown_content += f"### 🔹 {info['name']}\n"
        csv_path = find_latest_csv(key)

        if csv_path and os.path.exists(csv_path):
            try:
                df = pd.read_csv(csv_path)
                if df.empty:
                    markdown_content += "_今日無符合篩選條件之標的_\n\n"
                else:
                    # 尋找可能代表訊號的欄位
                    signal_cols = [c for c in df.columns if any(k in c.lower() for k in ['buy', 'watch', 'sell', 'action', 'signal', 'status'])]
                    
                    # 如果有訊號欄位，嘗試過濾掉空值或純粹無訊號的列（保留包含 buy/watch/sell 或非空的訊號）
                    filtered_df = df.copy()
                    if signal_cols:
                        # 挑選第一個主要的訊號欄位進行過濾展示，或者保留有訊號動作的列
                        s_col = signal_cols[0]
                        # 僅保留有意義的訊號（非 NaN、非空字串、非 0 / False / None）
                        filtered_df = filtered_df[filtered_df[s_col].notna() & (filtered_df[s_col].astype(str).str.strip() != '')]
                        # 如果過濾後有資料，優先顯示；若過濾後空了，則退回顯示前幾筆或提示
                        if filtered_df.empty:
                            filtered_df = df.head(5) # 若無特定 buy/watch 字眼但有產出，顯示前5筆
                    else:
                        filtered_df = df.head(10)

                    if filtered_df.empty:
                        markdown_content += "_今日無 Buy / Watch / Sell 訊號標的_\n\n"
                    else:
                        # 調整欄位順序：將 Buy, Watch, Action, 股票代號等優先排在前面
                        all_cols = list(filtered_df.columns)
                        priority_cols = [c for c in all_cols if any(k in c.lower() for k in ['buy', 'watch', 'sell', 'action', 'signal', '代號', '股票', 'symbol', 'name', 'status'])]
                        other_cols = [c for c in all_cols if c not in priority_cols and not c.startswith('Unnamed')]
                        
                        final_cols = (priority_cols + other_cols)[:8]
                        top_df = filtered_df[final_cols].head(15)
                        markdown_content += top_df.to_markdown(index=False) + "\n\n"
            except Exception as e:
                markdown_content += f"_讀取結果 CSV 失敗: {e}_\n\n"
        else:
            markdown_content += "_尚未產出結果或無資料_\n\n"

    with open(readme_path, "r", encoding="utf-8") as f:
        content = f.read()

    start_marker = "<!-- STRATEGY_RESULTS_START -->"
    end_marker = "<!-- STRATEGY_RESULTS_END -->"

    if start_marker in content and end_marker in content:
        before = content.split(start_marker)[0]
        after = content.split(end_marker)[1]
        new_content = f"{before}{start_marker}\n\n{markdown_content}{end_marker}{after}"

        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        print("✅ 已成功將過濾後的 Buy/Watch 策略結果更新至 README.md！")
    else:
        with open(readme_path, "a", encoding="utf-8") as f:
            f.write("\n\n<!-- STRATEGY_RESULTS_START -->\n<!-- STRATEGY_RESULTS_END -->\n")
        update_readme_summary()

def main():
    strategy_config = get_strategy_configs()
    target = sys.argv[1] if len(sys.argv) > 1 else 'ALL'
    print(f"🎯 執行目標策略: {target}")

    if target.upper() == 'ALL':
        for key, info in strategy_config.items():
            run_script(info['script'])
    elif target in strategy_config:
        run_script(strategy_config[target]['script'])
    else:
        print(f"❌ 未知的策略標籤: {target}")
        sys.exit(1)

    update_readme_summary()

if __name__ == "__main__":
    main()
