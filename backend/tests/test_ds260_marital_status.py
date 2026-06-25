"""Current marital status in DS-260 personal section."""

import json
from types import SimpleNamespace

from app.services.ds260_mapping import enrich_marital_status_from_documents


def _rec(
    raw: dict,
    doc_type: str = "divorce",
    *,
    variant: str = "standard",
) -> SimpleNamespace:
    return SimpleNamespace(
        doc_type=doc_type,
        variant=variant,
        form_data=json.dumps(raw),
        raw_data=json.dumps(raw),
    )


def test_marital_status_not_guessed_without_documents():
    """Không có giấy kết hôn / ly hôn → không ép Married (CHIEM ANH HANG pattern)."""
    fields = [{"key": "current_marital_status", "value": "", "source": {}}]
    enrich_marital_status_from_documents(fields, None)
    assert fields[0]["value"] == ""


def test_marital_status_cleared_when_no_documents_even_from_worksheet():
    """Không có giấy → xóa cả giá trị worksheet (Single, v.v.)."""
    fields = [{"key": "current_marital_status", "value": "Single", "source": {}}]
    enrich_marital_status_from_documents(fields, None)
    assert fields[0]["value"] == ""


def test_marital_status_married_when_marriage_cert_applicable():
    passport = _rec({"full_name": "TRAN VAN A"}, doc_type="passport")
    marriage = _rec(
        {
            "husband_full_name": "TRAN VAN A",
            "wife_full_name": "NGUYEN THI B",
            "marriage_date": "2010-05-01",
        },
        doc_type="marriage_certificate",
    )
    fields = [{"key": "current_marital_status", "value": "", "source": {}}]
    enrich_marital_status_from_documents(
        fields, None, marriage_rec=marriage, passport_rec=passport
    )
    assert fields[0]["value"] == "Married"
    assert fields[0]["source"]["derived"] == "marital_status_from_marriage"


def test_marital_status_divorced_when_divorce_present():
    fields = [{"key": "current_marital_status", "value": "", "source": {}}]
    divorce = _rec({"divorce_date": "2025-07-30"})
    enrich_marital_status_from_documents(fields, divorce)
    assert fields[0]["value"] == "Divorced"
    assert fields[0]["source"]["derived"] == "marital_status_from_divorce"
