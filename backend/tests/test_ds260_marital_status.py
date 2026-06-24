"""Current marital status in DS-260 personal section."""

import json
from types import SimpleNamespace

from app.services.ds260_mapping import enrich_marital_status_from_documents


def _rec(raw: dict, doc_type: str = "divorce") -> SimpleNamespace:
    return SimpleNamespace(
        doc_type=doc_type,
        form_data=json.dumps(raw),
        raw_data=json.dumps(raw),
    )


def test_marital_status_married_when_no_divorce():
    fields = [{"key": "current_marital_status", "value": "", "source": {}}]
    enrich_marital_status_from_documents(fields, None)
    assert fields[0]["value"] == "Married"
    assert fields[0]["source"]["derived"] == "marital_status_default_married"


def test_marital_status_divorced_when_divorce_present():
    fields = [{"key": "current_marital_status", "value": "", "source": {}}]
    divorce = _rec({"divorce_date": "2025-07-30"})
    enrich_marital_status_from_documents(fields, divorce)
    assert fields[0]["value"] == "Divorced"
    assert fields[0]["source"]["derived"] == "marital_status_from_divorce"
