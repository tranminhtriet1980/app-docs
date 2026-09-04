import unicodedata
from app.services.document_registry import parse_document_filename
from app.services.ocr_pipeline import _resolve_document_type


def test_parse_document_checklist_filename():
    decomposed_name = unicodedata.normalize("NFD", "PHIẾU MÔ TẢ & DANH SÁCH HỒ SƠ.xlsx")
    cases = [
        ("PHIEU MO TA & DANH SACH HO SO.pdf", "document_checklist", False),
        ("PHIẾU MÔ TẢ & DANH SÁCH HỒ SƠ.pdf", "document_checklist", False),
        ("PHIẾU MÔ TẢ & DANH SÁCH HỒ SƠ.xlsx", "document_checklist", False),
        (decomposed_name, "document_checklist", False),
        ("Phieu mo ta ho so.pdf", "document_checklist", False),
        ("danh sach ho so.pdf", "document_checklist", False),
        ("Checklist ho so.pdf", "document_checklist", False),
        ("bang ke giay to.pdf", "document_checklist", False),
        ("PHIEU MO TA_new.pdf", "document_checklist", True),
    ]
    for filename, expected_type, expected_exc in cases:
        doc_type, is_exc = parse_document_filename(filename)
        assert doc_type == expected_type, f"Failed for {filename}: got {doc_type}"
        assert is_exc == expected_exc, f"Failed exception flag for {filename}: got {is_exc}"

    # Also test _resolve_document_type when AI returns other
    resolved_type, _ = _resolve_document_type("other", "PHIẾU MÔ TẢ & DANH SÁCH HỒ SƠ.xlsx")
    assert resolved_type == "document_checklist"

