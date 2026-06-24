"""DS-260 Word export — section context must not fill applicant data into father/mother blocks."""

from pathlib import Path

from app.services.export_ds260 import _match_ds260_key, _smart_fill_ds260_line, fill_ds260_docx_template


def test_generic_dob_in_father_section_maps_to_father_field():
    line = "Date of Birth (dd/mm/yyyy) (Ngày tháng năm sinh):"
    assert _match_ds260_key(line, "father") == "father_date_of_birth"
    assert _match_ds260_key(line, "applicant") == "date_of_birth"


def test_father_section_does_not_use_applicant_values():
    line = "Date of Birth (dd/mm/yyyy) (Ngày tháng năm sinh):"
    values = {"date_of_birth": "05/05/1975", "father_date_of_birth": ""}
    filled = _smart_fill_ds260_line(line, values, "father")
    assert filled == line
    assert "05/05/1975" not in filled


def test_father_surname_fills_na():
    line = "Father’s Surnames (HỌ):"
    values = {"father_surname": "N/A", "date_of_birth": "05/05/1975"}
    filled = _smart_fill_ds260_line(line, values, "father")
    assert "N/A" in filled


def test_export_template_father_block_no_applicant_leak(tmp_path: Path):
    template = Path(__file__).resolve().parents[1] / "templates" / "forms" / "6_eb3_tt_-___n_ds260_-_h_ng_1.docx"
    if not template.exists():
        return
    out = tmp_path / "out.docx"
    fill_ds260_docx_template(
        template,
        out,
        {
            "date_of_birth": "05/05/1975",
            "birth_city": "DA NANG",
            "father_surname": "N/A",
            "father_date_of_birth": "",
            "father_birth_city": "",
        },
    )
    from docx import Document as DocxDocument

    doc = DocxDocument(str(out))
    father_lines: list[str] = []
    in_father = False
    for para in doc.paragraphs:
        t = para.text.strip()
        if "THÔNG TIN CỦA CHA" in t:
            in_father = True
            continue
        if in_father and "THÔNG TIN CỦA MẸ" in t:
            break
        if in_father and t:
            father_lines.append(t)
    blob = "\n".join(father_lines)
    assert "05/05/1975" not in blob
    assert "N/A" in blob
