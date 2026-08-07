"""Chặn ảnh mờ/out nét trước khi gọi Vision API, và gộp cờ image_quality khi
tài liệu bị chia nhiều batch (mỗi batch chỉ thấy một phần trang).

Bối cảnh: pipeline OCR trước đây xử lý ảnh mờ như ảnh nét bình thường — model đoán
mò chữ không đọc được thay vì báo lỗi, dữ liệu sai âm thầm lọt vào hồ sơ.
"""

from PIL import Image

from app.services.ocr_pipeline import (
    _image_quality_warning,
    _measure_blur_variance,
    _merge_batch_results,
)


def _checkerboard(tmp_path, name="sharp.jpg", size=(400, 400), cell=8):
    img = Image.new("L", size)
    px = img.load()
    for y in range(size[1]):
        for x in range(size[0]):
            px[x, y] = 255 if ((x // cell) + (y // cell)) % 2 == 0 else 0
    path = tmp_path / name
    img.convert("RGB").save(path, "JPEG", quality=95)
    return path


def _flat(tmp_path, name="blurry.jpg", size=(400, 400)):
    path = tmp_path / name
    Image.new("RGB", size, (200, 200, 200)).save(path, "JPEG", quality=95)
    return path


def test_sharp_image_scores_higher_than_flat_image(tmp_path):
    sharp = _checkerboard(tmp_path)
    flat = _flat(tmp_path)
    assert _measure_blur_variance(sharp) > _measure_blur_variance(flat) * 10


def test_gaussian_blur_lowers_the_score(tmp_path):
    from PIL import ImageFilter

    sharp_path = _checkerboard(tmp_path)
    with Image.open(sharp_path) as im:
        blurred = im.filter(ImageFilter.GaussianBlur(radius=6))
        blurred_path = tmp_path / "softened.jpg"
        blurred.convert("RGB").save(blurred_path, "JPEG", quality=95)

    assert _measure_blur_variance(blurred_path) < _measure_blur_variance(sharp_path)


def test_unreadable_file_returns_none(tmp_path):
    bad = tmp_path / "broken.jpg"
    bad.write_bytes(b"not an image")
    assert _measure_blur_variance(bad) is None


def test_quality_warning_none_when_readable_or_absent():
    assert _image_quality_warning({}) is None
    assert _image_quality_warning({"image_quality": {"readable": True}}) is None


def test_quality_warning_maps_known_issue_to_vietnamese():
    warning = _image_quality_warning({"image_quality": {"readable": False, "issue": "blurry"}})
    assert warning is not None
    assert "mờ" in warning


def test_quality_warning_falls_back_to_raw_issue_text():
    warning = _image_quality_warning(
        {"image_quality": {"readable": False, "issue": "torn_page"}}
    )
    assert warning is not None
    assert "torn_page" in warning


def test_merge_batches_flags_unreadable_if_any_batch_reports_it():
    results = [
        {"fields": {"a": {"value": "1"}}, "image_quality": {"readable": True, "issue": ""}},
        {"fields": {"b": {"value": "2"}}, "image_quality": {"readable": False, "issue": "blurry"}},
    ]
    merged = _merge_batch_results(results)
    assert merged["image_quality"]["readable"] is False
    assert "blurry" in merged["image_quality"]["issue"]
    # "fields" vẫn theo luật gộp nông sẵn có (khác rỗng đầu tiên thắng) — không bị
    # thay đổi bởi cờ image_quality được gộp riêng.
    assert merged["fields"]["a"]["value"] == "1"


def test_merge_batches_stays_readable_when_all_batches_agree():
    results = [
        {"fields": {"a": {"value": "1"}}, "image_quality": {"readable": True, "issue": ""}},
        {"fields": {"b": {"value": "2"}}, "image_quality": {"readable": True, "issue": ""}},
    ]
    merged = _merge_batch_results(results)
    assert "image_quality" not in merged
