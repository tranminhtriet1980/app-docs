import uuid
from app.models.entities import ApplicantDocRecord
from app.services.ds260_mapping import (
    reconcile_military_section,
    empty_ds260_field_source,
    _eligible_records_for_field_fill,
    _section_primary_doc_present,
    pick_luong1_pair_for_person,
)


def _mk_field(key: str, value: str, derived: str = "") -> dict:
    return {
        "key": key,
        "label": key,
        "value": value,
        "source": {
            **empty_ds260_field_source(),
            "derived": derived,
        }
    }


def test_reconcile_military_section_clears_fields_when_served_no():
    sections = [
        {
            "id": "section_military",
            "fields": [
                _mk_field("military_served", "No"),
                _mk_field("military_full_name", "NGUYEN VAN A"),
                _mk_field("military_country", "Vietnam"),
                _mk_field("military_branch", "Army"),
                _mk_field("military_rank", "Private"),
                _mk_field("military_specialty", "Infantry"),
                _mk_field("military_service_start", "2010-01-01"),
                _mk_field("military_service_end", "2012-01-01"),
                _mk_field("military_document_number", "123456"),
            ],
        }
    ]
    reconcile_military_section(sections)
    got = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert got["military_served"] == "No"
    assert got["military_full_name"] == ""
    assert got["military_country"] == ""
    assert got["military_branch"] == ""
    assert got["military_rank"] == ""
    assert got["military_specialty"] == ""
    assert got["military_service_start"] == ""
    assert got["military_service_end"] == ""
    assert got["military_document_number"] == ""


def test_reconcile_military_section_preserves_fields_when_served_yes():
    sections = [
        {
            "id": "section_military",
            "fields": [
                _mk_field("military_served", "Yes"),
                _mk_field("military_full_name", "TRAN VAN B"),
                _mk_field("military_country", "Vietnam"),
                _mk_field("military_branch", "Air Force"),
                _mk_field("military_rank", "Captain"),
                _mk_field("military_specialty", "Pilot"),
                _mk_field("military_service_start", "2010-01-01"),
                _mk_field("military_service_end", "2015-01-01"),
                _mk_field("military_document_number", "987654"),
            ],
        }
    ]
    reconcile_military_section(sections)
    got = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert got["military_served"] == "Yes"
    assert got["military_full_name"] == "TRAN VAN B"
    assert got["military_country"] == "Vietnam"
    assert got["military_branch"] == "Air Force"
    assert got["military_rank"] == "Captain"
    assert got["military_specialty"] == "Pilot"
    assert got["military_service_start"] == "2010-01-01"
    assert got["military_service_end"] == "2015-01-01"
    assert got["military_document_number"] == "987654"


def test_reconcile_military_section_respects_manual_override():
    sections = [
        {
            "id": "section_military",
            "fields": [
                _mk_field("military_served", "No"),
                _mk_field("military_full_name", "NGUYEN VAN A", derived="manual_override"),
                _mk_field("military_branch", "Army"),
            ],
        }
    ]
    reconcile_military_section(sections)
    got = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert got["military_served"] == "No"
    assert got["military_full_name"] == "NGUYEN VAN A"  # manual override kept
    assert got["military_branch"] == ""                 # non-override cleared


def test_military_discharge_scoped_to_person():
    spouse_doc = ApplicantDocRecord(
        id=uuid.uuid4(),
        doc_type="military_discharge",
        variant="standard",
        raw_data='{"full_name": "TRAN THI B", "military_branch": "Navy"}',
    )
    records = [spouse_doc]

    # For Principal applicant (NGUYEN VAN A): spouse's doc should NOT match
    std, ref = pick_luong1_pair_for_person(records, "military_discharge", "NGUYEN VAN A")
    assert std is None
    assert ref is None

    # For Spouse (TRAN THI B): spouse's doc SHOULD match
    std, ref = pick_luong1_pair_for_person(records, "military_discharge", "TRAN THI B")
    assert std is not None
    assert std.id == spouse_doc.id

    # Check eligible records for filling
    eligible_app = _eligible_records_for_field_fill(records, "NGUYEN VAN A", "military_branch")
    assert len(eligible_app) == 0

    eligible_spouse = _eligible_records_for_field_fill(records, "TRAN THI B", "military_branch")
    assert len(eligible_spouse) == 1

    # Check section primary doc present
    assert not _section_primary_doc_present(records, "section_military", person_name="NGUYEN VAN A")
    assert _section_primary_doc_present(records, "section_military", person_name="TRAN THI B")
