"""Guard: không điền worksheet vào section thiếu giấy tờ chính."""

import json
from types import SimpleNamespace

from app.services.ds260_mapping import enrich_empty_fields_from_all_doc_records, load_ds260_sections


def _ws(raw: dict) -> SimpleNamespace:
    return SimpleNamespace(
        doc_type="ds260_customer_form",
        variant="exception",
        form_data=json.dumps(raw),
        raw_data=json.dumps(raw),
        updated_at=None,
        id="ws",
        source_document_id="ws-doc",
    )


def test_death_section_not_filled_from_worksheet_without_death_cert():
    ws = _ws({"gender": "FEMALE", "passport_number": "P0668328"})
    sections = [
        {
            "id": "section_death",
            "fields": [
                {"key": "death_deceased_name", "value": "", "source": {}},
                {"key": "death_document_number", "value": "", "source": {}},
            ],
        }
    ]
    enrich_empty_fields_from_all_doc_records(sections, [ws], {})
    by_key = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert by_key["death_deceased_name"] == ""
    assert by_key["death_document_number"] == ""
