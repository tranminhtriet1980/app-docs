"""Prompt trích xuất worksheet: nhóm theo mục, bỏ key của loại giấy khác.

Danh sách phẳng ~500 key (gồm alias và tên field của giấy tờ KHÁC) làm prompt loãng và mời
model điền chéo — lỗi thật: chồng ĐÃ MẤT bị xếp vào ô "ĐÃ LY HÔN" (Case D); mục F/E.2/G
không hề được hỏi nên luôn rơi về giá trị mặc định (Vaccination luôn "Yes", ngôn ngữ "No").
"""

from app.services.ds260_customer_keys import (
    build_ds260_customer_extract_keys,
    build_ds260_customer_prompt_sections,
    render_ds260_customer_prompt_keys,
)

# Tên chung chung / thuộc giấy tờ khác — không được xuất hiện trong prompt worksheet.
_BLEED_KEYS = {
    "full_name",
    "date_of_death",
    "deceased_full_name",
    "husband_full_name",
    "wife_full_name",
    "plaintiff_name",
    "defendant_name",
    "judicial_full_name",
    "birth_cert_full_name",
}


def _prompt_keys() -> set[str]:
    return {k for _, keys in build_ds260_customer_prompt_sections() for k in keys}


def test_no_foreign_document_keys_in_prompt():
    assert _prompt_keys() & _BLEED_KEYS == set()


def test_previously_missing_sections_are_now_asked_for():
    """F (an ninh), E.2 (ngôn ngữ), G (SSN), C (lịch sử đến Mỹ) trước đây không hề có."""
    keys = _prompt_keys()
    for key in (
        "has_vaccination_docs",
        "other_languages_used",
        "been_in_us",
        "applied_ssn_before",
    ):
        assert key in keys, key


def test_prompt_is_grouped_by_section():
    labels = [label for label, _ in build_ds260_customer_prompt_sections()]
    assert any("AN NINH" in x for x in labels)
    assert any("SỐ AN SINH" in x for x in labels)
    rendered = render_ds260_customer_prompt_keys()
    assert rendered.startswith("[")
    assert "\n" in rendered


def test_prompt_list_is_smaller_than_output_filter():
    """Siết cái ta HỎI, không siết cái ta CHẤP NHẬN — bộ lọc đầu ra phải rộng hơn."""
    assert len(_prompt_keys()) < len(build_ds260_customer_extract_keys())


def test_output_filter_still_accepts_every_prompted_key():
    """Không được hỏi một key rồi lại lọc bỏ chính nó khỏi kết quả."""
    assert _prompt_keys() <= set(build_ds260_customer_extract_keys())


def test_core_worksheet_keys_still_present():
    keys = _prompt_keys()
    for key in (
        "applicant_name",
        "passport_number",
        "current_address",
        "primary_phone",
        "father_surname",
        "mother_surname",
        "spouse_full_name",
        "children_count",
        "work_primary_occupation",
        "military_served",
    ):
        assert key in keys, key
