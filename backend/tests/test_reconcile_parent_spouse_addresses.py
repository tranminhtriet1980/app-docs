"""reconcile_parent_spouse_addresses: 'bleed' cleanup (địa chỉ cha/mẹ trùng đương đơn → xóa) chỉ
được áp dụng cho dữ liệu OCR từ giấy tờ scan — KHÔNG được áp dụng cho dữ liệu đến từ chính form
DS-260 khách TỰ KHAI TAY (ds260_customer_form). Bug thật (2026-08-05, hồ sơ NGUYEN HOANG YEN):
cha/mẹ sống chung với đương đơn (rất phổ biến ở VN) → địa chỉ trùng chữ → bị coi là lỗi OCR và bị
xóa sạch (kể cả postal code đúng '78607' khách đã khai), dù dữ liệu đến từ form khách tự điền."""

from app.services.ds260_mapping import reconcile_parent_spouse_addresses


def _field(key, value, document_type=None):
    source = {"document_type": document_type} if document_type else {}
    return {"key": key, "value": value, "source": source}


def _sections(applicant_address, father_address, father_document_type):
    return [
        {
            "id": "section_address",
            "fields": [_field("current_address", applicant_address, "ds260_customer_form")],
        },
        {
            "id": "section_father",
            "fields": [
                _field("father_is_living", "Yes"),
                _field("father_address", father_address, father_document_type),
                _field("father_city", "Ho Chi Minh", father_document_type),
                _field("father_state", "Ho Chi Minh", father_document_type),
                _field("father_postal_code", "78607", father_document_type),
                _field("father_country", "Vietnam", father_document_type),
            ],
        },
    ]


def _postal(sections):
    for sec in sections:
        for f in sec["fields"]:
            if f["key"] == "father_postal_code":
                return f["value"]
    return None


def test_same_address_from_customer_form_is_kept_not_treated_as_bleed():
    sections = _sections("Xa Binh Gia", "Xa Binh Gia", "ds260_customer_form")
    reconcile_parent_spouse_addresses(sections)
    assert _postal(sections) == "78607", "Dữ liệu khách tự khai không được xóa dù trùng địa chỉ đương đơn"


def test_same_address_from_ocr_worksheet_is_still_treated_as_bleed():
    """Hành vi cũ vẫn phải giữ nguyên cho nguồn OCR (không phải form khách tự khai) — đây là lỗi
    thật có thể xảy ra khi máy đọc nhầm địa chỉ đương đơn vào ô cha/mẹ."""
    sections = _sections("Xa Binh Gia", "Xa Binh Gia", "birth_certificate")
    reconcile_parent_spouse_addresses(sections)
    assert _postal(sections) == "", "Bleed từ OCR giấy tờ scan vẫn phải bị xóa như trước"


def test_different_address_never_cleared_regardless_of_source():
    sections = _sections("Xa Binh Gia", "Thanh pho Da Nang", "ds260_customer_form")
    reconcile_parent_spouse_addresses(sections)
    assert _postal(sections) == "78607"
