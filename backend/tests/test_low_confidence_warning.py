"""Ảnh SẮC NÉT tổng thể nhưng chữ mực nhạt/thiếu sáng cục bộ — _measure_blur_variance
(đo trên toàn ảnh) không bắt được ca này vì viền/con dấu/ảnh thẻ vẫn kéo điểm nét lên cao.
Tín hiệu đúng là confidence THẤP trên field CÓ giá trị (model đọc được nhưng không chắc),
khác với field null (model trung thực báo trống).
"""

from app.services.ocr_pipeline import _combine_warnings, _low_confidence_field_warning


def _extraction(fields: dict) -> dict:
    return {"fields": fields}


def test_no_warning_when_all_fields_confident():
    extraction = _extraction(
        {
            "full_name": {"value": "NGUYEN VAN A", "confidence": 0.95},
            "date_of_birth": {"value": "1990-01-01", "confidence": 0.9},
        }
    )
    assert _low_confidence_field_warning(extraction) is None


def test_no_warning_for_null_fields_regardless_of_confidence():
    """Field null = model trung thực báo trống, không phải đoán mò — không tính vào tỉ lệ."""
    extraction = _extraction(
        {
            "full_name": {"value": "NGUYEN VAN A", "confidence": 0.95},
            "middle_name": {"value": None, "confidence": 0.0},
            "notes": {"value": "", "confidence": 0.1},
        }
    )
    assert _low_confidence_field_warning(extraction) is None


def test_warning_when_low_confidence_ratio_exceeds_threshold():
    extraction = _extraction(
        {
            "full_name": {"value": "NGUYEN VAN A", "confidence": 0.3},
            "date_of_birth": {"value": "1990-01-01", "confidence": 0.35},
            "gender": {"value": "MALE", "confidence": 0.9},
        }
    )
    warning = _low_confidence_field_warning(extraction)
    assert warning is not None
    assert "full_name" in warning
    assert "date_of_birth" in warning
    assert "2/3" in warning


def test_no_warning_when_only_one_field_out_of_many_is_low():
    """1 field không chắc trong nhiều field là bình thường — không đáng làm phiền người dùng."""
    fields = {f"field_{i}": {"value": f"v{i}", "confidence": 0.9} for i in range(10)}
    fields["field_0"]["confidence"] = 0.2
    extraction = _extraction(fields)
    assert _low_confidence_field_warning(extraction) is None


def test_combine_warnings_joins_non_empty_parts():
    assert _combine_warnings("a", None, "b") == "a | b"
    assert _combine_warnings(None, None) is None
    assert _combine_warnings("only") == "only"
