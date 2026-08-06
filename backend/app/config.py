from pathlib import Path
from urllib.parse import quote_plus
import os

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://immigration:immigration_dev@localhost:5432/immigration_ai"
    postgres_host: str = ""
    postgres_port: int = 5432
    postgres_user: str = ""
    postgres_password: str = ""
    postgres_db: str = ""
    secret_key: str = "dev-secret-change-in-production"
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1"
    # Base URL cho client OpenAI-compatible (vd. OpenRouter, Gemini OpenAI-compat) — trống = OpenAI.
    openai_base_url: str = ""
    # Model riêng cho OCR tài liệu (đọc ảnh/chữ tay). Trống → dùng openai_model.
    # Đặt model vision mạnh hơn cho worksheet viết tay, vd. "gpt-4o" hoặc (qua OCR base_url) "google/gemini-2.5-pro".
    vision_model: str = ""
    # Client OCR riêng — cho phép chạy OCR ở provider/model khác chat. Trống → kế thừa openai_*.
    ocr_api_key: str = ""
    ocr_base_url: str = ""
    # Lưới cắt mỗi trang worksheet DS-260 viết tay trước khi gửi Vision API.
    # Cắt trang làm chữ tay nét hơn, NHƯNG token tăng xấp xỉ theo số ảnh và trần
    # tokens-per-minute của OpenAI áp cho TỪNG request — một request vượt trần thì
    # không bao giờ thành công, retry vô ích. Đo trên worksheet 20 trang, tier 30k TPM:
    #     rows=1  20 ảnh  ~22k token  → lọt
    #     rows=2  40 ảnh  ~31k token  → 429
    #     rows=4  80 ảnh  ~116k token → 429 (đã gây sự cố prod 30/07/2026)
    # ⇒ mặc định TẮT (1x1). Chỉ tăng rows khi OCR đã chia nhỏ theo TPM, hoặc khi
    # tài khoản ở tier cao hơn. Kiểm tra trần bằng header `x-ratelimit-limit-tokens`.
    ocr_worksheet_rows: int = 1
    ocr_worksheet_cols: int = 1
    # Số ảnh tối đa mỗi request Vision API; vượt thì chia thành nhiều request nối tiếp
    # rồi gộp kết quả. Trần TPM áp cho TỪNG request nên chia nhỏ là cách duy nhất gửi
    # được tài liệu nhiều trang. 20 ảnh nguyên trang ≈ 22k token — lọt trần 30k.
    # 0 = không chia (hành vi cũ).
    ocr_max_images_per_request: int = 20
    # Trần số trang PDF render cho worksheet DS-260 khách khai — cũ cố định 20 trang (ước tính
    # cho worksheet "điển hình" ~18 trang), nhưng bản scan/chụp thực tế có thể dài hơn NHIỀU
    # (bản 146 trang gặp thực tế 2026-08-05 — mỗi trang giấy có thể bị chụp/scan thành nhiều
    # trang PDF). Vượt trần 20 trang cũ → các mục cuối form (Work/Education Part D, An ninh,
    # SSN) NẰM SAU trang 20 không bao giờ được render/gửi AI đọc — trống âm thầm không cảnh
    # báo. Nâng trần cao hơn nhiều + để _openai_extract tự đo SỐ TRANG THẬT của file, lấy
    # min(số trang thật, trần này) — không render thừa cho file ngắn, không cắt cụt file dài.
    # ocr_max_images_per_request vẫn lo việc chia nhỏ request theo TPM như cũ.
    ocr_ds260_worksheet_max_pages: int = 150
    ocr_blur_variance_threshold: float = 25.0
    ocr_low_confidence_threshold: float = 0.5
    ocr_low_confidence_field_ratio: float = 0.25
    # Hướng dẫn đọc chữ viết tay bổ sung (quy ước "..." = giống địa chỉ đã ghi trước đó, ưu tiên
    # nét đậm hơn khi có chữ sửa đè, cảnh báo nhầm "/" với số "1") — đúc kết từ script thử nghiệm
    # scripts/test_handwriting_ocr.py. BẬT RIÊNG TỪNG LOẠI TÀI LIỆU (không dùng 1 cờ chung) vì hint
    # này chỉ có ích cho tài liệu có phần VIẾT TAY (worksheet khách khai, giấy khai sinh bản chính
    # cũ thường viết tay trong sổ hộ tịch...) — bật tràn lan cho giấy tờ in sẵn hoàn toàn (passport,
    # ly hôn, kết hôn...) chỉ tốn thêm token vô ích mỗi request.
    # Thêm field mới ocr_handwriting_correction_rules_<doc_type> khi cần bật cho loại tài liệu khác
    # (đọc qua Settings.handwriting_correction_rules_enabled(doc_type), không cần sửa ocr_pipeline.py).
    ocr_handwriting_correction_rules_ds260_customer_form: bool = False
    ocr_handwriting_correction_rules_birth_certificate: bool = False
    ocr_handwriting_correction_rules_birth_certificate_child: bool = False
    # Gọi lại toàn bộ OCR N lần cho CÙNG tài liệu rồi gộp theo đa số phiếu mỗi field (xem
    # _merge_consensus_runs trong ocr_pipeline.py) — field bất đồng giữa các lần bị hạ confidence
    # + thêm warning, thay vì tin mù 1 lần chạy duy nhất (model không deterministic, đã quan sát
    # field số nhà/tên đường đổi giữa các lần gọi). CHI PHÍ NHÂN N LẦN — mặc định TẮT (1 = không lặp).
    ocr_consensus_runs: int = 1
    upload_dir: str = "uploads"
    export_dir: str = "exports"
    templates_dir: str = "templates/forms"
    # Lưu trữ đối tượng (MinIO/S3-compatible) cho document upload + export file — TẮT khi
    # s3_endpoint_url rỗng (mặc định), lúc đó mọi thứ dùng đĩa cục bộ y hệt trước đây (KHÔNG
    # thay đổi hành vi). Bật bằng cách set S3_ENDPOINT_URL trong .env (xem docker-compose.yml
    # / docker-compose.prod.yml — service "minio"). CHỈ áp dụng cho file MỚI: file cũ đã lưu
    # trên đĩa (file_path là đường dẫn cục bộ, không có tiền tố "s3://") vẫn đọc được bình
    # thường — xem app/services/storage.py (is_s3_uri phân biệt 2 loại qua tiền tố).
    s3_endpoint_url: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "immipath-documents"
    s3_region: str = "us-east-1"
    cors_origins: str = "http://localhost:3000"
    access_token_expire_minutes: int = 60 * 24
    app_name: str = "ImmiPath"
    app_base_url: str = "http://localhost:3000"
    backup_dir: str = "backups"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "noreply@immipath.local"
    smtp_use_tls: bool = True
    # Token cost estimate (USD per 1M tokens) — adjust for your model pricing
    openai_input_cost_per_1m: float = 0.15
    openai_output_cost_per_1m: float = 0.60
    monthly_token_budget: int = 0  # 0 = unlimited
    admin_email: str = ""
    admin_password: str = ""

    @property
    def base_dir(self) -> Path:
        return BASE_DIR

    @property
    def backup_path(self) -> Path:
        path = BASE_DIR / self.backup_dir
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def upload_path(self) -> Path:
        path = BASE_DIR / self.upload_dir
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def export_path(self) -> Path:
        path = BASE_DIR / self.export_dir
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def templates_path(self) -> Path:
        path = BASE_DIR / self.templates_dir
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def s3_enabled(self) -> bool:
        return bool((self.s3_endpoint_url or "").strip())

    @property
    def ocr_model(self) -> str:
        """Model dùng cho OCR tài liệu — vision_model nếu đặt, ngược lại openai_model."""
        return (self.vision_model or "").strip() or self.openai_model

    def handwriting_correction_rules_enabled(self, doc_type: str) -> bool:
        """True nếu field ocr_handwriting_correction_rules_<doc_type> tồn tại và = true.

        Loại tài liệu chưa có field riêng (giấy tờ in sẵn, không cần hint chữ viết tay) → luôn
        False, KHÔNG fallback về 1 cờ chung — tránh bật nhầm hàng loạt khi thêm field mới.
        """
        return bool(getattr(self, f"ocr_handwriting_correction_rules_{doc_type}", False))

    @property
    def resolved_database_url(self) -> str:
        env_host = os.environ.get("POSTGRES_HOST", "").strip()
        env_user = os.environ.get("POSTGRES_USER", "").strip()
        env_password = os.environ.get("POSTGRES_PASSWORD", "")
        env_db = os.environ.get("POSTGRES_DB", "").strip()
        env_port = os.environ.get("POSTGRES_PORT", "").strip()

        host = env_host or (self.postgres_host or "").strip()
        user = env_user or self.postgres_user or "immigration"
        password = env_password or self.postgres_password
        db = env_db or self.postgres_db or "immigration_ai"
        port = int(env_port or self.postgres_port or 5432)

        # Docker Compose: DB vars injected via environment.
        if not host and password:
            host = "postgres"

        if host and password:
            return (
                f"postgresql+asyncpg://{quote_plus(user)}:{quote_plus(password)}@"
                f"{host}:{port}/{quote_plus(db)}"
            )
        return self.database_url


settings = Settings()
