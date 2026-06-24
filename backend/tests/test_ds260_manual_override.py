"""Chỉnh tay DS-260 trước export — manual override."""

from app.services.ds260_conflicts import (
    apply_ds260_manual_overrides,
    ds260_manual_field_key,
    is_ds260_manual_field_key,
    is_ds260_conflict_field,
)


def test_ds260_manual_field_key():
    assert ds260_manual_field_key("applicant_name") == "ds260.manual.applicant_name"
    assert is_ds260_manual_field_key("ds260.manual.gender") is True
    assert is_ds260_manual_field_key("ds260.passport.full_name") is False
    assert is_ds260_conflict_field("ds260.passport.full_name") is True
    assert is_ds260_conflict_field("ds260.manual.applicant_name") is False


def test_apply_ds260_manual_overrides():
    sections = [
        {
            "fields": [
                {"key": "applicant_name", "value": "FROM OCR", "source": {"document_type": "passport"}},
                {"key": "gender", "value": "Male", "source": {}},
            ]
        }
    ]
    apply_ds260_manual_overrides(sections, {"applicant_name": "DANG VAN HUNG (edited)"})
    by_key = {f["key"]: f for f in sections[0]["fields"]}
    assert by_key["applicant_name"]["value"] == "DANG VAN HUNG (edited)"
    assert by_key["applicant_name"]["source"]["derived"] == "manual_override"
    assert by_key["gender"]["value"] == "Male"
