"""Applicant birth city/state in personal information section."""

import json
from types import SimpleNamespace

from app.services.ds260_mapping import enrich_applicant_birth_city_state_equal


def _rec(raw: dict, doc_type: str = "passport") -> SimpleNamespace:
    return SimpleNamespace(
        doc_type=doc_type,
        form_data=json.dumps(raw),
        raw_data=json.dumps(raw),
    )


def test_birth_city_and_state_equal_from_passport():
    passport = _rec(
        {
            "full_name": "DANG VAN HUNG",
            "place_of_birth": "An Don, An Hai Bac, Da Nang City, Vietnam",
            "birth_city": "",
        }
    )
    fields = [
        {"key": "place_of_birth", "value": "An Don, An Hai Bac, Da Nang City, Vietnam", "source": {}},
        {"key": "birth_city", "value": "", "source": {}},
        {"key": "birth_state", "value": "An Don, An Hai Bac, Da Nang City, Vietnam", "source": {}},
    ]
    enrich_applicant_birth_city_state_equal(fields, passport)
    by_key = {f["key"]: f["value"] for f in fields}
    assert by_key["birth_city"] == by_key["birth_state"]
    assert by_key["birth_city"] == "Da Nang City"


def test_worksheet_city_and_state_both_present_are_not_collapsed():
    """Ca thật (2026-08-04): City = địa chỉ đầy đủ, State = tên tỉnh riêng, KHÁC nhau.

    Trước đây hàm ép State = City (giá trị dài hơn thắng theo _canonical_applicant_birth_place),
    làm mất tên tỉnh thật; nếu City ngắn (vd. chỉ "Vinh Lac") thì bước normalize_ds260_place_fields
    chạy sau còn match nhầm sang tỉnh khác ("Vinh" → Nghệ An thay vì Yên Bái).
    """
    fields = [
        {"key": "birth_city", "value": "Xa Vinh Lac, Huyen Luc Yen, Tinh Yen Bai", "source": {}},
        {"key": "birth_state", "value": "Yen Bai", "source": {}},
    ]
    enrich_applicant_birth_city_state_equal(fields, None)
    by_key = {f["key"]: f["value"] for f in fields}
    # Không đè — giữ nguyên để normalize_ds260_place_fields (chạy cuối pipeline) tự tách đúng.
    assert by_key["birth_city"] == "Xa Vinh Lac, Huyen Luc Yen, Tinh Yen Bai"
    assert by_key["birth_state"] == "Yen Bai"


def test_export_birth_city_state_not_forced_equal():
    """Export không còn ép birth_state = birth_city đối với tỉnh (đã chuẩn hóa ở resolve)."""
    from app.services.export_ds260 import _prepare_display_values

    out = _prepare_display_values({"birth_city": "N/A", "birth_state": "Quang Tri"})
    assert out["birth_city"] == "N/A"
    assert out["birth_state"] == "Quang Tri"


def test_normalize_municipality_birthplace():
    """TP trực thuộc TW → City = TP, State = N/A."""
    from app.services.ds260_mapping import normalize_ds260_place_fields

    sections = [
        {
            "id": "section_a_personal",
            "fields": [
                {"key": "place_of_birth", "value": "An Don, An Hai Bac, Da Nang City, Vietnam", "source": {}},
                {"key": "birth_city", "value": "Khoa San Khu Vuc 2", "source": {}},
                {"key": "birth_state", "value": "An Don, An Hai Bac, Da Nang City", "source": {}},
                {"key": "birth_country", "value": "Vietnam", "source": {}},
            ],
        }
    ]
    normalize_ds260_place_fields(sections)
    by_key = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert by_key["birth_city"] == "Da Nang"
    assert by_key["birth_state"] == "N/A"


def test_normalize_hue_birthplace_as_municipality():
    """Huế lên TP trực thuộc TW (01/2025) → City = Hue, State = N/A; bỏ tên nhà hộ sinh.

    Trước đây ra ('N/A', 'Thua Thien Hue') — tester Case C-2 báo sai ở cả 5 thành viên.
    """
    from app.services.ds260_mapping import normalize_ds260_place_fields

    sections = [
        {
            "id": "section_father",
            "fields": [
                {"key": "father_birth_city", "value": "Nha Ho Sinh Khu Vuc II, Hue", "source": {}},
                {"key": "father_birth_state", "value": "To 1, Trung Giang, Huong Luu, Hue", "source": {}},
                {"key": "father_birth_country", "value": "Vietnam", "source": {}},
            ],
        }
    ]
    normalize_ds260_place_fields(sections)
    by_key = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert by_key["father_birth_city"] == "Hue"
    assert by_key["father_birth_state"] == "N/A"


def test_normalize_province_only_birthplace_keeps_na_city():
    """Chỉ có tên TỈNH, không có tên TP thuộc tỉnh → City = N/A."""
    from app.services.ds260_mapping import normalize_ds260_place_fields

    sections = [
        {
            "id": "section_father",
            "fields": [
                {"key": "father_birth_city", "value": "Benh vien Que Son, Quang Nam", "source": {}},
                {"key": "father_birth_state", "value": "Quang Nam", "source": {}},
                {"key": "father_birth_country", "value": "Vietnam", "source": {}},
            ],
        }
    ]
    normalize_ds260_place_fields(sections)
    by_key = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert by_key["father_birth_city"] == "N/A"
    assert by_key["father_birth_state"] == "Quang Nam"


def test_city_within_province_is_kept_not_dropped():
    """TP thuộc tỉnh → City = tên TP, State = tỉnh (lỗi 'bỏ mất Nha Trang' ở Case C)."""
    from app.services.ds260_mapping import normalize_ds260_place_fields

    sections = [
        {
            "id": "section_a_personal",
            "fields": [
                {"key": "birth_city", "value": "Nha Trang", "source": {}},
                {"key": "birth_state", "value": "Khanh Hoa", "source": {}},
                {"key": "birth_country", "value": "Vietnam", "source": {}},
            ],
        }
    ]
    normalize_ds260_place_fields(sections)
    by_key = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert by_key["birth_city"] == "Nha Trang"
    assert by_key["birth_state"] == "Khanh Hoa"


def test_ho_chi_minh_variations_set_state_to_na():
    """Bất kỳ biến thể nào của Hồ Chí Minh / TP.HCM / Thành Phố Hồ Chí Minh ở City -> State = N/A."""
    from app.services.ds260_mapping import normalize_ds260_place_fields

    variations = [
        "Hồ Chí Minh",
        "Thành phố Hồ Chí Minh",
        "Thành Phố Hồ Chí Minh",
        "TP. Hồ Chí Minh",
        "TP Hồ Chí Minh",
        "TP.HCM",
        "TPHCM",
        "Ho Chi Minh",
        "Ho Chi Minh City",
        "Hồ Chí Minh City",
        "Saigon",
        "Phường 1, Quận 3, TP. Hồ Chí Minh",
    ]
    for var in variations:
        sections = [
            {
                "id": "section_a_personal",
                "fields": [
                    {"key": "birth_city", "value": var, "source": {}},
                    {"key": "birth_state", "value": "Thành phố Hồ Chí Minh", "source": {}},
                    {"key": "birth_country", "value": "Vietnam", "source": {}},
                ],
            }
        ]
        normalize_ds260_place_fields(sections)
        by_key = {f["key"]: f["value"] for f in sections[0]["fields"]}
        assert by_key["birth_city"] == "Ho Chi Minh", f"Failed for {var}"
        assert by_key["birth_state"] == "N/A", f"Failed for {var}"


def test_central_municipalities_all_relatives_set_state_to_na():
    """Đương đơn, cha, mẹ, phối ngẫu, con cái: sinh ở TP trực thuộc TW -> City = TP, State = N/A."""
    from app.services.ds260_mapping import normalize_ds260_place_fields

    sections = [
        {
            "id": "family",
            "fields": [
                {"key": "birth_city", "value": "Thành phố Hồ Chí Minh", "source": {}},
                {"key": "birth_state", "value": "TP.HCM", "source": {}},
                {"key": "father_birth_city", "value": "Hà Nội", "source": {}},
                {"key": "father_birth_state", "value": "Hà Nội", "source": {}},
                {"key": "mother_birth_city", "value": "Đà Nẵng", "source": {}},
                {"key": "mother_birth_state", "value": "Đà Nẵng", "source": {}},
                {"key": "spouse_birth_city", "value": "Cần Thơ", "source": {}},
                {"key": "spouse_birth_state", "value": "Thành phố Cần Thơ", "source": {}},
                {"key": "child_1_birth_city", "value": "Hải Phòng", "source": {}},
                {"key": "child_1_birth_state", "value": "Hải Phòng", "source": {}},
                {"key": "child_2_birth_city", "value": "Thừa Thiên Huế", "source": {}},
                {"key": "child_2_birth_state", "value": "Huế", "source": {}},
            ],
        }
    ]
    normalize_ds260_place_fields(sections)
    by_key = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert by_key["birth_city"] == "Ho Chi Minh"
    assert by_key["birth_state"] == "N/A"
    assert by_key["father_birth_city"] == "Ha Noi"
    assert by_key["father_birth_state"] == "N/A"
    assert by_key["mother_birth_city"] == "Da Nang"
    assert by_key["mother_birth_state"] == "N/A"
    assert by_key["spouse_birth_city"] == "Can Tho"
    assert by_key["spouse_birth_state"] == "N/A"
    assert by_key["child_1_birth_city"] == "Hai Phong"
    assert by_key["child_1_birth_state"] == "N/A"
    assert by_key["child_2_birth_city"] == "Hue"
    assert by_key["child_2_birth_state"] == "N/A"


def test_export_ds260_normalizes_children_and_hcm():
    """Export DS-260 chuẩn hóa Hồ Chí Minh và con cái thành State = N/A."""
    from app.services.export_ds260 import _normalize_birth_city_state

    out = {
        "birth_city": "Thành phố Hồ Chí Minh",
        "birth_state": "Hồ Chí Minh",
        "father_birth_city": "TP. Hồ Chí Minh",
        "father_birth_state": "Việt Nam",
        "child_1_birth_city": "Hồ Chí Minh",
        "child_1_birth_state": "TP.HCM",
        "child_2_birth_city": "Đà Nẵng",
        "child_2_birth_state": "Đà Nẵng",
    }
    _normalize_birth_city_state(out)
    assert out["birth_city"] == "Ho Chi Minh"
    assert out["birth_state"] == "N/A"
    assert out["father_birth_city"] == "Ho Chi Minh"
    assert out["father_birth_state"] == "N/A"
    assert out["child_1_birth_city"] == "Ho Chi Minh"
    assert out["child_1_birth_state"] == "N/A"
    assert out["child_2_birth_city"] == "Da Nang"
    assert out["child_2_birth_state"] == "N/A"

