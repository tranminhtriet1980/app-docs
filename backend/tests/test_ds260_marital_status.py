"""Current marital status in DS-260 personal section."""

import json
from types import SimpleNamespace

from app.services.ds260_mapping import (
    enrich_marital_status_from_documents,
    reconcile_previous_spouse_with_marital_status,
)


def _rec(
    raw: dict,
    doc_type: str = "divorce",
    *,
    variant: str = "standard",
) -> SimpleNamespace:
    return SimpleNamespace(
        doc_type=doc_type,
        variant=variant,
        form_data=json.dumps(raw),
        raw_data=json.dumps(raw),
    )


def test_marital_status_not_guessed_without_documents():
    """Không có giấy kết hôn / ly hôn → không ép Married (CHIEM ANH HANG pattern)."""
    fields = [{"key": "current_marital_status", "value": "", "source": {}}]
    enrich_marital_status_from_documents(fields, None)
    assert fields[0]["value"] == ""


def test_marital_status_cleared_when_no_documents_even_from_worksheet():
    """Không có giấy → xóa cả giá trị worksheet (Single, v.v.)."""
    fields = [{"key": "current_marital_status", "value": "Single", "source": {}}]
    enrich_marital_status_from_documents(fields, None)
    assert fields[0]["value"] == ""


def test_marital_status_married_when_marriage_cert_applicable():
    passport = _rec({"full_name": "TRAN VAN A"}, doc_type="passport")
    marriage = _rec(
        {
            "husband_full_name": "TRAN VAN A",
            "wife_full_name": "NGUYEN THI B",
            "marriage_date": "2010-05-01",
        },
        doc_type="marriage_certificate",
    )
    fields = [{"key": "current_marital_status", "value": "", "source": {}}]
    enrich_marital_status_from_documents(
        fields, None, marriage_rec=marriage, passport_rec=passport
    )
    assert fields[0]["value"] == "Married"
    assert fields[0]["source"]["derived"] == "marital_status_from_marriage"


def test_marital_status_single_when_divorce_present_without_marriage_date():
    """Giấy ly hôn không ghi ngày kết hôn (chưa từng đăng ký hợp pháp) → Single."""
    fields = [{"key": "current_marital_status", "value": "", "source": {}}]
    divorce = _rec({"divorce_date": "2025-07-30"})
    enrich_marital_status_from_documents(fields, divorce)
    assert fields[0]["value"] == "Single"
    assert fields[0]["source"]["derived"] == "marital_status_single_unregistered_from_divorce"


def test_marital_status_single_when_divorce_says_unregistered_cohabitation():
    """Giấy ly hôn ghi rõ 'tự nguyện chung sống' / không đăng ký kết hôn → Single dù có marriage_date."""
    fields = [{"key": "current_marital_status", "value": "", "source": {}}]
    divorce = _rec(
        {
            "divorce_date": "2025-07-30",
            "marriage_date": "2015-01-01",
            "document_type": "V/v Không công nhận quan hệ vợ chồng - tự nguyện chung sống",
        }
    )
    enrich_marital_status_from_documents(fields, divorce)
    assert fields[0]["value"] == "Single"
    assert fields[0]["source"]["derived"] == "marital_status_single_unregistered_from_divorce"


def test_marital_status_divorced_when_marriage_was_registered():
    """Giấy ly hôn ghi rõ ngày đăng ký kết hôn → Divorced."""
    fields = [{"key": "current_marital_status", "value": "", "source": {}}]
    divorce = _rec({"divorce_date": "2025-07-30", "marriage_date": "2015-01-01"})
    enrich_marital_status_from_documents(fields, divorce)
    assert fields[0]["value"] == "Divorced"
    assert fields[0]["source"]["derived"] == "marital_status_divorced_from_divorce"


def test_marital_status_divorced_when_divorce_missing_date_but_has_marriage_cert():
    """Giấy ly hôn KHÔNG ghi ngày đăng ký kết hôn, nhưng hồ sơ CÓ giấy đăng ký kết hôn cho đúng
    cuộc hôn nhân đó → vẫn tính là đã đăng ký (Divorced), không mặc định Single."""
    passport = _rec({"full_name": "TRAN VAN A"}, doc_type="passport")
    divorce = _rec(
        {
            "husband_full_name": "TRAN VAN A",
            "wife_full_name": "NGUYEN THI B",
            "divorce_date": "2025-07-30",
        }
    )
    marriage = _rec(
        {
            "husband_full_name": "TRAN VAN A",
            "wife_full_name": "NGUYEN THI B",
            "marriage_date": "2010-05-01",
        },
        doc_type="marriage_certificate",
    )
    fields = [{"key": "current_marital_status", "value": "", "source": {}}]
    enrich_marital_status_from_documents(
        fields, divorce, marriage_rec=marriage, passport_rec=passport
    )
    assert fields[0]["value"] == "Divorced"
    assert fields[0]["source"]["derived"] == "marital_status_divorced_from_divorce"


def test_marital_status_single_when_divorce_missing_date_and_no_marriage_cert():
    """Giấy ly hôn không ghi ngày đăng ký kết hôn VÀ hồ sơ không có giấy đăng ký kết hôn nào
    → Single (giữ hành vi cũ khi không có bằng chứng đã đăng ký)."""
    passport = _rec({"full_name": "TRAN VAN A"}, doc_type="passport")
    divorce = _rec(
        {
            "husband_full_name": "TRAN VAN A",
            "wife_full_name": "NGUYEN THI B",
            "divorce_date": "2025-07-30",
        }
    )
    fields = [{"key": "current_marital_status", "value": "", "source": {}}]
    enrich_marital_status_from_documents(fields, divorce, passport_rec=passport)
    assert fields[0]["value"] == "Single"
    assert fields[0]["source"]["derived"] == "marital_status_single_unregistered_from_divorce"


def _previous_spouse_section_filled_from_divorce() -> list[dict]:
    """Mô phỏng section_previous_spouse SAU KHI enrich_previous_spouse_from_divorce đã điền —
    hàm đó chạy sớm trong pipeline, trước khi current_marital_status có giá trị CUỐI CÙNG."""
    return [
        {"key": "previous_spouses_used", "value": "Yes", "source": {"document_type": "divorce"}},
        {
            "key": "previous_spouse_full_name",
            "value": "NGUYEN THI B",
            "source": {"document_type": "divorce"},
        },
        {
            "key": "previous_spouse_date_of_birth",
            "value": "1985-03-01",
            "source": {"document_type": "divorce"},
        },
    ]


def test_reconcile_clears_previous_spouse_when_final_status_is_single():
    """cohabitation-Single: giấy ly hôn ghi 'tự nguyện chung sống' (chưa từng đăng ký hợp pháp)
    → current_marital_status cuối cùng = Single, nhưng enrich_previous_spouse_from_divorce đã
    lỡ điền "Yes" + tên/ngày sinh vợ cũ trước đó — reconcile phải xoá sạch, không được giữ lại
    Previous Spouse cho người chưa từng kết hôn hợp pháp."""
    sections = [
        {
            "id": "section_a_personal",
            "fields": [{"key": "current_marital_status", "value": "Single", "source": {}}],
        },
        {"id": "section_previous_spouse", "fields": _previous_spouse_section_filled_from_divorce()},
    ]
    reconcile_previous_spouse_with_marital_status(sections)
    prev = {f["key"]: f["value"] for f in sections[1]["fields"]}
    assert prev["previous_spouses_used"] == "No"
    assert prev["previous_spouse_full_name"] == ""
    assert prev["previous_spouse_date_of_birth"] == ""


def test_reconcile_keeps_previous_spouse_when_final_status_is_divorced():
    """Divorced hợp pháp — Previous Spouse phải giữ nguyên, không bị xoá nhầm (tương tác với
    test_ds260_widow_death.py: Widowed cũng phải giữ nguyên theo cùng logic)."""
    sections = [
        {
            "id": "section_a_personal",
            "fields": [{"key": "current_marital_status", "value": "Divorced", "source": {}}],
        },
        {"id": "section_previous_spouse", "fields": _previous_spouse_section_filled_from_divorce()},
    ]
    reconcile_previous_spouse_with_marital_status(sections)
    prev = {f["key"]: f["value"] for f in sections[1]["fields"]}
    assert prev["previous_spouses_used"] == "Yes"
    assert prev["previous_spouse_full_name"] == "NGUYEN THI B"


def test_reconcile_keeps_previous_spouse_when_final_status_is_widowed():
    sections = [
        {
            "id": "section_a_personal",
            "fields": [{"key": "current_marital_status", "value": "Widowed", "source": {}}],
        },
        {"id": "section_previous_spouse", "fields": _previous_spouse_section_filled_from_divorce()},
    ]
    reconcile_previous_spouse_with_marital_status(sections)
    prev = {f["key"]: f["value"] for f in sections[1]["fields"]}
    assert prev["previous_spouses_used"] == "Yes"
    assert prev["previous_spouse_full_name"] == "NGUYEN THI B"
