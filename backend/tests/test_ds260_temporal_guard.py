"""Guard hợp lý thời gian + chống bịa độ chi tiết ngày.

Bám theo 2 lỗi thật ghi nhận trong Ghi_nhan_ket_qua_test_DS260.xlsx:
  - Case D (Khúc Thị Lệ Hằng): cha ghi mất 1968 trong khi đương đơn sinh 1973.
  - Case C-2 (Văn Thị Hường): KHAI chỉ ghi cha/mẹ "Mất" → form xuất "07 September 2006".
"""

import json
from types import SimpleNamespace
from uuid import uuid4

from app.services.ds260_mapping import (
    downgrade_fabricated_date_precision,
    enforce_ds260_temporal_plausibility,
)


def _sections(values: dict[str, str], *, source_doc: str = "") -> list[dict]:
    return [
        {
            "id": "s",
            "fields": [
                {
                    "key": k,
                    "value": v,
                    "source": {"document_type": source_doc},
                }
                for k, v in values.items()
            ],
        }
    ]


def _flat(sections: list[dict]) -> dict[str, str]:
    return {f["key"]: f["value"] for f in sections[0]["fields"]}


# --- Guard A: năm mất vô lý ---


def test_case_d_father_death_before_applicant_birth_is_cleared():
    secs = _sections({"date_of_birth": "1973-05-02", "father_death_year": "1968"})
    enforce_ds260_temporal_plausibility(secs)
    assert _flat(secs)["father_death_year"] == ""


def test_death_year_before_own_birth_is_cleared():
    secs = _sections(
        {"father_date_of_birth": "1943", "father_death_year": "1930"}
    )
    enforce_ds260_temporal_plausibility(secs)
    assert _flat(secs)["father_death_year"] == ""


def test_father_may_die_the_year_before_applicant_is_born():
    """Cha mất khi con còn trong bụng mẹ là hợp lệ — không được xoá."""
    secs = _sections({"date_of_birth": "1973-05-02", "father_death_year": "1972"})
    enforce_ds260_temporal_plausibility(secs)
    assert _flat(secs)["father_death_year"] == "1972"


def test_mother_death_before_applicant_birth_is_cleared():
    secs = _sections({"date_of_birth": "1973-05-02", "mother_death_year": "1972"})
    enforce_ds260_temporal_plausibility(secs)
    assert _flat(secs)["mother_death_year"] == ""


def test_plausible_death_year_is_kept():
    secs = _sections({"date_of_birth": "1973-05-02", "father_death_year": "1999"})
    enforce_ds260_temporal_plausibility(secs)
    assert _flat(secs)["father_death_year"] == "1999"


def test_missing_comparison_data_leaves_value_untouched():
    """Không đủ dữ liệu để kết luận thì giữ nguyên cho người review."""
    secs = _sections({"father_death_year": "1968"})
    enforce_ds260_temporal_plausibility(secs)
    assert _flat(secs)["father_death_year"] == "1968"


# --- Guard B: rút độ chi tiết ngày về đúng nguồn khai ---


def _Rec(form_data: dict) -> SimpleNamespace:
    """ApplicantDocRecord tối giản đủ cho pick_latest_record/_merge_raw_dict."""
    return SimpleNamespace(
        id=uuid4(),
        doc_type="ds260_customer_form",
        variant="exception",
        form_data=json.dumps(form_data),
        raw_data="{}",
        updated_at=None,
        created_at=None,
    )


def test_year_only_worksheet_does_not_become_full_date():
    """Case C-2 / Phong: KHAI '1963' thì không được xuất 'Jan 01, 1963'."""
    secs = _sections(
        {"father_date_of_birth": "1963-01-01"}, source_doc="ds260_customer_form"
    )
    downgrade_fabricated_date_precision(secs, [_Rec({"father_date_of_birth": "1963"})])
    assert _flat(secs)["father_date_of_birth"] == "1963"


def test_full_date_from_official_document_is_kept():
    """Ngày đầy đủ trên giấy khai sinh là nguồn đáng tin — không bị rút."""
    secs = _sections(
        {"father_date_of_birth": "1963-01-01"}, source_doc="birth_certificate"
    )
    downgrade_fabricated_date_precision(secs, [_Rec({"father_date_of_birth": "1963"})])
    assert _flat(secs)["father_date_of_birth"] == "1963-01-01"


def test_worksheet_with_full_date_keeps_full_date():
    secs = _sections(
        {"father_date_of_birth": "1963-04-17"}, source_doc="ds260_customer_form"
    )
    downgrade_fabricated_date_precision(
        secs, [_Rec({"father_date_of_birth": "1963-04-17"})]
    )
    assert _flat(secs)["father_date_of_birth"] == "1963-04-17"


def test_no_worksheet_record_is_a_noop():
    secs = _sections(
        {"father_date_of_birth": "1963-01-01"}, source_doc="ds260_customer_form"
    )
    downgrade_fabricated_date_precision(secs, [])
    assert _flat(secs)["father_date_of_birth"] == "1963-01-01"


# --- Quy ước N/A vs No vs để trống ---


def test_phone_field_showing_no_becomes_na():
    """Case B-2: Work Phone hiển thị 'No' — ô thông tin phải là 'N/A'."""
    from app.services.ds260_mapping import normalize_ds260_na_conventions

    secs = _sections({"work_phone": "No", "primary_phone": "+84819353855"})
    normalize_ds260_na_conventions(secs)
    got = _flat(secs)
    assert got["work_phone"] == "N/A"
    assert got["primary_phone"] == "+84819353855"


def test_children_count_blank_becomes_no_when_no_children():
    """Case C-2: 'Số con' của Châu để trống trong khi anh chị em ghi 'No'."""
    from app.services.ds260_mapping import normalize_ds260_na_conventions

    secs = _sections({"children_count": "", "child_1_full_name": ""})
    normalize_ds260_na_conventions(secs)
    assert _flat(secs)["children_count"] == "No"


def test_children_count_untouched_when_children_exist():
    from app.services.ds260_mapping import normalize_ds260_na_conventions

    secs = _sections({"children_count": "", "child_1_full_name": "HO BAO HAN"})
    normalize_ds260_na_conventions(secs)
    assert _flat(secs)["children_count"] == ""


def test_blank_state_becomes_na_when_city_present():
    """Case E: nơi sinh Da Nang nhưng ô Tỉnh để TRỐNG thay vì 'N/A'."""
    from app.services.ds260_mapping import normalize_ds260_na_conventions

    secs = _sections({"birth_city": "Da Nang", "birth_state": ""})
    normalize_ds260_na_conventions(secs)
    assert _flat(secs)["birth_state"] == "N/A"


def test_blank_state_untouched_when_city_also_blank():
    from app.services.ds260_mapping import normalize_ds260_na_conventions

    secs = _sections({"birth_city": "", "birth_state": ""})
    normalize_ds260_na_conventions(secs)
    assert _flat(secs)["birth_state"] == ""


def test_email_showing_no_becomes_na():
    """_NA_NOT_NO_KEYS trước đây liệt kê 'email_address' — key thật trong DS-260 mapping là
    'email', nên rule này chưa từng chạy cho field email (rule chết). Sửa key đúng."""
    from app.services.ds260_mapping import normalize_ds260_na_conventions

    secs = _sections({"email": "No"})
    normalize_ds260_na_conventions(secs)
    assert _flat(secs)["email"] == "N/A"


def test_current_state_becomes_na_when_current_city_present():
    from app.services.ds260_mapping import normalize_ds260_na_conventions

    secs = _sections({"current_city": "Da Nang", "current_state": ""})
    normalize_ds260_na_conventions(secs)
    assert _flat(secs)["current_state"] == "N/A"


def test_work_employer_state_becomes_na_when_work_employer_city_present():
    from app.services.ds260_mapping import normalize_ds260_na_conventions

    secs = _sections({"work_employer_city": "Ho Chi Minh", "work_employer_state": ""})
    normalize_ds260_na_conventions(secs)
    assert _flat(secs)["work_employer_state"] == "N/A"
