"""Test OCR chữ viết tay (GPT Vision) trên 1 hoặc nhiều ảnh, log kết quả ra file để theo dõi.

Dùng để thử prompt cho các form khai địa chỉ viết tay khó đọc (chữ nghiêng, gạch xoá,
chèn chữ giữa dòng, số ngày/tháng viết chồng lên nhau...) — kiểu ảnh "KHACH KHAI...pdf"
mà khách chụp/scan.

Cách chạy (từ thư mục backend):

    .venv/Scripts/python.exe scripts/test_handwriting_ocr.py path/to/anh1.jpg path/to/anh2.jpg

    # hoặc trong container
    docker exec immigration-ai-backend python scripts/test_handwriting_ocr.py /path/anh.jpg

Mỗi lần chạy tạo 1 file log mới trong backend/ocr_debug/handwriting_test/ chứa: ảnh nào,
model nào, prompt gửi đi, raw response, và JSON đã parse — để so sánh giữa các lần chỉnh
prompt mà không cần đọc lại code.

GPT-4.1 KHÔNG deterministic — cùng ảnh, cùng prompt vẫn có thể ra field khác nhau giữa các
lần gọi (đã quan sát thực tế: "60/4" ↔ "601/4", "Thích Bửu Đăng" ↔ "Thiếu Bùi Đăng"). Dùng
--repeat N để gọi N lần và tự động so sánh field nào KHÔNG khớp giữa các lần — field bất
đồng gần như chắc chắn cần người review, field đồng nhất N/N lần thì tin cậy hơn hẳn.

    .venv/Scripts/python.exe scripts/test_handwriting_ocr.py --repeat 3 path/to/anh.jpg
"""

import asyncio
import base64
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.services.llm_client import get_ocr_client  # noqa: E402

LOG_DIR = Path(__file__).resolve().parent.parent / "ocr_debug" / "handwriting_test"

# Vision API resize ảnh sao cho CẠNH NGẮN ≈768px trước khi model "nhìn" (xem giải thích
# chi tiết trong ocr_pipeline.py). Ảnh dạng ghép dọc 2 tấm ảnh cao (như "KHACH KHAI...pdf")
# có cạnh ngắn là CHIỀU NGANG — cả trang cao ngất bị nén xuống 768px ngang, chữ viết tay ở
# nửa dưới gần như mất hết độ phân giải và model đọc sai/bỏ sót. Cắt ảnh cao thành các dải
# NGANG (rows) trước khi gửi thì cạnh ngắn của mỗi dải là chiều cao, được kéo lên 768 thay
# vì bị nén — giữ được nhiều điểm ảnh chữ viết tay hơn hẳn.
_ASPECT_RATIO_SPLIT_THRESHOLD = 1.3  # height / width > ngưỡng này thì tự động cắt theo hàng
_TILE_OVERLAP_Y = 0.06


def _auto_split_tall_image(path: Path) -> list[Path]:
    """Ảnh quá cao (vd 2 tấm ghép dọc) → cắt thành 2 dải ngang chồng lấn nhẹ. Ngược lại giữ nguyên."""
    try:
        from PIL import Image

        with Image.open(path) as img:
            width, height = img.size
            if height / width < _ASPECT_RATIO_SPLIT_THRESHOLD:
                return [path]

            half = height / 2
            overlap = half * _TILE_OVERLAP_Y
            bounds = [(0, min(height, half + overlap)), (max(0, half - overlap), height)]
            out: list[Path] = []
            for i, (top, bottom) in enumerate(bounds):
                dest = path.parent / f"{path.stem}_tile{i + 1}of2.jpg"
                img.crop((0, int(top), width, int(bottom))).convert("RGB").save(
                    str(dest), "JPEG", quality=90
                )
                out.append(dest)
            return out
    except Exception:
        return [path]

# Prompt riêng cho chữ viết tay: khác EXTRACTION_PROMPT_TEMPLATE ở ocr_pipeline.py vì mục
# đích ở đây là ĐÁNH GIÁ khả năng đọc chữ tay (từng ký tự/từ khó), không phải map vào field
# cố định — nên yêu cầu model transcribe RAW trước, rồi mới diễn giải theo cấu trúc bảng.
HANDWRITING_OCR_PROMPT = """Bạn là chuyên gia đọc chữ viết tay tiếng Việt trên form giấy tờ (visa/định cư).

Ảnh (có thể gồm nhiều tấm, là các dải cắt từ CÙNG một trang/nhiều trang liên tiếp — dải sau có thể
lặp lại một phần nội dung dải trước do chồng lấn khi cắt) là một form khai LỊCH SỬ ĐỊA CHỈ (address
history) — có phần in sẵn (tiêu đề, nhãn tiếng Anh/Việt) và phần viết tay bằng bút mực xanh (câu trả
lời của khách: ngày tháng, địa chỉ, tên đường/phường/quận). Nếu nhiều ảnh chứa cùng 1 dòng do chồng
lấn, chỉ liệt kê MỘT LẦN trong kết quả, không nhân đôi.

Chữ viết tay có thể khó đọc vì: chữ số chồng lên nhau (vd "13/2009" sửa từ "1/2009"), chữ viết chèn
thêm phía trên dòng (chú thích như "phường", tên phường viết nhỏ chèn vào), gạch xoá và viết đè,
nét chữ nghiêng dính liền nhau.

CẢNH BÁO NHẦM LẪN "/" VỚI SỐ "1": trong ngày tháng viết tay kiểu "8/2018", dấu gạch chéo phân cách
tháng/năm rất dễ bị đọc nhầm thành số "1" (và ngược lại, số "1" viết nghiêng dễ bị đọc nhầm thành "/")
vì nét chữ gần giống hệt nhau, đặc biệt khi ảnh hơi mờ hoặc chữ viết nhanh/nghiêng. Khi đọc mỗi mốc
thời gian dạng "tháng/năm":
- Đếm số ký tự PHÂN TÁCH: đúng 1 dấu "/" giữa tháng và năm — nếu bạn thấy 2 số "1" liền kề bất
  thường không hợp lý làm tháng (vd "111996" hay tháng > 12), rất có thể 1 trong số đó thực ra là "/".
- Đối chiếu bằng LOGIC ĐỊNH DẠNG (không phải đoán giá trị): tháng phải là 1-12, năm phải có 4 chữ số.
  Nếu cách đọc hiện tại vi phạm định dạng này, thử đọc lại xem có phải "/" bị nhầm "1" hay "1" bị nhầm
  "/" không — nhưng đây là kiểm tra CÁCH PHÂN ĐOẠN ký tự, KHÔNG phải đoán số bên trong tháng/năm.
- Nếu vẫn không chắc sau khi đối chiếu, ghi rõ trong "uncertain_fragments" (vd: "'111996' — không rõ
  đọc là '1/1996' hay '11/1996', dấu '/' và số '1' khó phân biệt trong nét viết tay này").

NHIỆM VỤ:
1. Chép lại NGUYÊN VĂN (transcribe) từng dòng chữ viết tay bạn nhìn thấy, theo đúng thứ tự trên ảnh.
2. Với mỗi dòng thuộc bảng "địa chỉ ở" (from - to - address), tách thành: from_date, to_date, address.
3. Nếu có chữ sửa/viết đè (2 nét chồng lên nhau tại cùng vị trí, vd số "12" bị viết đè thành "13"):
   NÉT ĐẬM HƠN / DÀY HƠN / MỰC RÕ HƠN là nét viết SAU (bản sửa cuối cùng, người viết tô lại để khẳng
   định) — ưu tiên lấy giá trị theo nét đậm hơn làm giá trị chính thức (value chính của from_date/
   to_date/address). Nét mảnh/nhạt hơn bên dưới là giá trị GỐC đã bị sửa — vẫn ghi lại trong
   "correction_notes" (field mới, xem schema) kèm mô tả "gốc là X, đã sửa đè thành Y (nét Y đậm hơn)".
   Nếu độ đậm 2 nét gần như nhau (không phân biệt được nét nào sau) → KHÔNG đoán, ghi cả 2 khả năng
   vào "uncertain_fragments" và lấy nét trông giống số hoàn chỉnh hơn làm value tạm, đánh confidence
   thấp (<0.6).
   ĐỪNG bỏ qua giá trị gốc — liệt kê cả giá trị gốc và giá trị sửa nếu phân biệt được.
4. Với chữ chèn nhỏ phía trên (như tên phường/quận viết thêm), gắn vào đúng dòng địa chỉ liên quan,
   ghi trong "inserted_notes".
5. QUY ƯỚC VIẾT TẮT ĐỊA CHỈ (rất phổ biến trong form tiếng Việt): nếu 1 địa chỉ chỉ ghi phần đầu rồi
   kết thúc bằng dấu "..." hoặc chấm lửng (vd "196 Kiệt 7, Đường Ưng Bình,..."), điều đó có nghĩa là
   "phần còn lại giống hệt một địa chỉ ĐẦY ĐỦ đã xuất hiện Ở DÒNG KHÁC TRƯỚC ĐÓ trên form (không nhất
   thiết là dòng ngay phía trên — có thể địa chỉ xen kẽ giữa 2-3 nơi ở khác nhau qua các mốc thời
   gian)". Xử lý bằng cách:
   a. Tìm trong các dòng đã đọc được TRƯỚC ĐÓ một địa chỉ đầy đủ có PHẦN ĐẦU trùng với phần đã viết
      (cùng số nhà/kiệt, cùng tên đường).
   b. Nếu tìm được → điền "address" bằng bản ĐẦY ĐỦ đó, giữ "address_raw" là đúng những gì viết tay
      thực tế ghi (kể cả dấu "..."), và set "expanded_from_repeat": true.
   c. Nếu KHÔNG tìm được địa chỉ đầy đủ nào khớp phần đầu → GIỮ NGUYÊN "address" = "address_raw" (kể
      cả dấu "..."), set "expanded_from_repeat": false, và thêm warning — ĐỪNG bịa ra phần còn thiếu.

QUY TẮC CHỐNG BỊA - CỰC KỲ QUAN TRỌNG:
- CHỈ chép lại chữ bạn THỰC SỰ đọc được rõ. KHÔNG suy luận/đoán dựa trên format form hay logic thời gian
  (vd không tự "sửa" ngày tháng cho hợp lý với dòng trước/sau).
  - Nếu 1 ký tự/số không chắc chắn → dùng "?" ở đúng vị trí đó (vd "13/200?") thay vì đoán bừa.
- Nếu cả dòng không đọc được → để value là null và giải thích trong "notes", KHÔNG bỏ qua dòng đó.
- Nếu có mâu thuẫn giữa 2 lần viết cùng 1 thông tin (vd 2 bảng ghi ngày khác nhau cho cùng 1 địa chỉ)
  → KHÔNG tự chọn cái "đúng hơn", liệt kê cả hai và ghi warning.

Trả về ONLY valid JSON theo schema:
{
  "raw_transcription": ["<dòng 1 y nguyên>", "<dòng 2 y nguyên>", ...],
  "address_history": [
    {
      "from_date": "<string như viết, vd '11/1996' hoặc null nếu không đọc được>",
      "to_date": "<string như viết, vd '12/2008' hoặc null>",
      "address_raw": "<string đúng nguyên văn viết tay, kể cả dấu '...' nếu có>",
      "address": "<string địa chỉ đầy đủ — đã suy ra từ quy ước '...' nếu áp dụng được, ngược lại = address_raw>",
      "expanded_from_repeat": true/false,
      "inserted_notes": "<chữ chèn thêm liên quan tới dòng này, '' nếu không có>",
      "correction_notes": "<mô tả chữ số/chữ bị viết đè sửa lại ở dòng này (gốc → sửa, nét nào đậm hơn), '' nếu không có>",
      "confidence": 0.0-1.0
    }
  ],
  "uncertain_fragments": ["<liệt kê từng đoạn chữ/số không chắc chắn và lý do>"],
  "warnings": ["<mâu thuẫn, chữ bị gạch xoá/viết đè, phần không đọc được...>"]
}"""


def _encode_image(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower()
    mime = {
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(suffix, "image/jpeg")
    data = base64.standard_b64encode(path.read_bytes()).decode("utf-8")
    return mime, data


async def run_ocr(image_paths: list[Path]) -> dict:
    client = get_ocr_client()
    content: list[dict] = [{"type": "text", "text": HANDWRITING_OCR_PROMPT}]
    for path in image_paths:
        mime, data = _encode_image(path)
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{data}", "detail": "high"},
            }
        )

    response = await client.chat.completions.create(
        model=settings.ocr_model,
        messages=[{"role": "user", "content": content}],
    )
    raw_text = response.choices[0].message.content or ""
    usage = response.usage

    parsed: object = None
    parse_error: str | None = None
    try:
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        parsed = json.loads(cleaned.strip())
    except Exception as exc:
        parse_error = f"{type(exc).__name__}: {exc}"

    return {
        "model": settings.ocr_model,
        "images": [str(p) for p in image_paths],
        "raw_response": raw_text,
        "parsed": parsed,
        "parse_error": parse_error,
        "usage": {
            "prompt_tokens": usage.prompt_tokens if usage else None,
            "completion_tokens": usage.completion_tokens if usage else None,
            "total_tokens": usage.total_tokens if usage else None,
        },
    }


_COMPARE_FIELDS = ["from_date", "to_date", "address_raw", "address", "correction_notes"]


def _address_history(result: dict) -> list[dict]:
    parsed = result.get("parsed")
    if not isinstance(parsed, dict):
        return []
    rows = parsed.get("address_history")
    return rows if isinstance(rows, list) else []


def compare_runs(results: list[dict]) -> list[dict]:
    """So sánh address_history giữa N lần chạy, gióng theo INDEX (không theo from_date vì
    chính from_date cũng có thể là field bất đồng giữa các lần — gióng theo index đơn giản
    và đủ dùng khi số dòng ổn định; nếu số dòng lệch nhau giữa các lần thì tự nó đã là 1
    dấu hiệu bất ổn định đáng nêu ra, không cần thuật toán khớp phức tạp hơn."""
    per_run_rows = [_address_history(r) for r in results]
    max_rows = max((len(rows) for rows in per_run_rows), default=0)

    row_counts = [len(rows) for rows in per_run_rows]
    diff: list[dict] = []
    if len(set(row_counts)) > 1:
        diff.append({"row": None, "field": "SỐ DÒNG address_history", "values": row_counts, "agree": False})

    for i in range(max_rows):
        for field in _COMPARE_FIELDS:
            values = [rows[i].get(field) if i < len(rows) else "<thiếu dòng>" for rows in per_run_rows]
            agree = len(set(values)) == 1
            if not agree:
                diff.append({"row": i, "field": field, "values": values, "agree": False})
    return diff


def write_log(results: list[dict], diff: list[dict] | None = None) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = LOG_DIR / f"{timestamp}.log"

    lines: list[str] = []
    lines.append("=" * 70)
    lines.append(f"THỜI GIAN     : {timestamp}")
    lines.append(f"SỐ LẦN CHẠY   : {len(results)}")
    lines.append(f"MODEL         : {results[0]['model']}")
    lines.append(f"ẢNH           : {results[0]['images']}")
    lines.append("=" * 70)
    lines.append("PROMPT GỬI ĐI:")
    lines.append(HANDWRITING_OCR_PROMPT)

    for idx, result in enumerate(results, start=1):
        lines.append("=" * 70)
        lines.append(f"--- LẦN CHẠY {idx}/{len(results)} --- USAGE: {result['usage']}")
        lines.append("RAW RESPONSE:")
        lines.append(result["raw_response"])
        if result["parse_error"]:
            lines.append(f"PARSE ERROR: {result['parse_error']}")
        else:
            lines.append("PARSED JSON:")
            lines.append(json.dumps(result["parsed"], ensure_ascii=False, indent=2))

    if diff is not None:
        lines.append("=" * 70)
        lines.append(f"SO SÁNH GIỮA {len(results)} LẦN CHẠY (chỉ liệt kê field KHÔNG khớp):")
        if not diff:
            lines.append("  Tất cả field khớp 100% giữa các lần chạy.")
        else:
            for d in diff:
                row_label = "TOÀN BỘ" if d["row"] is None else f"dòng {d['row']}"
                lines.append(f"  [{row_label}] {d['field']}:")
                for i, v in enumerate(d["values"], start=1):
                    lines.append(f"      lần {i}: {v!r}")
    lines.append("=" * 70)

    log_path.write_text("\n".join(lines), encoding="utf-8")
    return log_path


async def main() -> None:
    argv = sys.argv[1:]
    repeat = 1
    if "--repeat" in argv:
        idx = argv.index("--repeat")
        repeat = int(argv[idx + 1])
        argv = argv[:idx] + argv[idx + 2 :]

    if not argv:
        print("Dùng: python scripts/test_handwriting_ocr.py [--repeat N] anh1.jpg [anh2.jpg ...]")
        sys.exit(1)

    input_paths = [Path(p).resolve() for p in argv]
    missing = [p for p in input_paths if not p.exists()]
    if missing:
        print(f"Không tìm thấy file: {missing}")
        sys.exit(1)

    image_paths: list[Path] = []
    for p in input_paths:
        tiles = _auto_split_tall_image(p)
        if len(tiles) > 1:
            print(f"  {p.name}: ảnh cao bất thường → cắt thành {len(tiles)} dải ngang trước khi gửi.")
        image_paths.extend(tiles)

    print(f"Đang gọi OCR ({settings.ocr_model}) cho {len(image_paths)} ảnh, {repeat} lần...")
    results = []
    for i in range(repeat):
        results.append(await run_ocr(image_paths))
        print(f"  lần {i + 1}/{repeat} xong.")

    diff = compare_runs(results) if repeat > 1 else None
    log_path = write_log(results, diff)
    print(f"Đã ghi log: {log_path}")

    result = results[0]
    if result["parse_error"]:
        print(f"⚠️  Parse JSON lỗi (lần 1): {result['parse_error']}")
    else:
        n_lines = len(result["parsed"].get("raw_transcription", [])) if isinstance(result["parsed"], dict) else 0
        n_rows = len(result["parsed"].get("address_history", [])) if isinstance(result["parsed"], dict) else 0
        print(f"OK (lần 1) — {n_lines} dòng transcribe, {n_rows} dòng địa chỉ đã tách.")

    if diff is not None:
        if not diff:
            print(f"✅ {repeat}/{repeat} lần khớp 100% — kết quả đáng tin cậy.")
        else:
            print(f"⚠️  {len(diff)} field KHÔNG khớp giữa {repeat} lần chạy — xem chi tiết trong log:")
            for d in diff:
                row_label = "TOÀN BỘ" if d["row"] is None else f"dòng {d['row']}"
                print(f"   [{row_label}] {d['field']}: {d['values']}")


if __name__ == "__main__":
    asyncio.run(main())
