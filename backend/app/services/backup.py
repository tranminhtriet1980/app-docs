import shutil
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings


def backup_dir() -> Path:
    path = settings.backup_path
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_sqlite_backup() -> dict:
    """Copy SQLite DB file to backups folder."""
    db_url = settings.database_url
    if "sqlite" not in db_url:
        raise ValueError("Backup chỉ hỗ trợ SQLite trong môi trường dev. Production dùng pg_dump.")

    # sqlite+aiosqlite:///./immigration.db
    rel = db_url.split("///")[-1]
    src = Path(rel)
    if not src.is_absolute():
        src = settings.base_dir / rel

    if not src.exists():
        raise FileNotFoundError(f"Database file not found: {src}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = backup_dir() / f"immigration_{ts}.db"
    shutil.copy2(src, dest)
    return {"filename": dest.name, "path": str(dest), "size_bytes": dest.stat().st_size}


def list_backups() -> list[dict]:
    files = sorted(backup_dir().glob("immigration_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [
        {
            "filename": f.name,
            "size_bytes": f.stat().st_size,
            "created_at": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat(),
        }
        for f in files
    ]


def restore_sqlite_backup(filename: str) -> dict:
    if ".." in filename or "/" in filename or "\\" in filename:
        raise ValueError("Invalid filename")
    src = backup_dir() / filename
    if not src.exists():
        raise FileNotFoundError("Backup not found")

    db_url = settings.database_url
    rel = db_url.split("///")[-1]
    dest = Path(rel)
    if not dest.is_absolute():
        dest = settings.base_dir / rel

    # Safety copy before restore
    if dest.exists():
        safety = backup_dir() / f"pre_restore_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.db"
        shutil.copy2(dest, safety)

    shutil.copy2(src, dest)
    return {"restored": filename, "target": str(dest)}
