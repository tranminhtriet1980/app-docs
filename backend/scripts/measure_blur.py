"""Đo phương sai Laplacian (độ nét) của một hoặc nhiều ảnh, để hiệu chỉnh
`settings.ocr_blur_variance_threshold` trên ảnh THẬT của dự án thay vì đoán mò.

Cách dùng:
    .venv/Scripts/python.exe scripts/measure_blur.py anh_net.jpg anh_mo.jpg ...
    .venv/Scripts/python.exe scripts/measure_blur.py path/to/folder

Quy trình hiệu chỉnh gợi ý:
1. Gom vài chục ảnh THẬT khách đã upload — cả loại rõ nét lẫn loại bị từ chối/khó đọc
   trong quá khứ (tra `error_message`/phàn nàn của nhân viên).
2. Chạy script này, ghi lại điểm số của từng ảnh.
3. Chọn threshold nằm GIỮA nhóm "nét" (điểm cao) và nhóm "mờ" (điểm thấp) — không đặt
   ngay sát nhóm nét kẻo chặn nhầm ảnh dùng được.
4. Cập nhật ocr_blur_variance_threshold trong .env (backend), KHÔNG sửa default trong
   config.py trừ khi muốn đổi mặc định cho mọi môi trường.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.services.ocr_pipeline import IMAGE_SUFFIXES, _measure_blur_variance  # noqa: E402


def _collect_images(args: list[str]) -> list[Path]:
    paths: list[Path] = []
    for arg in args:
        p = Path(arg)
        if p.is_dir():
            paths.extend(sorted(f for f in p.rglob("*") if f.suffix.lower() in IMAGE_SUFFIXES))
        elif p.is_file():
            paths.append(p)
        else:
            print(f"  (bỏ qua, không tồn tại: {arg})")
    return paths


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return

    images = _collect_images(args)
    if not images:
        print("Không tìm thấy ảnh nào.")
        return

    threshold = settings.ocr_blur_variance_threshold
    print(f"Ngưỡng hiện tại (ocr_blur_variance_threshold) = {threshold:.1f}")
    print("-" * 60)
    rows = []
    for path in images:
        variance = _measure_blur_variance(path)
        rows.append((path, variance))

    rows.sort(key=lambda r: (r[1] is None, r[1]))
    for path, variance in rows:
        if variance is None:
            print(f"  {'LỖI ĐỌC':>10}   {path}")
            continue
        verdict = "SẼ BỊ CHẶN (mờ)" if variance < threshold else "qua"
        print(f"  {variance:10.1f}   {verdict:<16} {path}")


if __name__ == "__main__":
    main()
