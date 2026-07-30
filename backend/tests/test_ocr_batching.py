"""Chia tài liệu nhiều ảnh thành nhiều request Vision API rồi gộp kết quả.

Bối cảnh: OpenAI áp trần tokens-per-minute cho TỪNG request. Worksheet 20 trang cắt
lưới 4x1 thành 80 ảnh ≈ 116k token, đập vào trần 30k của tier 1 → 429 vĩnh viễn, retry
vô ích (sự cố prod 30/07/2026). Chia nhỏ là cách duy nhất gửi được.
"""

from pathlib import Path

from app.services.ocr_pipeline import (
    _build_llm_user_content,
    _merge_batch_results,
    _split_images_into_batches,
)


def _paths(n: int) -> list[Path]:
    return [Path(f"page{i}.jpg") for i in range(1, n + 1)]


def test_no_split_when_under_limit():
    paths = _paths(20)
    labels = [f"Page {i}" for i in range(1, 21)]

    batches = _split_images_into_batches(paths, labels, 20)

    assert len(batches) == 1
    assert batches[0] == (paths, labels)


def test_zero_disables_splitting():
    """0 = giữ hành vi cũ, gửi tất cả trong một request."""
    paths = _paths(80)

    batches = _split_images_into_batches(paths, None, 0)

    assert len(batches) == 1
    assert batches[0][0] == paths


def test_splits_and_keeps_labels_aligned():
    """80 ảnh (worksheet 20 trang cắt 4x1) → 4 lô, nhãn phải đi đúng ảnh của nó."""
    paths = _paths(80)
    labels = [f"Page {i // 4 + 1} tile {i % 4 + 1}" for i in range(80)]

    batches = _split_images_into_batches(paths, labels, 20)

    assert len(batches) == 4
    assert [len(p) for p, _ in batches] == [20, 20, 20, 20]
    # Nối lại phải ra đúng danh sách gốc, không sót không lặp.
    assert [p for batch, _ in batches for p in batch] == paths
    assert [lb for _, batch_labels in batches for lb in batch_labels] == labels
    # Nhãn thứ i trong lô phải khớp ảnh thứ i của lô đó.
    assert batches[1][1][0] == labels[20]


def test_split_handles_uneven_last_batch():
    batches = _split_images_into_batches(_paths(50), None, 20)

    assert [len(p) for p, _ in batches] == [20, 20, 10]


def test_merge_first_non_empty_wins():
    """Lô đọc được giá trị thật thắng; lô sau không đè lên."""
    merged = _merge_batch_results(
        [
            {"full_name": "CHIEM ANH HANG", "passport_no": ""},
            {"full_name": "SAI BET", "passport_no": "C1234567"},
        ]
    )

    assert merged["full_name"] == "CHIEM ANH HANG"
    assert merged["passport_no"] == "C1234567"


def test_merge_treats_blank_forms_as_empty():
    """None, chuỗi trắng, list/dict rỗng đều là 'chưa đọc được' → cho lô sau điền."""
    merged = _merge_batch_results(
        [
            {"a": None, "b": "   ", "c": [], "d": {}, "e": 0, "f": False},
            {"a": "A", "b": "B", "c": ["C"], "d": {"k": "v"}, "e": 9, "f": True},
        ]
    )

    assert merged["a"] == "A"
    assert merged["b"] == "B"
    assert merged["c"] == ["C"]
    assert merged["d"] == {"k": "v"}
    # 0 và False là giá trị hợp lệ, không phải "rỗng" → giữ nguyên lô đầu.
    assert merged["e"] == 0
    assert merged["f"] is False


def test_merge_edge_cases():
    assert _merge_batch_results([]) == {}
    single = {"x": "y"}
    assert _merge_batch_results([single]) is single


def test_batch_prompt_tells_model_not_to_guess(tmp_path):
    """Mỗi lô chỉ thấy một phần tài liệu — phải cấm model đoán phần nó không thấy.

    Không có câu này thì lô 1 bịa ra giá trị, và luật gộp 'khác rỗng đầu tiên thắng'
    sẽ khoá luôn giá trị đọc thật ở lô sau.
    """
    img = tmp_path / "page1.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")

    parts = _build_llm_user_content(
        filename="worksheet.pdf",
        image_paths=[img],
        hint="pdf_pages",
        file_path=tmp_path / "worksheet.pdf",
        task="Extract all fields from this document.",
        image_labels=["Page 1"],
        batch_position=(2, 4),
    )

    intro = parts[0]["text"]
    assert "PART 2 of 4" in intro
    assert "do NOT guess" in intro


def test_single_batch_has_no_part_wording(tmp_path):
    """Tài liệu không bị chia thì không được nhắc tới 'PART' — tránh làm model dè dặt thừa."""
    img = tmp_path / "page1.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")

    parts = _build_llm_user_content(
        filename="worksheet.pdf",
        image_paths=[img],
        hint="pdf_pages",
        file_path=tmp_path / "worksheet.pdf",
        task="Extract all fields from this document.",
        image_labels=["Page 1"],
    )

    assert "PART" not in parts[0]["text"]
