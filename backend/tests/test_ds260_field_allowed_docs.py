"""Every DS-260 mapping field must have an explicit field-level allowlist entry."""

import json
from pathlib import Path

from app.services.ds260_field_allowed_docs import _FIELD_ALLOWED_DOCS, build_field_allowed_docs


def test_every_mapping_field_has_explicit_allowlist():
    mapping_path = Path(__file__).resolve().parents[1] / "data" / "doc_schemas" / "ds260_mapping.json"
    with mapping_path.open(encoding="utf-8") as f:
        data = json.load(f)

    keys: set[str] = set()
    for sec in data.get("sections", []):
        for field in sec.get("fields", []):
            if field["document"] == "spouse_applicant_profile":
                continue
            keys.add(field["key"])

    missing = sorted(keys - set(_FIELD_ALLOWED_DOCS))
    assert not missing, f"Missing explicit FIELD_ALLOWED_DOCS for: {missing}"


def test_build_covers_all_mapping_fields():
    mapping_path = Path(__file__).resolve().parents[1] / "data" / "doc_schemas" / "ds260_mapping.json"
    with mapping_path.open(encoding="utf-8") as f:
        data = json.load(f)

    expected: set[str] = set()
    for sec in data.get("sections", []):
        for field in sec.get("fields", []):
            if field["document"] == "spouse_applicant_profile":
                continue
            expected.add(field["key"])

    built = build_field_allowed_docs()
    assert set(built) == expected
