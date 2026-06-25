"""Previous spouse section from divorce decree."""

import json
from types import SimpleNamespace

from app.services.ds260_mapping import (
    enrich_divorce_section_from_record,
    enrich_previous_spouse_from_divorce,
)


def _rec(raw: dict, doc_type: str = "divorce") -> SimpleNamespace:
    return SimpleNamespace(
        doc_type=doc_type,
        form_data=json.dumps(raw),
        raw_data=json.dumps(raw),
    )


def test_enrich_previous_spouse_from_divorce():
    divorce = _rec(
        {
            "husband_full_name": "MR. DANG VAN HUNG",
            "wife_full_name": "MRS. MAI NGOC HOA",
            "marriage_date": "2006-12-21",
            "divorce_date": "2025-07-30",
            "document_number": "41/2025/QDST-HNGD",
        }
    )
    passport = _rec({"full_name": "DANG VAN HUNG", "gender": "Male"}, "passport")
    fields = [
        {"key": "previous_spouses_used", "value": "", "source": {}},
        {"key": "previous_spouse_full_name", "value": "", "source": {}},
        {"key": "previous_marriage_date", "value": "", "source": {}},
        {"key": "previous_divorce_date", "value": "", "source": {}},
    ]
    enrich_previous_spouse_from_divorce(fields, divorce, passport)
    by_key = {f["key"]: f["value"] for f in fields}
    assert by_key["previous_spouses_used"] == "Yes"
    assert by_key["previous_spouse_full_name"] == "MAI NGOC HOA"
    assert by_key["previous_marriage_date"] == "2006-12-21"
    assert by_key["previous_divorce_date"] == "2025-07-30"


def test_no_divorce_clears_previous_spouse_section():
    """CHIEM ANH HANG: không có giấy ly hôn → No và trống."""
    fields = [
        {"key": "previous_spouses_used", "value": "Yes", "source": {}},
        {"key": "previous_spouse_full_name", "value": "DS CHIEM ANH HANG", "source": {}},
        {"key": "previous_spouse_date_of_birth", "value": "1993-09-13", "source": {}},
        {"key": "previous_marriage_date", "value": "", "source": {}},
        {"key": "previous_divorce_date", "value": "", "source": {}},
    ]
    passport = _rec({"full_name": "CHIEM ANH HANG", "date_of_birth": "1993-09-13"}, "passport")
    enrich_previous_spouse_from_divorce(fields, None, passport)
    by_key = {f["key"]: f["value"] for f in fields}
    assert by_key["previous_spouses_used"] == "No"
    assert by_key["previous_spouse_full_name"] == ""
    assert by_key["previous_spouse_date_of_birth"] == ""


def test_worksheet_bleed_matching_applicant_name_is_cleared():
    """Worksheet OCR ghi nhầm tên chủ hồ sơ vào vợ/chồng cũ — không coi là ly hôn."""
    ws_as_divorce = _rec(
        {
            "previous_spouse_full_name": "DS CHIEM ANH HANG",
            "previous_spouse_date_of_birth": "1993-09-13",
            "wife_date_of_birth": "1993-09-13",
        },
        doc_type="ds260_customer_form",
    )
    passport = _rec({"full_name": "CHIEM ANH HANG"}, "passport")
    fields = [
        {"key": "previous_spouses_used", "value": "", "source": {}},
        {"key": "previous_spouse_full_name", "value": "DS CHIEM ANH HANG", "source": {}},
        {"key": "previous_spouse_date_of_birth", "value": "1993-09-13", "source": {}},
    ]
    enrich_previous_spouse_from_divorce(fields, ws_as_divorce, passport)
    by_key = {f["key"]: f["value"] for f in fields}
    assert by_key["previous_spouses_used"] == "No"
    assert by_key["previous_spouse_full_name"] == ""


def test_enrich_divorce_section_from_record():
    divorce = _rec(
        {
            "husband_full_name": "DANG VAN HUNG",
            "wife_full_name": "MAI NGOC HOA",
            "marriage_date": "2006-12-21",
            "divorce_date": "2025-07-30",
            "document_number": "41/2025",
        }
    )
    fields = [
        {"key": "divorce_husband_name", "value": "", "source": {}},
        {"key": "divorce_wife_name", "value": "", "source": {}},
        {"key": "divorce_date", "value": "", "source": {}},
    ]
    enrich_divorce_section_from_record(fields, divorce)
    by_key = {f["key"]: f["value"] for f in fields}
    assert by_key["divorce_husband_name"] == "DANG VAN HUNG"
    assert by_key["divorce_wife_name"] == "MAI NGOC HOA"
    assert by_key["divorce_date"] == "2025-07-30"


def test_no_divorce_clears_divorce_section():
    fields = [
        {"key": "divorce_husband_name", "value": "DS CHIEM ANH HANG", "source": {}},
        {"key": "divorce_wife_name", "value": "", "source": {}},
        {"key": "divorce_date", "value": "", "source": {}},
    ]
    enrich_divorce_section_from_record(fields, None)
    by_key = {f["key"]: f["value"] for f in fields}
    assert by_key["divorce_husband_name"] == ""
    assert by_key["divorce_wife_name"] == ""
