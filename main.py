import sys
import os

def main():
    # 取得命令列參數（預設為 ALL）
    target_strategy = sys.argv[1] if len(sys.argv) > 1 else "ALL"
    filter_mode = os.getenv("FILTER_MODE", "ALL")
    
    print(f"=== 啟動量化策略引擎 ===")
    print(f"目標策略: {target_strategy}")
    print(f"過濾模式: {filter_mode}")
    print("=" * 30)

    # 建立輸出目錄
    os.makedirs("results", exist_ok=True)

    # 執行策略邏輯
    if target_strategy in ["ALL", "v3_10"]:
        print("--> 執行策略: v3_10")
        os.system("python strategies/v3_10.py")

    if target_strategy in ["ALL", "v6_6_ETF"]:
        print("--> 執行策略: v6_6_ETF")
        os.system("python strategies/v6_6_ETF.py")

    if target_strategy in ["ALL", "v6_0"]:
        print("--> 執行策略: v6_0")
        os.system("python strategies/v6_0.py")

    if target_strategy in ["ALL", "v5_73_ETF"]:
        print("--> 執行策略: v5_73_ETF")
        os.system("python strategies/v5_73_ETF.py")

    if target_strategy in ["ALL", "v5_6"]:
        print("--> 執行策略: v5_6")
        os.system("python strategies/v5_6.py")

    print("=== 所有策略計算完畢 ===")

if __name__ == "__main__":
    main()
