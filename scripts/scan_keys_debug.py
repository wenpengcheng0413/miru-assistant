"""Debug: scan WeChat 4.1.x memory for key patterns."""
import re
import pymem

pid = 2360
pm = pymem.Pymem()
pm.open_process_from_id(pid)
modules = list(pm.list_modules())

# Try different hex patterns
patterns = [
    (br"x'[0-9a-fA-F]{96}'", "96-char hex in x'' quotes"),
    (br"'[0-9a-fA-F]{64}'", "64-char hex in quotes"),
]

for module in modules:
    name = getattr(module, 'name', '') or ''
    if name not in ('libwxcodec.dll', 'Weixin.exe'):
        continue
    base = module.lpBaseOfDll
    size = module.SizeOfImage
    print(f"=== {name} ({size/1024/1024:.1f}MB) ===")

    data = b''
    chunk = 5 * 1024 * 1024
    offset = 0
    while offset < size:
        read_size = min(chunk, size - offset)
        try:
            data += pm.read_bytes(base + offset, read_size)
        except Exception:
            pass
        offset += read_size

    for pat, desc in patterns:
        matches = list(re.finditer(pat, data))
        print(f"  {desc}: {len(matches)} matches")

# Search for raw 64-char hex strings (possible keys without x'' wrapper)
# Search entire process memory in key areas
print()
print("=== Searching all memory for hex patterns ===")
# Simple brute: look for 96 consecutive hex chars
hex_pat = re.compile(b"[0-9a-fA-F]{96}")
for module in modules:
    name = getattr(module, 'name', '') or ''
    base = module.lpBaseOfDll
    size = module.SizeOfImage
    try:
        data = pm.read_bytes(base, min(size, 3 * 1024 * 1024))
        matches = list(hex_pat.finditer(data))
        if matches:
            print(f"  {name}: {len(matches)} 96-char hex strings found")
    except Exception:
        pass

print("Done")
