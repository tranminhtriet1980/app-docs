"""Previous spouse section from divorce decree."""

import json
from types import SimpleNamespace

from app.services.ds260_mapping import enrich_previous_spouse_from_divorce


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
