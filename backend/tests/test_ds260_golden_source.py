"""reattribute_matching_worksheet_sources — golden source: DS-260 worksheet value that matches
Application form should display as sourced from application_form (value unchanged); a genuine
mismatch must leave the worksheet source AND still produce a document_vs_worksheet conflict row
(same predicates as build_worksheet_conflict_rows, so attribution and conflict never disagree)."""

import json
from types import SimpleNamespace
from uuid import uuid4

from app.services.ds260_conflicts import build_worksheet_conflict_rows, worksheet_conflict_field_key
from app.services.ds260_mapping import reattribute_matching_worksheet_sources


def _rec(raw: dict, doc_type: str, *, variant: str = "standard") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        doc_type=doc_type,
        variant=variant,
        source_document_id=uuid4(),
        form_data=json.dumps(raw),
        raw_data=json.dumps(raw),
        updated_at=None,
    )


def _sections(key: str, value: str) -> list[dict]:
    return [
        {
            "id": "sec",
            "fields": [
                {
                    "key": key,
                    "value": value,
                    "source": {
                        "document_type": "ds260_customer_form",
                        "source_field": key,
                        "document_id": None,
                        "document_filename": None,
                        "variant": "exception",
                        "record_id": None,
                    },
                }
            ],
        }
    ]


def test_matching_address_reattributed_to_application_form():
    application = _rec({"current_address": "123 LE LOI"}, "application_form")
    ds260 = _rec({"current_address": "123 LE LOI"}, "ds260_customer_form", variant="exception")
    sections = _sections("current_address", "123 LE LOI")

    reattribute_matching_worksheet_sources(sections, [application, ds260], {})

    field = sections[0]["fields"][0]
    assert field["source"]["document_type"] == "application_form"
    assert field["source"]["derived"] == "golden_source_application_form"
    assert field["value"] == "123 LE LOI"  # value never changes, only the displayed source

    # Attribution parity: a matched field must never also produce a conflict row.
    rows = build_worksheet_conflict_rows([application, ds260], {})
    keys = {r["field_key"] for r in rows}
    assert worksheet_conflict_field_key("current_address") not in keys


def test_mismatched_address_keeps_worksheet_source_and_creates_conflict():
    application = _rec({"current_address": "123 LE LOI"}, "application_form")
    ds260 = _rec({"current_address": "456 TRAN PHU"}, "ds260_customer_form", variant="exception")
    sections = _sections("current_address", "456 TRAN PHU")

    reattribute_matching_worksheet_sources(sections, [application, ds260], {})

    field = sections[0]["fields"][0]
    assert field["source"]["document_type"] == "ds260_customer_form"
    assert "derived" not in field["source"]

    rows = build_worksheet_conflict_rows([application, ds260], {})
    keys = {r["field_key"] for r in rows}
    assert worksheet_conflict_field_key("current_address") in keys


def test_matching_work_fields_reattributed():
    application = _rec(
        {"primary_occupation": "Sales Staff", "present_employer": "ABC Co"}, "application_form"
    )
    ds260 = _rec(
        {"primary_occupation": "sales staff", "present_employer": "abc co"},
        "ds260_customer_form",
        variant="exception",
    )
    sections = [
        {
            "id": "sec",
            "fields": [
                {
                    "key": "work_primary_occupation",
                    "value": "sales staff",
                    "source": {"document_type": "ds260_customer_form", "source_field": "work_primary_occupation"},
                },
                {
                    "key": "work_present_employer",
                    "value": "abc co",
                    "source": {"document_type": "ds260_customer_form", "source_field": "work_present_employer"},
                },
            ],
        }
    ]

    reattribute_matching_worksheet_sources(sections, [application, ds260], {})

    for field in sections[0]["fields"]:
        assert field["source"]["document_type"] == "application_form"
        assert field["source"]["derived"] == "golden_source_application_form"


def test_non_worksheet_source_is_untouched():
    # Field already sourced from a Luồng 1 document (not the worksheet) — nothing to reattribute.
    application = _rec({"current_address": "123 LE LOI"}, "application_form")
    sections = [
        {
            "id": "sec",
            "fields": [
                {
                    "key": "current_address",
                    "value": "123 LE LOI",
                    "source": {"document_type": "application_form", "source_field": "current_address"},
                }
            ],
        }
    ]

    reattribute_matching_worksheet_sources(sections, [application], {})

    field = sections[0]["fields"][0]
    assert field["source"]["document_type"] == "application_form"
    assert "derived" not in field["source"]


def test_empty_worksheet_value_is_untouched():
    application = _rec({"current_address": "123 LE LOI"}, "application_form")
    ds260 = _rec({}, "ds260_customer_form", variant="exception")
    sections = _sections("current_address", "")

    reattribute_matching_worksheet_sources(sections, [application, ds260], {})

    field = sections[0]["fields"][0]
    assert field["source"]["document_type"] == "ds260_customer_form"
