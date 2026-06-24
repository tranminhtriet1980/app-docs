"""Remove stale marriage_certificate OCR when file was deleted (wrong test upload)."""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import delete, select

from app.database import async_session
from app.models.entities import ApplicantDocRecord, Document

DANG_CASE_ID = uuid.UUID("3f685c8973d5403a83f5ed42f80c7f4d")


async def main() -> None:
    async with async_session() as db:
        docs = await db.execute(
            select(Document).where(
                Document.applicant_id == DANG_CASE_ID,
                Document.registry_doc_type == "marriage_certificate",
            )
        )
        for doc in docs.scalars():
            await db.delete(doc)
            print(f"Deleted document: {doc.original_filename}")

        result = await db.execute(
            delete(ApplicantDocRecord).where(
                ApplicantDocRecord.applicant_id == DANG_CASE_ID,
                ApplicantDocRecord.doc_type == "marriage_certificate",
            )
        )
        print(f"Deleted marriage_certificate doc records: {result.rowcount}")
        await db.commit()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
