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
    # Ô "Date of Divorce" có sẵn giá trị sai (ngày mất) — phải bị XÓA vì người goá không ly hôn.
    for f in fields:
        if f["key"] == "previous_divorce_date":
            f["value"] = "2019-09-12"
    enrich_previous_spouse_from_death(fields, [marriage, passport, death], passport)
    got = {f["key"]: f["value"] for f in fields}
    assert got["previous_spouses_used"] == "Yes"
    assert got["previous_spouse_full_name"] == "NGUYEN VAN LIEU"
    assert got["previous_spouse_date_of_birth"] == "1969-03-08"
    assert got["previous_marriage_date"] == "1995-07-08"
    # Người goá KHÔNG ly hôn → tuyệt đối không để ngày mất vào ô "Date of Divorce".
    assert got["previous_divorce_date"] == ""


def test_gender_token_not_bled_into_name_field():
    from app.services.ds260_mapping import enrich_empty_fields_from_all_doc_records

    # Một record có 'father_name' = 'FEMALE' (OCR rác) không được lọt vào father_full_name.
    junk = _rec({"father_name": "FEMALE"}, "birth_certificate")
    sections = [
        {"id": "section_father", "fields": [{"key": "father_full_name", "value": "", "source": {}}]},
    ]
    enrich_empty_fields_from_all_doc_records(sections, [junk], {})
    assert sections[0]["fields"][0]["value"] != "FEMALE"


def _mk(key: str, value: str) -> dict:
    return {"key": key, "value": value, "source": {}}


def test_yesno_na_becomes_no():
    """B4: câu hỏi Yes/No để 'N/A' hoặc trống-không-dữ-liệu → 'No'."""
    from app.services.ds260_mapping import reconcile_ds260_yesno_and_death_year

    sections = [
        {
            "id": "section_additional",
            "fields": [
                _mk("military_served", "N/A"),
                _mk("military_full_name", ""),
                _mk("work_prior_jobs_used", "N/A"),
                _mk("work_prior_jobs_history", ""),
                _mk("children_used", ""),
                _mk("child_1_full_name", ""),
                _mk("other_emails_used", ""),
                _mk("other_emails_history", ""),
            ],
        }
    ]
    reconcile_ds260_yesno_and_death_year(sections)
    got = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert got["military_served"] == "No"
    assert got["work_prior_jobs_used"] == "No"
    assert got["children_used"] == "No"
    assert got["other_emails_used"] == "No"


def test_yesno_left_alone_when_evidence_present():
    """Có dữ liệu kèm (military doc) → KHÔNG tự chốt No, để review; giá trị Yes giữ nguyên."""
    from app.services.ds260_mapping import reconcile_ds260_yesno_and_death_year

    sections = [
        {
            "id": "section_additional",
            "fields": [
                _mk("military_served", ""),
                _mk("military_full_name", "NGUYEN VAN A"),
                _mk("other_phones_used", "Yes"),
                _mk("other_phones_history", "+84 909 000 111"),
            ],
        }
    ]
    reconcile_ds260_yesno_and_death_year(sections)
    got = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert got["military_served"] == ""       # có bằng chứng → để trống cho review
    assert got["other_phones_used"] == "Yes"  # đáp án Yes hợp lệ → giữ nguyên


def test_is_living_na_not_forced_to_no():
    """*_is_living để 'N/A' KHÔNG được ép 'No' (sẽ hoá thành 'đã mất' — bịa)."""
    from app.services.ds260_mapping import reconcile_ds260_yesno_and_death_year

    sections = [{"id": "section_father", "fields": [_mk("father_is_living", "N/A")]}]
    reconcile_ds260_yesno_and_death_year(sections)
    assert sections[0]["fields"][0]["value"] == "N/A"


def test_death_year_full_date_reduced_to_year():
    """A4: '*_death_year' lỡ là ngày đầy đủ → rút về năm; năm sẵn có giữ nguyên."""
    from app.services.ds260_mapping import reconcile_ds260_yesno_and_death_year

    sections = [
        {
            "id": "section_father",
            "fields": [
                _mk("father_death_year", "07/09/2006"),
                _mk("mother_death_year", "2013"),
            ],
        }
    ]
    reconcile_ds260_yesno_and_death_year(sections)
    got = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert got["father_death_year"] == "2006"
    assert got["mother_death_year"] == "2013"


def test_other_name_used_defaults_to_no_without_checking_evidence():
    """Other Names (details): luôn điền 'No' khi trống, không cần kiểm tra other_names.
    Nếu người dùng thực sự có tên khác, họ sẽ tự sửa thành 'Yes' trên worksheet."""
    from app.services.ds260_mapping import reconcile_ds260_yesno_and_death_year

    sections = [
        {
            "id": "section_a_personal",
            "fields": [
                _mk("other_name_used", ""),       # trống
                _mk("other_names", "NGUYEN VAN B"),  # có dữ liệu nhưng không cần check
            ],
        }
    ]
    reconcile_ds260_yesno_and_death_year(sections)
    got = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert got["other_name_used"] == "No"  # vẫn điền No dù có evidence


def test_other_name_used_na_becomes_no():
    """Other Name Used = 'N/A' → 'No'."""
    from app.services.ds260_mapping import reconcile_ds260_yesno_and_death_year

    sections = [
        {
            "id": "section_a_personal",
            "fields": [
                _mk("other_name_used", "N/A"),
            ],
        }
    ]
    reconcile_ds260_yesno_and_death_year(sections)
    got = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert got["other_name_used"] == "No"


def test_other_name_used_yes_preserved():
    """Other Name Used = 'Yes' → giữ nguyên (không đè thành No)."""
    from app.services.ds260_mapping import reconcile_ds260_yesno_and_death_year

    sections = [
        {
            "id": "section_a_personal",
            "fields": [
                _mk("other_name_used", "Yes"),
            ],
        }
    ]
    reconcile_ds260_yesno_and_death_year(sections)
    got = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert got["other_name_used"] == "Yes"


def test_been_in_us_yes_when_us_visa_document_present():
    """Có US Visa document (visa dán trong passport, entry stamp) → been_in_us = Yes."""
    from app.services.ds260_mapping import reconcile_ds260_yesno_and_death_year

    sections = [
        {
            "id": "section_c_travel",
            "fields": [
                _mk("been_in_us", ""),
                _mk("issued_us_visa", ""),
                _mk("visa_type", "B1/B2"),
                _mk("entry_stamp", "US ENTRY"),
            ],
        }
    ]
    reconcile_ds260_yesno_and_death_year(sections)
    got = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert got["been_in_us"] == "Yes"
    assert got["issued_us_visa"] == "Yes"


def test_been_in_us_stays_empty_when_no_us_visa_document():
    """Không có US Visa document và been_in_us trống → để trống."""
    from app.services.ds260_mapping import reconcile_ds260_yesno_and_death_year

    sections = [
        {
            "id": "section_c_travel",
            "fields": [
                _mk("been_in_us", ""),
                _mk("issued_us_visa", ""),
            ],
        }
    ]
    reconcile_ds260_yesno_and_death_year(sections)
    got = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert got["been_in_us"] == ""
    assert got["issued_us_visa"] == ""


def test_been_in_us_preserved_when_already_answered():
    """been_in_us đã có giá trị Yes/No → giữ nguyên, không bị ghi đè."""
    from app.services.ds260_mapping import reconcile_ds260_yesno_and_death_year

    sections = [
        {
            "id": "section_c_travel",
            "fields": [
                _mk("been_in_us", "Yes"),
                _mk("issued_us_visa", "Yes"),
                _mk("visa_type", "F1"),
            ],
        }
    ]
    reconcile_ds260_yesno_and_death_year(sections)
    got = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert got["been_in_us"] == "Yes"
    assert got["issued_us_visa"] == "Yes"


def test_been_in_us_na_becomes_yes_with_visa():
    """been_in_us = N/A nhưng có US Visa → Yes."""
    from app.services.ds260_mapping import reconcile_ds260_yesno_and_death_year

    sections = [
        {
            "id": "section_c_travel",
            "fields": [
                _mk("been_in_us", "N/A"),
                _mk("visa_number", "AA1234567"),
            ],
        }
    ]
    reconcile_ds260_yesno_and_death_year(sections)
    got = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert got["been_in_us"] == "Yes"


def test_been_in_us_na_stays_empty_without_visa():
    """been_in_us = N/A và không có US Visa → để trống."""
    from app.services.ds260_mapping import reconcile_ds260_yesno_and_death_year

    sections = [
        {
            "id": "section_c_travel",
            "fields": [
                _mk("been_in_us", "N/A"),
            ],
        }
    ]
    reconcile_ds260_yesno_and_death_year(sections)
    got = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert got["been_in_us"] == "N/A"

