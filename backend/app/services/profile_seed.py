"""Apply bundled DS-160 seed data to fill empty profile fields."""

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import ProfileField
from app.services.field_mapping import PROFILE_SECTIONS

CANONICAL_PROFILE_KEYS = {key for keys in PROFILE_SECTIONS.values() for key in keys}

SEED_DIR = Path(__file__).resolve().parents[2] / "data"


def list_seeds() -> list[str]:
    if not SEED_DIR.is_dir():
        return []
    return sorted(p.stem.replace("ds160_seed_", "") for p in SEED_DIR.glob("ds160_seed_*.json"))


def load_seed(name: str) -> dict[str, str]:
    path = SEED_DIR / f"ds160_seed_{name}.json"
    if not path.is_file():
        path = SEED_DIR / f"{name}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Seed not found: {name}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {k: str(v) for k, v in raw.items() if v is not None and str(v).strip()}


async def apply_profile_seed(
    db: AsyncSession,
    applicant_id: UUID,
    seed_name: str,
    *,
    fill_empty_only: bool = True,
) -> dict[str, int]:
    fields = load_seed(seed_name)
    valid = {k: v for k, v in fields.items() if k in CANONICAL_PROFILE_KEYS}

    result = await db.execute(
        select(ProfileField).where(ProfileField.applicant_id == applicant_id)
    )
    existing = {pf.field_key: pf for pf in result.scalars().all()}

    added = 0
    updated = 0
    skipped = 0
    now = datetime.now(timezone.utc)

    for key, value in valid.items():
        pf = existing.get(key)
        if pf:
            current = (pf.field_value or "").strip()
            if fill_empty_only and current:
                skipped += 1
                continue
            pf.field_value = value
            pf.is_manual = True
            pf.updated_at = now
            updated += 1
        else:
            db.add(
                ProfileField(
                    applicant_id=applicant_id,
                    field_key=key,
                    field_value=value,
                    is_manual=True,
                )
            )
            added += 1

    await db.flush()
    return {"added": added, "updated": updated, "skipped": skipped, "total_seed": len(valid)}
