"""DS-260 parent (father/mother) fields from birth certificate."""

import json
from types import SimpleNamespace
from uuid import uuid4

from app.services.ds260_mapping import (
    has_father_info_on_birth_cert,
    has_mother_info_on_birth_cert,
    has_parent_info_on_birth_cert,
    reconcile_parent_living_status,
)


def _rec(form: dict | None = None, *, raw: dict | None = None, doc_type: str | None = "birth_certificate") -> SimpleNamespace:
    return SimpleNamespace(
        form_data=json.dumps(form or {}),
        raw_data=json.dumps(raw or {}),
        doc_type=doc_type,
    )


def test_no_mother_info():
    rec = _rec({"full_name": "CHILD", "father_surname": "TRAN"})
    assert has_mother_info_on_birth_cert(rec) is False


def test_na_mother_name_is_not_info():
    rec = _rec({"mother_name": "N/A"})
    assert has_mother_info_on_birth_cert(rec) is False


def test_has_mother_surname():
    rec = _rec({"mother_surname": "LE", "mother_given_names": "THI C"})
    assert has_mother_info_on_birth_cert(rec) is True


def test_parent_generic():
    rec = _rec({"mother_name": "LE THI D"})
    assert has_parent_info_on_birth_cert(rec, "mother") is True
    assert has_father_info_on_birth_cert(rec) is False


def test_mother_residence_and_nationality_never_leak_into_birth_place():
    """Giấy khai sinh VN chỉ ghi NƠI THƯỜNG TRÚ + QUỐC TỊCH hiện tại của mẹ, KHÔNG ghi nơi mẹ
    được SINH RA — mother_city/address/country (thường trú/quốc tịch) KHÔNG được coi là
    mother_birth_city/state/country (khách yêu cầu 2026-08-12: tránh đọc nơi thường trú/quốc
    tịch cha/mẹ ra thành nơi sinh của họ). Các field ngày sinh vẫn phải điền bình thường."""
    from app.services.ds260_mapping import _resolve_ds260_field_value, flatten_ds260_mappings

    raw = {
        "mother_name": "ĐẶNG THỊ TIÊM",
        "mother_date_of_birth": "1954-01-01",
        "mother_city": "Đà Nẵng",
        "mother_address": "An Đồn, An Hải Bắc, thành phố Đà Nẵng",
        "mother_country": "Việt Nam",
    }
    rec = _rec(raw=raw)
    mappings = flatten_ds260_mappings()

    dob, _ = _resolve_ds260_field_value(mappings["mother_date_of_birth"], rec)
    city, _ = _resolve_ds260_field_value(mappings["mother_birth_city"], rec)
    state, _ = _resolve_ds260_field_value(mappings["mother_birth_state"], rec)
    country, _ = _resolve_ds260_field_value(mappings["mother_birth_country"], rec)

    assert dob == "1954-01-01"
    assert city == ""
    assert state == ""
    assert country == ""


def test_mother_explicit_birth_place_still_resolves():
    """Khi giấy khai sinh CÓ ghi rõ nơi sinh của mẹ (field birth-place thật, không phải thường
    trú), vẫn phải điền bình thường vào birth_city/state/country."""
    from app.services.ds260_mapping import _resolve_ds260_field_value, flatten_ds260_mappings

    raw = {
        "mother_name": "ĐẶNG THỊ TIÊM",
        "mother_birth_place": "Hue, Thua Thien Hue",
    }
    rec = _rec(raw=raw)
    mappings = flatten_ds260_mappings()

    state, _ = _resolve_ds260_field_value(mappings["mother_birth_state"], rec)
    country, _ = _resolve_ds260_field_value(mappings["mother_birth_country"], rec)

    assert "Hue" in state
    assert country == "Vietnam"


def _section_father(is_living: str, death_year: str, address: str = "123 Some St") -> list[dict]:
    return [
        {
            "id": "section_father",
            "fields": [
                {"key": "father_is_living", "value": is_living, "source": {}},
                {"key": "father_death_year", "value": death_year, "source": {}},
                {"key": "father_address", "value": address, "source": {}},
            ],
        }
    ]


def test_na_death_year_does_not_flip_living_status_to_no():
    """Báo lỗi thực tế 2026-08-17 (hồ sơ TRUONG THI MY LE): worksheet ghi rõ father_is_living=Yes
    và father_death_year="N/A" (nghĩa là KHÔNG có năm mất) — "N/A" từng bị hiểu nhầm là giá trị
    thật, tự động đổi is_living thành "No" và xóa hết địa chỉ cha còn sống."""
    sections = _section_father("Yes", "N/A")
    reconcile_parent_living_status(sections)
    fields = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert fields["father_is_living"] == "Yes"


def test_real_death_year_still_flips_living_status_to_no():
    sections = _section_father("Yes", "2010")
    reconcile_parent_living_status(sections)
    fields = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert fields["father_is_living"] == "No"


def _doc_rec(raw: dict, doc_type: str, *, variant: str = "standard") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        doc_type=doc_type,
        variant=variant,
        source_document_id=uuid4(),
        form_data=json.dumps(raw),
        raw_data=json.dumps(raw),
        updated_at=None,
    )


def test_reconcile_parent_living_addresses_same_as_applicant():
    """Cha/mẹ còn sống, địa chỉ ghi 'Cùng địa chỉ' -> tự động điền đầy đủ từ địa chỉ đương đơn."""
    from app.services.ds260_mapping import reconcile_parent_living_addresses

    sections = [
        {
            "id": "section_address",
            "fields": [
                {"key": "current_address", "value": "123 Le Loi, Phuong 1", "source": {}},
                {"key": "current_city", "value": "My Tho", "source": {}},
                {"key": "current_state", "value": "Tien Giang", "source": {}},
                {"key": "postal_code", "value": "86000", "source": {}},
                {"key": "current_country", "value": "Vietnam", "source": {}},
            ],
        },
        {
            "id": "section_father",
            "fields": [
                {"key": "father_surname", "value": "NGUYEN", "source": {}},
                {"key": "father_given_names", "value": "VAN A", "source": {}},
                {"key": "father_is_living", "value": "Yes", "source": {}},
                {"key": "father_death_year", "value": "", "source": {}},
                {"key": "father_address", "value": "Cùng địa chỉ", "source": {}},
                {"key": "father_city", "value": "", "source": {}},
                {"key": "father_state", "value": "", "source": {}},
                {"key": "father_postal_code", "value": "", "source": {}},
                {"key": "father_country", "value": "", "source": {}},
            ],
        },
    ]

    reconcile_parent_living_addresses(sections)

    father_fields = {f["key"]: f["value"] for f in sections[1]["fields"]}
    assert father_fields["father_address"] == "123 Le Loi, Phuong 1"
    assert father_fields["father_city"] == "My Tho"
    assert father_fields["father_state"] == "Tien Giang"
    assert father_fields["father_postal_code"] == "86000"
    assert father_fields["father_country"] == "Vietnam"


def test_reconcile_parent_living_addresses_derived_from_street():
    """Cha/mẹ còn sống có địa chỉ đường chi tiết nhưng thiếu City/State -> tự động phân tích."""
    from app.services.ds260_mapping import reconcile_parent_living_addresses

    sections = [
        {
            "id": "section_address",
            "fields": [
                {"key": "current_address", "value": "Ap Vinh An, Xa Binh Gia", "source": {}},
                {"key": "current_city", "value": "Chau Duc", "source": {}},
                {"key": "current_state", "value": "Ba Ria-Vung Tau", "source": {}},
                {"key": "postal_code", "value": "78607", "source": {}},
                {"key": "current_country", "value": "Vietnam", "source": {}},
            ],
        },
        {
            "id": "section_father",
            "fields": [
                {"key": "father_is_living", "value": "Yes", "source": {}},
                {"key": "father_death_year", "value": "", "source": {}},
                {"key": "father_address", "value": "Ap Vinh An, Xa Binh Gia, Huyen Chau Duc, Tinh Ba Ria-Vung Tau", "source": {}},
                {"key": "father_city", "value": "", "source": {}},
                {"key": "father_state", "value": "", "source": {}},
                {"key": "father_postal_code", "value": "", "source": {}},
                {"key": "father_country", "value": "", "source": {}},
            ],
        },
    ]

    reconcile_parent_living_addresses(sections)

    father_fields = {f["key"]: f["value"] for f in sections[1]["fields"]}
    assert "Chau Duc" in father_fields["father_city"]
    assert "Ba Ria-Vung Tau" in father_fields["father_state"]
    assert father_fields["father_country"] == "Vietnam"
    assert father_fields["father_postal_code"] == "78607"


def test_reconcile_parent_living_addresses_same_household():
    """Cả cha và mẹ cùng còn sống, một người có địa chỉ đầy đủ còn người kia để trống -> tự động điền."""
    from app.services.ds260_mapping import reconcile_parent_living_addresses

    sections = [
        {
            "id": "section_father",
            "fields": [
                {"key": "father_is_living", "value": "Yes", "source": {}},
                {"key": "father_address", "value": "456 Tran Hung Dao", "source": {}},
                {"key": "father_city", "value": "Da Nang", "source": {}},
                {"key": "father_state", "value": "Da Nang", "source": {}},
                {"key": "father_postal_code", "value": "55000", "source": {}},
                {"key": "father_country", "value": "Vietnam", "source": {}},
            ],
        },
        {
            "id": "section_mother",
            "fields": [
                {"key": "mother_is_living", "value": "Yes", "source": {}},
                {"key": "mother_address", "value": "", "source": {}},
                {"key": "mother_city", "value": "", "source": {}},
                {"key": "mother_state", "value": "", "source": {}},
                {"key": "mother_postal_code", "value": "", "source": {}},
                {"key": "mother_country", "value": "", "source": {}},
            ],
        },
    ]

    reconcile_parent_living_addresses(sections)

    mother_fields = {f["key"]: f["value"] for f in sections[1]["fields"]}
    assert mother_fields["mother_address"] == "456 Tran Hung Dao"
    assert mother_fields["mother_city"] == "Da Nang"
    assert mother_fields["mother_state"] == "Da Nang"
    assert mother_fields["mother_postal_code"] == "55000"
    assert mother_fields["mother_country"] == "Vietnam"


def test_other_addresses_used_reconciled_to_yes_when_history_exists():
    """Khi prior address history có dữ liệu -> other_addresses_used bắt buộc phải là Yes."""
    from app.services.ds260_mapping import reconcile_ds260_yesno_and_death_year

    sections = [
        {
            "id": "section_address",
            "fields": [
                {"key": "other_addresses_used", "value": "No", "source": {}},
                {
                    "key": "other_addresses_history",
                    "value": "2015-2018: 123 Nguyen Trai, Q5, TP.HCM\n2018-2021: 456 Le Loi, Q1, TP.HCM",
                    "source": {},
                },
            ],
        }
    ]

    reconcile_ds260_yesno_and_death_year(sections)

    fields = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert fields["other_addresses_used"] == "Yes"


def test_other_addresses_used_left_empty_when_not_provided():
    """Khi prior address history trống và khách không khai -> other_addresses_used để trống, không tự điền No."""
    from app.services.ds260_mapping import reconcile_ds260_yesno_and_death_year

    sections = [
        {
            "id": "section_address",
            "fields": [
                {"key": "other_addresses_used", "value": "", "source": {}},
                {"key": "other_addresses_history", "value": "", "source": {}},
            ],
        }
    ]

    reconcile_ds260_yesno_and_death_year(sections)

    fields = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert fields["other_addresses_used"] == ""




