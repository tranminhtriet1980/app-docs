"""normalize_person_name — tách riêng khỏi normalize_location (dành cho ĐỊA DANH).

Sự cố thực tế 2026-08-04: _names_same_person/_names_match (dùng cho dedupe con, khớp
vợ/chồng, khớp thành viên hồ sơ theo tên OCR, khớp cha/mẹ trên lý lịch tư pháp...) từng dùng
chung normalize_location — hàm đó lọc bỏ từ hành chính (phường/quận/huyện/xã/tỉnh/tp) khỏi
địa danh, và vô tình cắt luôn tên người trùng các từ này (Phương/Phường, Quân/Quan, Xa...).
"""

from app.services.birth_location import format_person_name_ascii, normalize_person_name
from app.services.ds260_mapping import _names_match, _names_same_person


def test_normalize_person_name_keeps_syllables_that_collide_with_admin_words():
    """'Phương' KHÔNG được cắt mất dù trùng 'phường' (đơn vị hành chính)."""
    assert normalize_person_name("Nguyễn Minh Phương") == "nguyen minh phuong"
    assert normalize_person_name("Trần Quân") == "tran quan"
    assert normalize_person_name("Nguyễn Thị Xa") == "nguyen thi xa"


def test_normalize_person_name_diacritics_and_whitespace():
    assert normalize_person_name("  Nguyễn   Minh Phương ") == "nguyen minh phuong"
    assert normalize_person_name("NGUYEN MINH PHUONG") == "nguyen minh phuong"


def test_names_same_person_matches_diacritics_vs_ascii():
    assert _names_same_person("Nguyễn Minh Phương", "NGUYEN MINH PHUONG") is True


def test_names_same_person_distinguishes_names_sharing_a_prefix():
    """Trước fix: normalize_location cắt 'Phương' khỏi 'Nguyễn Minh Phương' → còn 'nguyen
    minh', nên so với một người TÊN KHÁC "Nguyễn Minh Anh" (cũng rút gọn về gần giống) có thể
    khớp nhầm qua đường vòng khác biệt với thử nghiệm trực tiếp ở đây; điều quan trọng là
    chuỗi so khớp giờ giữ đủ âm tiết thay vì bị cắt cụt bởi từ hành chính trùng lặp."""
    assert normalize_person_name("Nguyễn Minh Phương") != normalize_person_name("Nguyễn Minh Anh")
    assert _names_same_person("Nguyễn Minh Phương", "Nguyễn Minh Anh") is False


def test_names_same_person_still_matches_real_different_spellings():
    assert _names_same_person("Nguyễn Văn A", "NGUYEN VAN A") is True
    assert _names_match("Trần Thị B", "TRAN THI B") is True


def test_format_person_name_ascii_unaffected():
    """format_person_name_ascii (hiển thị DS-260) vốn đã đúng — không đổi hành vi."""
    assert format_person_name_ascii("Nguyễn Minh Phương") == "NGUYEN MINH PHUONG"
