"""Case D: vợ goá + con — marital Widowed, cha/mẹ từ lý lịch tư pháp, báo tử."""

import json
from types import SimpleNamespace


def _rec(raw: dict, doc_type: str, variant: str = "standard", rid: str = "1") -> SimpleNamespace:
    return SimpleNamespace(
        doc_type=doc_type,
        variant=variant,
        form_data=json.dumps(raw),
        raw_data=json.dumps(raw),
        updated_at=None,
        id=rid,
        source_document_id=None,
    )


def test_marital_status_widowed_when_spouse_deceased():
    from app.services.ds260_mapping import enrich_marital_status_from_documents

    marriage = _rec(
        {"husband_full_name": "NGUYEN VAN LIEU", "wife_full_name": "KHUC THI LE HANG"},
        "marriage_certificate",
    )
    passport = _rec({"full_name": "KHUC THI LE HANG", "gender": "FEMALE"}, "passport")
    death = _rec(
        {"deceased_full_name": "NGUYEN VAN LIEU", "date_of_death": "2019-09-12"},
        "death_certificate",
    )
    fields = [{"key": "current_marital_status", "value": "", "source": {}}]
    enrich_marital_status_from_documents(
        fields, None, marriage_rec=marriage, passport_rec=passport, death_rec=death
    )
    assert fields[0]["value"] == "Widowed"


def test_marital_status_married_when_spouse_alive():
    from app.services.ds260_mapping import enrich_marital_status_from_documents

    marriage = _rec(
        {"husband_full_name": "TRAN VAN A", "wife_full_name": "LE THI B"},
        "marriage_certificate",
    )
    passport = _rec({"full_name": "LE THI B", "gender": "FEMALE"}, "passport")
    fields = [{"key": "current_marital_status", "value": "", "source": {}}]
    enrich_marital_status_from_documents(
        fields, None, marriage_rec=marriage, passport_rec=passport, death_rec=None
    )
    assert fields[0]["value"] == "Married"


def test_parent_names_from_judicial_fill_when_empty():
    from app.services.ds260_mapping import enrich_parent_names_from_judicial

    judicial = _rec(
        {
            "full_name": "KHUC THI LE HANG",
            "father_name": "KHUC THUA LANH",
            "mother_name": "HO THI PHUONG",
        },
        "judicial_certificate",
    )
    father_fields = [
        {"key": "father_full_name", "value": "", "source": {}},
        {"key": "father_surname", "value": "", "source": {}},
        {"key": "father_given_names", "value": "", "source": {}},
    ]
    enrich_parent_names_from_judicial(father_fields, [judicial], "father", "KHUC THI LE HANG")
    got = {f["key"]: f["value"] for f in father_fields}
    assert got["father_full_name"] == "KHUC THUA LANH"
    assert got["father_surname"] == "KHUC"
    assert got["father_given_names"] == "THUA LANH"

    mother_fields = [
        {"key": "mother_full_name", "value": "", "source": {}},
        {"key": "mother_surname", "value": "", "source": {}},
        {"key": "mother_given_names", "value": "", "source": {}},
    ]
    enrich_parent_names_from_judicial(mother_fields, [judicial], "mother", "KHUC THI LE HANG")
    mgot = {f["key"]: f["value"] for f in mother_fields}
    assert mgot["mother_full_name"] == "HO THI PHUONG"
    assert mgot["mother_surname"] == "HO"


def test_parent_names_from_judicial_does_not_override_birth_cert():
    from app.services.ds260_mapping import enrich_parent_names_from_judicial

    judicial = _rec(
        {"full_name": "KHUC THI LE HANG", "father_name": "JUDICIAL FATHER"},
        "judicial_certificate",
    )
    fields = [{"key": "father_full_name", "value": "BIRTH CERT FATHER", "source": {}}]
    enrich_parent_names_from_judicial(fields, [judicial], "father", "KHUC THI LE HANG")
    assert fields[0]["value"] == "BIRTH CERT FATHER"


def test_parent_death_overrides_is_living_yes():
    from app.services.ds260_mapping import enrich_parent_death_from_death_cert

    death = _rec(
        {"deceased_full_name": "NGUYEN VAN LIEU", "date_of_death": "2019-09-12"},
        "death_certificate",
    )
    fields = [
        {"key": "father_is_living", "value": "Yes", "source": {}},
        {"key": "father_death_year", "value": "", "source": {}},
    ]
    enrich_parent_death_from_death_cert(fields, death, "father", "NGUYEN VAN LIEU")
    got = {f["key"]: f["value"] for f in fields}
    assert got["father_is_living"] == "No"
    assert got["father_death_year"] == "2019"


def test_previous_spouse_from_death():
    from app.services.ds260_mapping import enrich_previous_spouse_from_death

    marriage = _rec(
        {
            "husband_full_name": "NGUYEN VAN LIEU",
            "wife_full_name": "KHUC THI LE HANG",
            "husband_date_of_birth": "1969-03-08",
            "marriage_date": "1995-07-08",
        },
        "marriage_certificate",
    )
    passport = _rec({"full_name": "KHUC THI LE HANG", "gender": "FEMALE"}, "passport")
    death = _rec(
        {"deceased_full_name": "NGUYEN VAN LIEU", "date_of_death": "2019-09-12"},
        "death_certificate",
    )
    fields = [
        {"key": "previous_spouses_used", "value": "", "source": {}},
        {"key": "previous_spouse_full_name", "value": "", "source": {}},
        {"key": "previous_spouse_date_of_birth", "value": "", "source": {}},
        {"key": "previous_marriage_date", "value": "", "source": {}},
        {"key": "previous_divorce_date", "value": "", "source": {}},
    ]
    enrich_previous_spouse_from_death(fields, [marriage, passport, death], passport)
    got = {f["key"]: f["value"] for f in fields}
    assert got["previous_spouses_used"] == "Yes"
    assert got["previous_spouse_full_name"] == "NGUYEN VAN LIEU"
    assert got["previous_spouse_date_of_birth"] == "1969-03-08"
    assert got["previous_divorce_date"] == "2019-09-12"


def test_gender_token_not_bled_into_name_field():
    from app.services.ds260_mapping import enrich_empty_fields_from_all_doc_records

    # Một record có 'father_name' = 'FEMALE' (OCR rác) không được lọt vào father_full_name.
    junk = _rec({"father_name": "FEMALE"}, "birth_certificate")
    sections = [
        {"id": "section_father", "fields": [{"key": "father_full_name", "value": "", "source": {}}]},
    ]
    enrich_empty_fields_from_all_doc_records(sections, [junk], {})
    assert sections[0]["fields"][0]["value"] != "FEMALE"
