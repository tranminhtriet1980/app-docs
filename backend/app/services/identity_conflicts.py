"""
Cảnh báo "đa số vs thiểu số": khi cùng một trường nhận dạng (họ tên, ngày sinh, giới tính,
tên cha/mẹ) được nhiều tài liệu khác nhau trích xuất, và phần lớn tài liệu đồng ý một giá trị
nhưng một vài tài liệu lệch ra — tài liệu lệch nhiều khả năng bị OCR sai, cần cảnh báo riêng
thay vì coi ngang hàng "chọn A hay B" như document_vs_exception / document_vs_worksheet.

Không xét ds260_customer_form (worksheet khách khai): FIELD_MAP của doc_type này không map field
nào vào các canonical key dưới đây, nên tự động bị loại — tránh trùng lặp với cảnh báo
document_vs_worksheet (đã so worksheet với giá trị Luồng 1 riêng trong ds260_conflicts.py).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.entities import Applicant, Document, DocumentStatus
from app.services.ds260_conflicts import DS260_CONFLICT_PREFIX, IDENTITY_OUTLIER_SEGMENT, _display_conflict_date
from app.services.ds260_dates import parse_full_date
from app.services.field_mapping import FIELD_MAP, SOURCE_PRIORITY
from app.services.merge import _field_norm

# Chỉ các field nhận dạng cốt lõi — sai lệch ở đây ảnh hưởng trực tiếp việc điền DS-260.
IDENTITY_VOTE_KEYS: tuple[str, ...] = (
    "identity.full_name",
    "identity.date_of_birth",
    "identity.gender",
    "family.father_name",
    "family.mother_name",
)

# Cần tối thiểu 3 tài liệu có giá trị mới đủ tin cậy để gọi là "đa số".
MIN_TOTAL_VOTES = 3


def identity_outlier_field_key(canonical_key: str, document_id: uuid.UUID) -> str:
    return f"{DS260_CONFLICT_PREFIX}{IDENTITY_OUTLIER_SEGMENT}.{canonical_key}.{document_id}"


def _source_rank(doc_type: str | None) -> int:
    try:
        return SOURCE_PRIORITY.index(doc_type or "other")
    except ValueError:
        return len(SOURCE_PRIORITY)


def _normalize_identity_value(canonical_key: str, value: str) -> str:
    if canonical_key == "identity.date_of_birth":
        parsed = parse_full_date(value)
        if parsed:
            return parsed.isoformat()
    return _field_norm(canonical_key, value) or ""


async def _load_extracted_documents(db: AsyncSession, applicant_id: uuid.UUID) -> list[Document]:
    result = await db.execute(
        select(Document)
        .where(Document.applicant_id == applicant_id, Document.status == DocumentStatus.extracted)
        .options(selectinload(Document.extracted_fields))
    )
    return list(result.scalars())


def _group_documents_by_case_member(
    documents: list[Document], applicant: Applicant | None, members: list
) -> list[list[Document]]:
    """Chia tài liệu theo TỪNG NGƯỜI trong bộ hồ sơ gia đình trước khi vote đa số.

    Bug thực tế 2026-08-04: hồ sơ gia đình (is_family_bundle) gộp CHUNG passport của mẹ
    (TRIEU THI DUYEN) với passport/lý lịch tư pháp của con (NGUYEN MINH PHUONG) vào MỘT vòng
    vote ngày sinh — hai người khác nhau nên "khác biệt" là ĐÚNG, không phải OCR sai. Phải vote
    riêng trong phạm vi tài liệu của từng người.
    """
    from app.services.family_case import (
        DocumentLabelInput,
        members_for_document_labeling,
        resolve_document_member_labels_batch,
    )

    resolved_members = members_for_document_labeling(applicant, members)
    labels = resolve_document_member_labels_batch(
        items=[
            DocumentLabelInput(
                document_id=doc.id,
                filename=doc.original_filename or "",
                registry_doc_type=doc.registry_doc_type or doc.document_type,
                doc_record=None,
                uploaded_at=doc.uploaded_at,
            )
            for doc in documents
        ],
        members=resolved_members,
    )

    groups: dict[str, list[Document]] = {}
    for doc in documents:
        member_number, _name, _label = labels.get(doc.id, (None, None, None))
        if not member_number:
            # Không xác định được thuộc về ai — KHÔNG gộp chung với người khác để đoán mò,
            # bỏ khỏi vòng vote hơn là tạo cảnh báo sai giữa hai người khác nhau.
            continue
        groups.setdefault(member_number, []).append(doc)
    return list(groups.values())


async def build_identity_outlier_conflict_rows(
    db: AsyncSession, applicant_id: uuid.UUID, resolutions: dict[str, str]
) -> list[dict]:
    """Đa số tài liệu đồng ý một giá trị, một số tài liệu lệch ra → 1 dòng cảnh báo/tài liệu lệch.

    Vote chỉ trong phạm vi tài liệu của TỪNG NGƯỜI (case member) — hồ sơ đơn (không khai báo
    thành viên) tự động coi là một người, không đổi hành vi cũ.
    """
    from app.services.family_case import load_case_members

    documents = await _load_extracted_documents(db, applicant_id)
    applicant = await db.get(Applicant, applicant_id)
    members = await load_case_members(db, applicant_id)

    rows: list[dict] = []
    for group in _group_documents_by_case_member(documents, applicant, members):
        rows.extend(build_identity_outlier_conflict_rows_from_documents(group, resolutions))
    return rows


def build_identity_outlier_conflict_rows_from_documents(
    documents: list, resolutions: dict[str, str]
) -> list[dict]:
    """Phần logic thuần (không DB) — mỗi `doc` cần `.id`, `.document_type`, `.extracted_fields`
    (list các object có `.field_key`/`.field_value`). Tách riêng để test không cần DB thật."""
    # canonical_key -> normalized_value -> list[(raw_value, Document)]
    groups: dict[str, dict[str, list[tuple[str, Document]]]] = {}
    for doc in documents:
        mapping = FIELD_MAP.get(doc.document_type or "", {})
        voted_keys: set[str] = set()
        for ef in doc.extracted_fields:
            if not ef.field_value:
                continue
            canonical = mapping.get(ef.field_key)
            if canonical not in IDENTITY_VOTE_KEYS or canonical in voted_keys:
                continue
            norm = _normalize_identity_value(canonical, ef.field_value)
            if not norm:
                continue
            voted_keys.add(canonical)
            groups.setdefault(canonical, {}).setdefault(norm, []).append((ef.field_value, doc))

    rows: list[dict] = []
    for canonical_key, value_groups in groups.items():
        total = sum(len(items) for items in value_groups.values())
        if total < MIN_TOTAL_VOTES:
            continue

        majority_norm, majority_items = max(value_groups.items(), key=lambda kv: len(kv[1]))
        if len(majority_items) * 2 <= total:
            continue  # không có đa số tuyệt đối (vd. 2v2, 1v1v1) — chưa đủ tin cậy để gọi là sai

        majority_value, majority_doc = min(
            majority_items, key=lambda item: _source_rank(item[1].document_type)
        )

        for norm, items in value_groups.items():
            if norm == majority_norm:
                continue
            for raw_value, doc in items:
                field_key = identity_outlier_field_key(canonical_key, doc.id)
                if field_key in resolutions:
                    continue
                rows.append(
                    {
                        "field_key": field_key,
                        "value_a": _display_conflict_date(canonical_key, majority_value),
                        "document_a_id": majority_doc.id,
                        "value_b": _display_conflict_date(canonical_key, raw_value),
                        "document_b_id": doc.id,
                        "majority_count": len(majority_items),
                        "total_count": total,
                    }
                )
    return rows
