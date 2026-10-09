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
                'name': f"策略 {key}",
                'latest_csv': f"results/{key}_latest.csv" # 預設對應的 csv 命名慣例
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

def update_readme_summary():
    readme_path = "README.md"
    if not os.path.exists(readme_path):
        print("⚠️ 未找到 README.md，無法更新摘要。")
        return

    strategy_config = get_strategy_configs()
    today_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    markdown_content = f"## 📊 各策略最新掃描結果摘要（更新時間：{today_str}）\n\n"

    for key, info in strategy_config.items():
        markdown_content += f"### 🔹 {info['name']}\n"
        csv_path = info['latest_csv']
        
        # 模糊搜尋 results 目錄下是否有包含該策略關鍵字的 CSV 檔案
        if not os.path.exists(csv_path) and os.path.exists("results"):
            matched = [os.path.join("results", f) for f in os.listdir("results") if key.lower() in f.lower() and f.endswith(".csv")]
            if matched:
                csv_path = sorted(matched)[-1]

        if os.path.exists(csv_path):
            try:
                df = pd.read_csv(csv_path)
                if df.empty:
                    markdown_content += "_今日無符合篩選條件之標的_\n\n"
                else:
                    display_cols = [col for col in df.columns if not col.startswith('Unnamed')][:8]
                    top_df = df[display_cols].head(5)
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
        print("✅ 已成功將所有策略結果更新至 README.md！")
    else:
        print("⚠️ README.md 缺少標籤，正在自動補全...")
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
