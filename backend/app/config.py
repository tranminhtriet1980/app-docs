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
    upload_dir: str = "uploads"
    export_dir: str = "exports"
    templates_dir: str = "templates/forms"
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
    def ocr_model(self) -> str:
        """Model dùng cho OCR tài liệu — vision_model nếu đặt, ngược lại openai_model."""
        return (self.vision_model or "").strip() or self.openai_model

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
