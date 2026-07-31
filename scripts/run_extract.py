"""Extract WeChat 4.1.x keys using PyWxDump."""
import json
import psutil
from pywxdump.wx_core.wx_info import get_info_details
from pywxdump import WX_OFFS

print("=== Searching for WeChat processes ===")
pids = []
for p in psutil.process_iter(['pid', 'name']):
    try:
        n = (p.info['name'] or '').lower()
        if n in ('wechat.exe', 'weixin.exe'):
            pids.append(p.info['pid'])
            print(f"Found: {p.info['name']} PID={p.info['pid']}")
    except Exception:
        pass

if not pids:
    print("ERROR: No WeChat process found!")
    exit(1)

for pid in pids:
    try:
        info = get_info_details(pid, WX_OFFS)
        if info:
            print(f"\n=== Account (PID={pid}) ===")
            for k, v in info.items():
                val = str(v)
                if 'key' in k.lower():
                    print(f"  {k}: {val[:20]}...{val[-8:]}")
                else:
                    print(f"  {k}: {val}")

            import os
            os.makedirs("data", exist_ok=True)
            with open("data/wechat_keys.json", "w", encoding="utf-8") as f:
                json.dump([info], f, ensure_ascii=False, indent=2, default=str)
            print(f"\nSaved to data/wechat_keys.json")
    except Exception as e:
        print(f"  PID={pid} ERROR: {e}")
