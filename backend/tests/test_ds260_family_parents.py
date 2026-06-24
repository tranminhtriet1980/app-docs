"""DS-260 cha/mẹ chủ hồ sơ — phải lấy từ GKS của chính chủ hồ sơ, không lấy GKS con."""

import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.ds260_mapping import (
    enrich_empty_fields_from_all_doc_records,
    flatten_ds260_mappings,
    resolve_luong1_ds260_field,
)


def _rec(
    *,
    doc_type: str,
    raw: dict,
    updated_at: datetime | None = None,
    variant: str = "standard",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        doc_type=doc_type,
        variant=variant,
        form_data="{}",
        raw_data=json.dumps(raw),
        source_document_id=uuid.uuid4(),
        updated_at=updated_at or datetime.now(timezone.utc),
    )


def test_principal_parents_from_own_birth_cert_not_child():
    """HỒ CÔNG BẢO LONG — GKS con mới hơn không được dùng cho cha/mẹ chủ hồ sơ."""
    principal_bc = _rec(
        doc_type="birth_certificate",
        raw={
            "full_name": "HỒ CÔNG BẢO LONG",
            "father_name": "HỒ VĂN NAM",
            "mother_name": "NGUYỄN THỊ LAN",
        },
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    child_bc_misclassified = _rec(
        doc_type="birth_certificate",
        raw={
            "full_name": "HỒ BẢO CHÂU",
            "father_name": "HỒ CÔNG BẢO LONG",
            "mother_name": "VĂN THỊ HƯỜNG",
        },
        updated_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
    )
    records = [principal_bc, child_bc_misclassified]
    mappings = flatten_ds260_mappings()
    person = "HỒ CÔNG BẢO LONG"

    father_val, _, father_rec, _ = resolve_luong1_ds260_field(
        records, "birth_certificate", mappings["father_full_name"], {}, person_name=person
    )
    mother_val, _, mother_rec, _ = resolve_luong1_ds260_field(
        records, "birth_certificate", mappings["mother_full_name"], {}, person_name=person
    )

    assert father_val == "HỒ VĂN NAM"
    assert mother_val == "NGUYỄN THỊ LAN"
    assert father_rec is principal_bc
    assert mother_rec is principal_bc


def test_enrich_empty_skips_child_birth_cert_for_principal_parents():
    sections = [
        {
            "id": "section_father",
            "fields": [{"key": "father_full_name", "value": "", "source": {}}],
        },
        {
            "id": "section_mother",
            "fields": [{"key": "mother_full_name", "value": "", "source": {}}],
        },
    ]
    principal_bc = _rec(
        doc_type="birth_certificate",
        raw={
            "full_name": "HỒ CÔNG BẢO LONG",
            "father_name": "HỒ VĂN NAM",
            "mother_name": "NGUYỄN THỊ LAN",
        },
    )
    child_bc = _rec(
        doc_type="birth_certificate_child",
        raw={
            "child_full_name": "HỒ BẢO CHÂU",
            "father_name": "HỒ CÔNG BẢO LONG",
            "mother_name": "VĂN THỊ HƯỜNG",
        },
    )
    enrich_empty_fields_from_all_doc_records(
        sections, [child_bc, principal_bc], {}, person_name="HỒ CÔNG BẢO LONG"
    )
    father = sections[0]["fields"][0]["value"]
    mother = sections[1]["fields"][0]["value"]
    assert father == "HỒ VĂN NAM"
    assert mother == "NGUYỄN THỊ LAN"
