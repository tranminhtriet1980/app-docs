"""identity_outlier — cảnh báo 'đa số vs thiểu số' giữa nhiều tài liệu."""

from types import SimpleNamespace
from uuid import uuid4

from app.services.ds260_conflicts import conflict_label_vi, conflict_type_from_field_key
from app.services.identity_conflicts import (
    build_identity_outlier_conflict_rows_from_documents,
    identity_outlier_field_key,
)


def _ef(field_key: str, field_value: str) -> SimpleNamespace:
    return SimpleNamespace(field_key=field_key, field_value=field_value)


def _doc(document_type: str, fields: dict[str, str]) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        document_type=document_type,
        extracted_fields=[_ef(k, v) for k, v in fields.items()],
    )


def test_outlier_flagged_when_majority_agrees():
    passport = _doc("passport", {"full_name": "NGUYEN VAN A"})
    birth = _doc("birth_certificate", {"full_name": "NGUYEN VAN A"})
    judicial = _doc("judicial_certificate", {"full_name": "NGUYEN VAN B"})

    rows = build_identity_outlier_conflict_rows_from_documents([passport, birth, judicial], {})
    assert len(rows) == 1
    row = rows[0]
    assert row["value_a"] == "NGUYEN VAN A"
    assert row["value_b"] == "NGUYEN VAN B"
    assert row["document_b_id"] == judicial.id
    assert row["majority_count"] == 2
    assert row["total_count"] == 3
    assert row["field_key"] == identity_outlier_field_key("identity.full_name", judicial.id)


def test_no_outlier_when_all_three_disagree():
    docs = [
        _doc("passport", {"full_name": "NGUYEN VAN A"}),
        _doc("birth_certificate", {"full_name": "NGUYEN VAN B"}),
        _doc("judicial_certificate", {"full_name": "NGUYEN VAN C"}),
    ]
    assert build_identity_outlier_conflict_rows_from_documents(docs, {}) == []


def test_no_outlier_below_min_total_votes():
    docs = [
        _doc("passport", {"full_name": "NGUYEN VAN A"}),
        _doc("birth_certificate", {"full_name": "NGUYEN VAN B"}),
    ]
    assert build_identity_outlier_conflict_rows_from_documents(docs, {}) == []


def test_outlier_respects_resolved():
    passport = _doc("passport", {"full_name": "NGUYEN VAN A"})
    birth = _doc("birth_certificate", {"full_name": "NGUYEN VAN A"})
    judicial = _doc("judicial_certificate", {"full_name": "NGUYEN VAN B"})
    fk = identity_outlier_field_key("identity.full_name", judicial.id)

    rows = build_identity_outlier_conflict_rows_from_documents(
        [passport, birth, judicial], {fk: "NGUYEN VAN A"}
    )
    assert rows == []


def test_date_of_birth_normalized_across_formats():
    docs = [
        _doc("passport", {"date_of_birth": "1990-01-15"}),
        _doc("birth_certificate", {"date_of_birth": "15/01/1990"}),
        _doc("judicial_certificate", {"date_of_birth": "1991-02-20"}),
    ]
    rows = build_identity_outlier_conflict_rows_from_documents(docs, {})
    assert len(rows) == 1
    # Hiển thị dd/mm/yyyy cho người dùng chọn — không phải chuỗi ISO thô (khách yêu cầu).
    assert rows[0]["value_b"] == "20/02/1991"


def test_ex_spouse_name_on_divorce_decree_not_counted_as_applicant():
    """Bug thực tế 2026-08-04: quyết định ly hôn có 2 phía (chồng/vợ), map tĩnh cũ luôn coi
    husband_full_name = đương đơn — sai khi đương đơn là VỢ (nữ). Đương đơn "TRIỆU THỊ DUYÊN"
    bị hệ thống hỏi chọn giữa tên mình và "NGUYỄN VĂN HÙNG" (chồng cũ, không liên quan gì đến
    danh tính của cô). husband_full_name/defendant_name giờ dồn vào family.* như
    marriage_certificate, không phía nào trên giấy ly hôn được coi là đương đơn."""
    docs = [
        _doc("passport", {"full_name": "TRIEU THI DUYEN"}),
        _doc("birth_certificate", {"full_name": "TRIEU THI DUYEN"}),
        _doc("divorce", {"husband_full_name": "NGUYEN VAN HUNG", "wife_full_name": "TRIEU THI DUYEN"}),
    ]
    rows = build_identity_outlier_conflict_rows_from_documents(docs, {})
    assert rows == []


def test_spouse_name_on_marriage_certificate_not_counted_as_applicant():
    """marriage_certificate maps husband/wife name to family.spouse_name, not identity.full_name —
    must not be pulled into the applicant identity vote."""
    docs = [
        _doc("passport", {"full_name": "NGUYEN VAN A"}),
        _doc("birth_certificate", {"full_name": "NGUYEN VAN A"}),
        _doc("marriage_certificate", {"wife_full_name": "TRAN THI C"}),
    ]
    rows = build_identity_outlier_conflict_rows_from_documents(docs, {})
    assert rows == []


def test_conflict_type_and_label_for_identity_outlier():
    doc_id = uuid4()
    field_key = identity_outlier_field_key("identity.full_name", doc_id)
    assert conflict_type_from_field_key(field_key) == "identity_outlier"
    label = conflict_label_vi(field_key)
    assert "Họ và tên đầy đủ" in label
    assert "đa số" in label


def test_identity_outlier_label_includes_person_hint_to_disambiguate():
    """Hồ sơ gia đình có thể phát ra 2 thẻ conflict CÙNG nhãn field ('Họ và tên đầy đủ') cho
    2 người khác nhau (mẹ, con) — phải ghi rõ tên người ngay trên tiêu đề, không để người
    dùng phải tự đoán qua tên file bên dưới (báo lỗi thực tế 2026-08-04)."""
    doc_id = uuid4()
    field_key = identity_outlier_field_key("identity.date_of_birth", doc_id)

    mother_label = conflict_label_vi(field_key, person_hint="TRIEU THI DUYEN")
    child_label = conflict_label_vi(field_key, person_hint="NGUYEN MINH PHUONG")

    assert "TRIEU THI DUYEN" in mother_label
    assert "NGUYEN MINH PHUONG" in child_label
    assert mother_label != child_label
    # Không truyền hint vẫn hoạt động, giờ có thêm tiền tố mục DS-260.
    assert conflict_label_vi(field_key) == (
        "⚠️ DS-260 A.1 — Personal Information · Ngày sinh (dd/mm/yyyy) — khác biệt với đa số tài liệu"
    )
