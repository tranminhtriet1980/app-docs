"""Remove ds260_final template — use EB3 template as default."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from sqlalchemy import select, update

from app.config import settings
from app.database import async_session
from app.models.entities import Export, FormTemplate

DS260_FINAL_ID = uuid.UUID("d8fd94ec292c4d6ea5ac01aed5662543")
EB3_TEMPLATE_ID = uuid.UUID("2b1c93bafc124e35be73b7295a7a5c45")


async def main() -> None:
    async with async_session() as db:
        await db.execute(
            update(Export).where(Export.template_id == DS260_FINAL_ID).values(template_id=EB3_TEMPLATE_ID)
        )
        tpl = await db.get(FormTemplate, DS260_FINAL_ID)
        if tpl:
            await db.delete(tpl)
            print("Deleted form_templates row: ds260_final")
        else:
            print("ds260_final template row not found")

        disk = settings.templates_path / "ds260_final.docx"
        if disk.is_file():
            disk.unlink()
            print(f"Deleted file: {disk}")
        else:
            print("ds260_final.docx not on disk")

        await db.commit()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
