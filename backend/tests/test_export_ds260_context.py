"""DS-260 Word export — section context must not fill applicant data into father/mother blocks."""

from pathlib import Path

from app.services.export_ds260 import (
    _match_ds260_key,
    _smart_fill_ds260_line,
    _update_section_context,
    fill_ds260_docx_template,
)


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


def test_social_media_identifier_fills_without_colon():
    """Nhãn Social Media Identifier kết thúc bằng '))' (không có ':') — giá trị vẫn phải được điền."""
    line = "Social Media Identifier (cung cấp TÊN MẠNG XÃ HỘI CỦA BẠN & LINK TRANG MẠNG XÃ HỘI (LINK NGẮN))"
    assert _match_ds260_key(line, "social") == "social_media_identifier"
    filled = _smart_fill_ds260_line(line, {"social_media_identifier": "facebook.com/user"}, "social")
    assert filled.endswith("facebook.com/user")
    # Idempotent — chạy lại không nhân đôi giá trị.
    assert _smart_fill_ds260_line(filled, {"social_media_identifier": "facebook.com/user"}, "social") == filled


def test_social_media_platform_fills_with_colon():
    line = "Social Media Provider/Platform (sử dụng MẠNG XÃ HỘI nào):"
    filled = _smart_fill_ds260_line(line, {"social_media_platform": "Facebook"}, "social")
    assert filled.rstrip().endswith("Facebook")


def test_other_used_questions_yes_with_detail_else_no():
    """Other ... used last 5 years?: có history → 'Yes - <chi tiết>'; không → 'No'."""
    soc = "Other Social Media used last Five years? (cung cấp TÊN MẠNG XÃ HỘI KHÁC CỦA BẠN đã sử dụng trong 5 NĂM QUA)"
    assert _match_ds260_key(soc, "social") == "other_social_media_used"
    assert _smart_fill_ds260_line(soc, {"other_social_history": "Zalo - Vy"}, "social").endswith("Yes - Zalo - Vy")
    assert _smart_fill_ds260_line(soc, {}, "social").endswith("No")

    em = "Other Email used last Five years? (địa chỉ EMAIL KHÁC đã sử dụng trong 5 NĂM QUA)"
    assert _match_ds260_key(em, "contact") == "other_emails_used"
    assert _smart_fill_ds260_line(em, {"other_emails_used": "Yes", "other_emails_history": "old@x.com"}, "contact").endswith("Yes - old@x.com")

    ph = "Other Telephone Number used last Five years? (số ĐIỆN THOẠI KHÁC đã sử dụng trong 5 NĂM QUA)"
    assert _match_ds260_key(ph, "contact") == "other_phones_used"
    assert _smart_fill_ds260_line(ph, {}, "contact").endswith("No")


def test_work_yes_no_questions_render_detail():
    """Section D: nghề khác + lịch sử việc làm 10 năm → 'Yes - <chi tiết>' / 'No' (narrative phải hiện)."""
    oc = "Do you have other occupation (Hiện tại bạn có làm đang CÔNG VIỆC nào khác?)"
    assert _smart_fill_ds260_line(oc, {"work_other_occupation_detail": "Phụ bán hàng"}, "work").endswith("Yes - Phụ bán hàng")
    assert _smart_fill_ds260_line(oc, {}, "work").endswith("No")

    pj = "Were you previously employed in any other company in the last 10 years? (...):"
    hist = "From 01/2009 to 12/2023\nManager - ABC Co"
    filled = _smart_fill_ds260_line(pj, {"work_prior_jobs_history": hist}, "work")
    assert "From 01/2009 to 12/2023; Manager - ABC Co" in filled
    assert _smart_fill_ds260_line(pj, {}, "work").endswith("No")


def test_military_section_maps_bilingual_labels():
    """Mục NVQS: nhãn tiếng Việt → đúng field; Country/Region KHÔNG rơi vào current_country."""
    cases = {
        "Name of Country/Region (Phục vụ quân đội ở Nước/Lãnh Thổ nào):": "military_country",
        "Branch of Serive (Phục vụ quân đội ở Khu/Chiến Khu nào):": "military_branch",
        "Rank/Positon (làm công việc gì khi phục vụ quân đội):": "military_rank",
        "Military Specialty (Phục vụ quân đội chuyên ngành gì):": "military_specialty",
        "Date of Service From (Phục vụ quân đội Từ tháng/ngày/năm nào):": "military_service_start",
        "Date of Service To (Phục vụ quân đội Đến tháng/ngày/năm nào):": "military_service_end",
    }
    for line, key in cases.items():
        assert _match_ds260_key(line, "military") == key, line
    country = "Name of Country/Region (Phục vụ quân đội ở Nước/Lãnh Thổ nào):"
    filled = _smart_fill_ds260_line(country, {"military_country": "Vietnam", "current_country": "HCM"}, "military")
    assert filled.rstrip().endswith("Vietnam")
    assert "HCM" not in filled
    served = "Have you ever served in the military? (Bạn đã từng phục vụ trong quân đội?)"
    assert _match_ds260_key(served, "military") == "military_served"
    assert _smart_fill_ds260_line(served, {"military_served": "Yes"}, "military").rstrip().endswith("Yes")


def test_military_context_switches_to_applicant_at_e2():
    """Header chuyển context: MILITARY → military; THÔNG TIN KHÁC → applicant."""
    assert _update_section_context("MILITARY SERVICE – NGHĨA VỤ QUÂN SỰ", "work") == "military"
    assert _update_section_context("THÔNG TIN KHÁC", "military") == "applicant"


def test_other_addresses_question_fills_once_across_two_lines():
    """A.3 'lived anywhere since 16?' trải 2 dòng (Anh+Việt) → chỉ điền đáp án 1 lần."""
    en = "Have you lived anywhere other than this address since the age of sixteen?"
    vi = "(Bạn có từng ở những chổ khác kể từ năm 16 tuổi đến nay hay không?)"
    assert _match_ds260_key(en, "address") == "other_addresses_used"
    assert _match_ds260_key(vi, "address") == "other_addresses_used"
    vals = {"other_addresses_used": "Yes", "other_addresses_history": "1989-2008: Tien Giang"}
    filled: set[str] = set()
    out_en = _smart_fill_ds260_line(en, vals, "address", filled)
    out_vi = _smart_fill_ds260_line(vi, vals, "address", filled)
    assert out_en.endswith("Yes - 1989-2008: Tien Giang")
    assert out_vi == vi  # dòng thứ 2 không điền lại
    # Không có lịch sử → No.
    assert _smart_fill_ds260_line(en, {}, "address", set()).endswith("No")


def test_e2_languages_and_travel_render_detail():
    """E.2: ngôn ngữ khác + du lịch 5 năm → 'Yes - <chi tiết>' / 'No'."""
    lang = (
        "Do you use any other languages beside your native language? "
        "(Có sử dụng ngôn ngữ nào khác ngoài tiếng Việt hay không?) ... của ngôn ngữ đó."
    )
    trav = (
        "Have you traveled to any countries/regions within the last five years? "
        "(Bạn đã từng DU LỊCH đến các NƯỚC NÀO trong 5 NĂM QUA):"
    )
    instr = "(Yes or No, if 'Yes' write details below) ... thông tin đã đi du lịch."
    assert _match_ds260_key(lang, "applicant") == "other_languages_used"
    assert _match_ds260_key(trav, "applicant") == "traveled_countries_5yr_used"
    # Dòng hướng dẫn phụ KHÔNG được nhận nhầm là ô du lịch.
    assert _match_ds260_key(instr, "applicant") == ""
    assert _smart_fill_ds260_line(lang, {"other_languages": "English, French"}, "applicant").endswith("Yes - English, French")
    assert _smart_fill_ds260_line(lang, {}, "applicant").endswith("No")
    assert _smart_fill_ds260_line(trav, {"traveled_countries_history": "Thailand 2023; Japan 2024"}, "applicant").endswith("Yes - Thailand 2023; Japan 2024")
    assert _smart_fill_ds260_line(trav, {}, "applicant").endswith("No")


def test_year_of_death_maps_per_section():
    """'Year of death (Năm mất):' → father/mother_death_year trong section cha/mẹ; death_date ở section báo tử."""
    line = "Year of death (Năm mất):"
    assert _match_ds260_key(line, "father") == "father_death_year"
    assert _match_ds260_key(line, "mother") == "mother_death_year"
    assert _match_ds260_key(line, "applicant") == "death_date"
    assert _smart_fill_ds260_line(line, {"father_death_year": "2009"}, "father").rstrip().endswith("2009")
    assert _smart_fill_ds260_line(line, {"mother_death_year": "1998"}, "mother").rstrip().endswith("1998")


def test_plain_email_and_identifier_not_shadowed_by_other_used():
    """Nhãn email/identifier thường KHÔNG được nhận nhầm thành cờ other_*_used."""
    assert _match_ds260_key("Email Address (địa chỉ EMAIL):", "contact") == "email"
    assert _match_ds260_key(
        "Social Media Identifier (cung cấp TÊN MẠNG XÃ HỘI CỦA BẠN & LINK TRANG MẠNG XÃ HỘI (LINK NGẮN))",
        "social",
    ) == "social_media_identifier"


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
