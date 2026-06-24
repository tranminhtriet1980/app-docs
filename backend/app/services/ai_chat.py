"""AI Q&A over a single applicant's profile and extracted document fields."""

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.entities import Applicant, Document, ProfileField
from app.services.llm_client import is_openai_configured
from app.services.llm_usage import UsageContext, chat_completion


async def _build_context(db: AsyncSession, applicant_id) -> str:
    applicant = await db.get(Applicant, applicant_id)
    if not applicant:
        return ""

    fields = await db.execute(
        select(ProfileField).where(ProfileField.applicant_id == applicant_id).order_by(ProfileField.field_key)
    )
    profile_lines = [
        f"- {row.field_key}: {row.field_value}"
        for row in fields.scalars().all()
        if row.field_value
    ]

    docs = await db.execute(
        select(Document)
        .where(Document.applicant_id == applicant_id)
        .options(selectinload(Document.extracted_fields))
        .order_by(Document.uploaded_at.desc())
    )
    doc_blocks = []
    for doc in docs.scalars().all():
        extracted = {ef.field_key: ef.field_value for ef in doc.extracted_fields if ef.field_value}
        if extracted:
            doc_blocks.append(
                f"File: {doc.original_filename} ({doc.document_type or 'unknown'})\n"
                + json.dumps(extracted, ensure_ascii=False, indent=2)
            )

    return f"""Hồ sơ: {applicant.display_name}
Khách hàng: {applicant.client_name or '—'}
Dự án: {applicant.project_name or '—'}
Phòng ban: {applicant.department or '—'}
Ghi chú: {applicant.notes or '—'}

Dữ liệu hồ sơ đã merge:
{chr(10).join(profile_lines) or '(chưa có)'}

Trích xuất từ tài liệu:
{chr(10).join(doc_blocks) or '(chưa có)'}
"""


async def ask_applicant_ai(
    db: AsyncSession,
    *,
    applicant_id,
    user_id,
    question: str,
) -> dict:
    if not is_openai_configured():
        return {
            "answer": "Chưa cấu hình OPENAI_API_KEY. Thêm key trong backend/.env để dùng AI Chat.",
            "sources": [],
        }

    context = await _build_context(db, applicant_id)
    messages = [
        {
            "role": "system",
            "content": (
                "Bạn là trợ lý ImmiPath — trả lời câu hỏi về hồ sơ di trú/du học dựa CHỈ trên dữ liệu được cung cấp. "
                "Nếu không đủ thông tin, nói rõ. Trả lời tiếng Việt, ngắn gọn, có cấu trúc."
            ),
        },
        {"role": "user", "content": f"Dữ liệu hồ sơ:\n\n{context}\n\nCâu hỏi: {question}"},
    ]
    response = await chat_completion(
        db,
        operation="applicant.ai_chat",
        context=UsageContext(user_id=user_id, applicant_id=applicant_id),
        messages=messages,
        max_tokens=1200,
        temperature=0.2,
    )
    answer = response.choices[0].message.content or ""
    return {"answer": answer.strip(), "model": settings.openai_model}
