"""Chuẩn hoá giá trị Yes/No — mọi field câu hỏi Yes/No trong ds260_mapping.json (không chỉ
field kết thúc _used / bắt đầu is_), và mọi biến thể input (YES/NO, Có/Không, Đã/Chưa)."""

from app.services.document_registry import format_field_value, _yes_no_field_keys


def test_yes_no_field_keys_cover_reported_fields():
    """Field Yes/No không theo pattern _used/is_ vẫn phải được nhận diện — báo lỗi thực tế
    2026-08-05: DS-260 C mục Previous U.S Travel, been_in_us/issued_us_visa hiển thị "Chua"
    thay vì "No" vì trước đó không khớp pattern cũ."""
    keys = _yes_no_field_keys()
    for key in (
        "been_in_us",
        "issued_us_visa",
        "refused_us_visa",
        "father_is_living",
        "mother_is_living",
        "military_served",
        "children_used",
        "previous_spouses_used",
        "arrested_convicted",
        "drug_abuser",
        "spouse_immigrating",
    ):
        assert key in keys, f"{key} should be recognized as a yes/no field"


def test_chua_normalizes_to_no():
    """'Chưa' (chưa từng — chưa xảy ra) = No, dù có dấu hay không."""
    assert format_field_value("been_in_us", "Chưa") == "No"
    assert format_field_value("been_in_us", "Chua") == "No"
    assert format_field_value("issued_us_visa", "chưa") == "No"
    assert format_field_value("issued_us_visa", "CHUA") == "No"


def test_da_normalizes_to_yes():
    """'Đã' (đã từng) = Yes, dù có dấu hay không."""
    assert format_field_value("been_in_us", "Đã") == "Yes"
    assert format_field_value("been_in_us", "Da") == "Yes"


def test_co_khong_normalize():
    """Có/Không — dạng phổ biến khác của Yes/No trong worksheet."""
    assert format_field_value("father_is_living", "Có") == "Yes"
    assert format_field_value("father_is_living", "Co") == "Yes"
    assert format_field_value("mother_is_living", "Không") == "No"
    assert format_field_value("mother_is_living", "Khong") == "No"


def test_english_yes_no_passthrough():
    """YES/NO tiếng Anh (mọi kiểu viết hoa/thường) vẫn ra đúng Yes/No chuẩn."""
    assert format_field_value("refused_us_visa", "yes") == "Yes"
    assert format_field_value("refused_us_visa", "YES") == "Yes"
    assert format_field_value("refused_us_visa", "No") == "No"
    assert format_field_value("refused_us_visa", "no") == "No"


def test_non_yes_no_field_untouched():
    """Field không phải Yes/No (vd. tên, địa chỉ) không bị ép qua logic chuẩn hoá này."""
    assert format_field_value("full_name", "Nguyen Van A") == "NGUYEN VAN A"
    assert format_field_value("current_address", "123 Le Loi") == "123 Le Loi"


def test_unrecognized_value_on_yes_no_field_kept_as_is():
    """Giá trị lạ trên field Yes/No (không khớp token nào) giữ nguyên — không đoán bừa."""
    assert format_field_value("been_in_us", "Không rõ") == "Không rõ"
