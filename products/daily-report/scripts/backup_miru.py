"""Miru Assistant - Key file backup script."""
import shutil
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
BACKUP_DIR = PROJECT / "backup" / datetime.now().strftime("%Y%m%d")
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

FILES = {
    PROJECT / "config" / "settings.yaml": "CRITICAL - API keys, database key, groups",
    PROJECT / "data" / "miru.db": "Daily reports, message dedup cache",
    PROJECT / "scripts" / "run_daily.py": "Auto-run entry point",
    PROJECT / "scripts" / "run_daily.bat": "Auto-run bat wrapper",
    PROJECT / "scripts" / "setup_scheduler.ps1": "Task scheduler installer",
    PROJECT / "pyproject.toml": "Project dependencies",
    Path.home() / ".chatlog" / "chatlog.json": "chatlog key cache",
}

print(f"Miru Backup: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print(f"Target: {BACKUP_DIR}")
print()

for src, desc in FILES.items():
    if src.exists():
        shutil.copy2(src, BACKUP_DIR / src.name)
        print(f"  [OK] {src.name}  ({desc})")
    else:
        print(f"  [MISS] {src.name}  ({desc})")

print()
print(f"Backup complete: {BACKUP_DIR}")
print(f"Files: {len(list(BACKUP_DIR.iterdir()))}")
