import sys
import os
import subprocess

def run_strategy(script_name):
    script_path = os.path.join("strategies", script_name)
    if not os.path.exists(script_path):
        print(f"❌ [警告] 找不到檔案: {script_path}，跳過此策略。")
        return

    print(f"\n========================================")
    print(f"🚀 開始執行策略: {script_name}")
    print(f"========================================")
    
    try:
        # 使用 subprocess 執行，避免單一策略報錯導致 main.py 崩潰中斷
        result = subprocess.run(["python", script_path], check=False)
        if result.returncode == 0:
            print(f"✅ 策略 {script_name} 執行成功！")
        else:
            print(f"⚠️ 策略 {script_name} 執行結束，返回非零代碼: {result.returncode}")
    except Exception as e:
        print(f"💥 策略 {script_name} 發生異常: {e}")

def main():
    target_strategy = sys.argv[1] if len(sys.argv) > 1 else "ALL"
    filter_mode = os.getenv("FILTER_MODE", "ALL")
    
    print(f"=== 啟動量化策略整合引擎 ===")
    print(f"目標策略: {target_strategy}")
    print(f"過濾模式: {filter_mode}")
    print("========================================\n")

    os.makedirs("results", exist_ok=True)

    # 定義所有策略檔名清單
    strategy_map = {
        "v3_10": "v3_10.py",
        "v6_6_ETF": "v6_6_ETF.py",
        "v6_0": "v6_0.py",
        "v5_73_ETF": "v5_73_ETF.py",
        "v5_6": "v5_6.py"
    }

    if target_strategy == "ALL":
        for name, script in strategy_map.items():
            run_strategy(script)
    elif target_strategy in strategy_map:
        run_strategy(strategy_map[target_strategy])
    else:
        print(f"❌ 未知的策略名稱: {target_strategy}")

    print("\n========================================")
    print("🎉 所有指定策略計算完畢！")
    print("========================================")

if __name__ == "__main__":
    main()
