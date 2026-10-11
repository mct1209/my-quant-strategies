import sys
import os
import subprocess
import glob
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

def clean_old_results():
    """自動清除 results/ 資料夾中所有舊的 CSV 檔案，僅保留帶有 latest 的最新結果"""
    results_dir = "results"
    if not os.path.exists(results_dir):
        return

    print("🧹 [自動清理] 正在檢查並刪除 results/ 中的舊 CSV 檔案...")
    csv_files = glob.glob(os.path.join(results_dir, "*.csv"))
    
    for file_path in csv_files:
        filename = os.path.basename(file_path)
        # 只要檔名中不包含 'latest'，一律刪除，確保 GitHub 上永遠只有最新檔案
        if "latest" not in filename.lower():
            try:
                os.remove(file_path)
                print(f"🗑️ 已刪除舊結果: {filename}")
            except Exception as e:
                print(f"⚠️ 無法刪除 {filename}: {e}")

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
                    signal_cols = [c for c in df.columns if any(k in c.lower() for k in ['buy', 'watch', 'sell', 'action', 'signal', 'status'])]
                    
                    filtered_df = df.copy()
                    if signal_cols:
                        s_col = signal_cols[0]
                        filtered_df = filtered_df[filtered_df[s_col].notna() & (filtered_df[s_col].astype(str).str.strip() != '')]
                        if filtered_df.empty:
                            filtered_df = df.head(5)
                    else:
                        filtered_df = df.head(10)

                    if filtered_df.empty:
                        markdown_content += "_今日無 Buy / Watch / Sell 訊號標的_\n\n"
                    else:
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
    # 每次執行前（包含 GitHub Actions 自動執行），先自動清理舊的非 latest 歷史結果檔
    clean_old_results()

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
