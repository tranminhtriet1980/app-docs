"""ExtractedField.field_value/confidence là cột VARCHAR/FLOAT — insert thẳng list/dict/string-số
từ model vào đó ném DataError ở tầng asyncpg và ROLLBACK CẢ TRANSACTION, làm mất luôn mọi field
khác đã đọc đúng của tài liệu (sự cố thực tế 2026-08-04, OCR "01_7 JOB APPLICATION...docx").
"""

import asyncio
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.entities import Applicant, Document, ExtractedField, User
from app.services.ocr_pipeline import (
    _coerce_confidence_to_float,
    _coerce_field_value_to_str,
    save_extracted_fields,
)


def test_coerce_field_value_passes_through_str_and_none():
    assert _coerce_field_value_to_str("NGUYEN VAN A") == "NGUYEN VAN A"
    assert _coerce_field_value_to_str(None) is None


def test_coerce_field_value_serializes_list_and_dict():
    assert _coerce_field_value_to_str([{"surname": "NGUYEN", "given_names": "HUNG"}]) == (
        '[{"surname": "NGUYEN", "given_names": "HUNG"}]'
    )
    assert _coerce_field_value_to_str({"a": 1}) == '{"a": 1}'


def test_coerce_field_value_stringifies_other_scalars():
    assert _coerce_field_value_to_str(True) == "True"
    assert _coerce_field_value_to_str(123) == "123"


def test_coerce_confidence_accepts_numeric_and_numeric_strings():
    assert _coerce_confidence_to_float(0.9) == 0.9
    assert _coerce_confidence_to_float("0.5") == 0.5
    assert _coerce_confidence_to_float(None) is None


def test_coerce_confidence_falls_back_to_none_on_garbage():
    assert _coerce_confidence_to_float("high") is None
    assert _coerce_confidence_to_float([0.9]) is None


def _run(coro):
    return asyncio.run(coro)


def test_save_extracted_fields_survives_list_value_from_model(tmp_path):
    """Trước fix: field_value=list đi thẳng vào INSERT — asyncpg từ chối kiểu, cả batch rollback."""

    async def scenario():
        db_file = tmp_path / "coerce.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_file.as_posix()}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False)

        async with Session() as session:
            user = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@t.local", hashed_password="x")
            applicant = Applicant(id=uuid.uuid4(), user_id=user.id, display_name="TRIEU THI DUYEN")
            document = Document(
                id=uuid.uuid4(),
                applicant_id=applicant.id,
                original_filename="01_7 JOB APPLICATION - TRIEU THI DUYEN.docx",
                file_path="uploads/x/job.docx",
                mime_type="application/vnd.openxmlformats",
                file_size=1234,
            )
            session.add_all([user, applicant, document])
            await session.flush()

            extraction = {
                "fields": {
                    "surname": {"value": "TRIEU", "confidence": 1.0, "source_page": "page_1"},
                    "other_names": {
                        "value": [{"surname": "NGUYEN", "given_names": "HUNG"}],
                        "confidence": "high",
                        "source_page": "page_1",
                    },
                }
            }
            saved = await save_extracted_fields(session, document.id, extraction)
            await session.commit()

            assert len(saved) == 2
            by_key = {f.field_key: f for f in saved}
            assert by_key["surname"].field_value == "TRIEU"
            assert isinstance(by_key["other_names"].field_value, str)
            assert "NGUYEN" in by_key["other_names"].field_value
            # confidence rác ("high") → None thay vì ném lỗi.
            assert by_key["other_names"].confidence is None
        await engine.dispose()

    _run(scenario())
