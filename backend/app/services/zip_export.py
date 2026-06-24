import io
import zipfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Document


async def build_applicant_zip(db: AsyncSession, applicant_id) -> tuple[bytes, str]:
    result = await db.execute(
        select(Document).where(Document.applicant_id == applicant_id).order_by(Document.uploaded_at)
    )
    documents = result.scalars().all()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, doc in enumerate(documents):
            path = Path(doc.file_path)
            if path.exists():
                arcname = f"{i + 1:02d}_{doc.original_filename}"
                zf.write(path, arcname=arcname)
    buf.seek(0)
    return buf.getvalue(), f"ho_so_{applicant_id}.zip"
