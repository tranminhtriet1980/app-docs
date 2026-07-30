"""Cắt trang worksheet viết tay thành lưới cho Vision API.

Vision API nén ảnh về cạnh NGẮN 768px và kẹp cạnh DÀI 2048px, nên gửi nguyên trang A4
thì chữ tay chỉ còn ~0.52 px/px bất kể render DPI bao nhiêu.
"""

from PIL import Image

from app.services.ocr_pipeline import _split_image_into_tiles


def _effective_scale(w: int, h: int) -> float:
    """Độ phân giải hiệu dụng sau khi Vision API (detail=high) nén ảnh."""
    scale = 768 / min(w, h)
    if max(w, h) * scale > 2048:
        scale = 2048 / max(w, h)
    return scale


def _page(tmp_path, size=(1468, 2038)):
    path = tmp_path / "page.jpg"
    Image.new("RGB", size, "white").save(path, "JPEG")
    return path


def test_tiling_disabled_returns_original(tmp_path):
    page = _page(tmp_path)
    assert _split_image_into_tiles(page, 1, 1) == [page]


def test_tile_count_matches_grid(tmp_path):
    page = _page(tmp_path)
    assert len(_split_image_into_tiles(page, 4, 1)) == 4
    assert len(_split_image_into_tiles(page, 2, 2)) == 4


def test_horizontal_tiles_keep_full_width(tmp_path):
    """cols=1 phải giữ nguyên chiều rộng — không được tách nhãn khỏi câu trả lời."""
    page = _page(tmp_path)
    for tile in _split_image_into_tiles(page, 4, 1):
        with Image.open(tile) as im:
            assert im.size[0] == 1468


def test_tiles_overlap_so_boundary_text_is_not_lost(tmp_path):
    page = _page(tmp_path)
    tiles = _split_image_into_tiles(page, 4, 1)
    total_height = 0
    for tile in tiles:
        with Image.open(tile) as im:
            total_height += im.size[1]
    # Chồng lấn → tổng chiều cao các mảnh lớn hơn chiều cao trang gốc.
    assert total_height > 2038


def test_four_rows_beats_whole_page_resolution(tmp_path):
    """Mục đích của việc cắt: chữ tay phải nét hơn thật sự."""
    page = _page(tmp_path)
    whole = _effective_scale(1468, 2038)
    with Image.open(_split_image_into_tiles(page, 4, 1)[0]) as im:
        tiled = _effective_scale(*im.size)
    assert tiled > whole * 2.5


def test_vertical_split_is_not_better_than_horizontal(tmp_path):
    """Lý do mặc định cols=1: cắt dọc vừa kém nét hơn 4x1 vừa tách nhãn khỏi đáp án."""
    page = _page(tmp_path)
    with Image.open(_split_image_into_tiles(page, 1, 2)[0]) as im:
        vertical = _effective_scale(*im.size)
    with Image.open(_split_image_into_tiles(page, 4, 1)[0]) as im:
        horizontal = _effective_scale(*im.size)
    assert horizontal > vertical


def test_unreadable_file_falls_back_to_original(tmp_path):
    bad = tmp_path / "broken.jpg"
    bad.write_bytes(b"not an image")
    assert _split_image_into_tiles(bad, 4, 1) == [bad]
