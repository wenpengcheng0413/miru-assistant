"""Test PyWxDump key extraction for WeChat 4.1.11.53."""
import json
import sys

print("=== PyWxDump Key Extraction Test ===")
print()

# Try top-level function
try:
    from pywxdump import get_wx_info
    print("[1] Trying pywxdump.get_wx_info()...")
    info = get_wx_info()
    print(f"  Result type: {type(info)}")
    print(f"  Result: {json.dumps(info, indent=2, ensure_ascii=False, default=str)[:2000]}")

    if info:
        with open("data/wechat_keys.json", "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False, indent=2, default=str)
        print("  Keys saved to data/wechat_keys.json")
    else:
        print("  FAILED: No accounts found")
        print()
        print("[2] Trying pywxdump.get_core_db()...")
        from pywxdump import get_core_db
        db_info = get_core_db()
        print(f"  Result: {json.dumps(db_info, indent=2, ensure_ascii=False, default=str)[:2000]}")
except Exception as e:
    print(f"  ERROR: {e}")
    import traceback
    traceback.print_exc()
