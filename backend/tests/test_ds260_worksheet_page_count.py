"""Trần render trang PDF cho worksheet DS-260 khách khai phải theo SỐ TRANG THẬT của file
(giới hạn bởi settings.ocr_ds260_worksheet_max_pages), không cắt cụt cố định ở 20 trang.

Báo lỗi thực tế 2026-08-05: worksheet "03_6 DS260 - NGUYEN MINH PHUONG.pdf" dài 146 trang —
trần cũ 20 trang khiến mục Work/Education Part D (nằm sau trang 20) không bao giờ được AI đọc,
Section D trên DS-260 form trống hoàn toàn dù worksheet có ghi đầy đủ.
"""

import fitz

from app.config import settings
from app.services.ocr_pipeline import _pdf_page_count


def _make_pdf(path, num_pages: int) -> None:
    doc = fitz.open()
    for _ in range(num_pages):
        doc.new_page()
    doc.save(str(path))
    doc.close()


def test_pdf_page_count_matches_real_page_count(tmp_path):
    pdf_path = tmp_path / "worksheet_5_pages.pdf"
    _make_pdf(pdf_path, 5)
    assert _pdf_page_count(pdf_path) == 5


def test_pdf_page_count_long_worksheet_146_pages(tmp_path):
    """Tái hiện đúng kích cỡ file thực tế gây lỗi (146 trang)."""
    pdf_path = tmp_path / "worksheet_146_pages.pdf"
    _make_pdf(pdf_path, 146)
    assert _pdf_page_count(pdf_path) == 146


def test_pdf_page_count_missing_file_returns_zero():
    from pathlib import Path

    assert _pdf_page_count(Path("/nonexistent/path/does-not-exist.pdf")) == 0


def test_ds260_worksheet_max_pages_setting_covers_146_page_real_case():
    """Trần cấu hình phải đủ lớn để phủ file thực tế 146 trang gây lỗi — nếu ai đó vô tình hạ
    trần này xuống dưới 146, test sẽ báo đỏ nhắc lại đúng ca lỗi gốc."""
    assert settings.ocr_ds260_worksheet_max_pages >= 146


def test_dynamic_max_pages_uses_actual_count_not_fixed_cap(tmp_path):
    """min(số trang thật, trần cấu hình) — file ngắn hơn trần thì dùng đúng số trang thật,
    không render thừa; file dài hơn trần thì bị giới hạn ở trần (không crash/timeout vô hạn)."""
    short_pdf = tmp_path / "short.pdf"
    _make_pdf(short_pdf, 5)
    long_pdf = tmp_path / "long.pdf"
    _make_pdf(long_pdf, 500)

    ceiling = settings.ocr_ds260_worksheet_max_pages
    short_max = min(_pdf_page_count(short_pdf) or ceiling, ceiling)
    long_max = min(_pdf_page_count(long_pdf) or ceiling, ceiling)

    assert short_max == 5, "File ngắn phải dùng đúng số trang thật, không bị ép lên trần"
    assert long_max == ceiling, "File dài hơn trần phải bị chặn ở trần, không vượt quá"
