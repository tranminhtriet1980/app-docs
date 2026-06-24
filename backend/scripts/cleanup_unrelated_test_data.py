"""Xóa hồ sơ test không liên quan và dọn dữ liệu sai trong hồ sơ DANG VAN HUNG."""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select

from app.database import async_session
from app.models.entities import Applicant, CaseMember, Document


DANG_CASE_ID = uuid.UUID("3f685c8973d5403a83f5ed42f80c7f4d")
TRUONG_CASE_ID = uuid.UUID("f200a4bbeb7e43b4b9564d22d7da8b22")
WRONG_MARRIAGE_FILENAMES = {"Marriage Certificate.pdf", "marriage certificate.pdf"}


async def cleanup() -> None:
    async with async_session() as db:
        truong = await db.get(Applicant, TRUONG_CASE_ID)
        if truong:
            print(f"DELETE test case: {truong.display_name} ({TRUONG_CASE_ID})")
            await db.delete(truong)
        else:
            print("TRUONG case not found")

        hung = await db.get(Applicant, DANG_CASE_ID)
        if not hung:
            print("DANG case not found")
            await db.commit()
            return

        spouse_rows = await db.execute(
            select(CaseMember).where(
                CaseMember.applicant_id == DANG_CASE_ID,
                CaseMember.role == "spouse",
            )
        )
        for member in spouse_rows.scalars():
            print(f"DELETE wrong spouse: {member.display_name}")
            await db.delete(member)

        principal_rows = await db.execute(
            select(CaseMember).where(
                CaseMember.applicant_id == DANG_CASE_ID,
                CaseMember.role == "principal",
            )
        )
        principal = principal_rows.scalar_one_or_none()
        hung.display_name = "DANG VAN HUNG"
        if principal:
            principal.display_name = "DANG VAN HUNG"
            print("Fixed principal -> DANG VAN HUNG")

        doc_rows = await db.execute(select(Document).where(Document.applicant_id == DANG_CASE_ID))
        for doc in doc_rows.scalars():
            if doc.original_filename in WRONG_MARRIAGE_FILENAMES:
                print(f"DELETE unrelated marriage cert: {doc.original_filename}")
                await db.delete(doc)

        await db.commit()
        print("Cleanup done.")


if __name__ == "__main__":
    asyncio.run(cleanup())
