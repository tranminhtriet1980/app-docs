# Immigration AI — Form Filler

Ứng dụng AI hỗ trợ điền form định cư & du học Mỹ: upload giấy tờ → OCR/trích xuất → hợp nhất hồ sơ → review → xuất Word.

## Kiến trúc

```
Next.js (Upload + Review Dashboard)
    ↓
FastAPI (Auth, Upload, OCR Pipeline, Export)
    ↓
PostgreSQL (dữ liệu) + MinIO/S3 (file upload + export)
    ↓
OpenAI GPT-4.1 (classification + extraction) — demo mode nếu không có API key
```

## Yêu cầu

- Docker Desktop (PostgreSQL + MinIO)
- Python 3.11+
- Node.js 18+

## Cài đặt nhanh

### 1. PostgreSQL + MinIO

```bash
docker compose up -d
```

Khởi động 2 container:

- `immigration-ai-db` — PostgreSQL, port 5432
- `immigration-ai-minio` — MinIO (S3 API port 9000, console web port 9001)

### 2. Backend

```bash
cd backend
cp .env.example .env
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Sửa `backend/.env`:

- `POSTGRES_*` — khớp với `docker-compose.yml` (mặc định user/db `immigration`/`ImmigrationDevDB`)
- `S3_ACCESS_KEY` / `S3_SECRET_KEY` — **phải điền giá trị thật**, khớp với `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` (không dùng cú pháp `${...}`, `.env` không tự expand biến)
- `OPENAI_API_KEY` — thêm để dùng OCR thật, không có key thì chạy demo mode (dữ liệu mẫu từ tên file)

```env
OPENAI_API_KEY=sk-your-openai-key
OPENAI_MODEL=gpt-4.1
```

Lấy API key tại [platform.openai.com/api-keys](https://platform.openai.com/api-keys).

Bảng DB được tự tạo lúc khởi động backend (`init_db()` → `create_all`), **không cần chạy Alembic** trên DB mới. Sau lần chạy đầu tiên, đánh dấu Alembic ở baseline để các migration sau này áp dụng đúng:

```bash
alembic stamp head
```

Kiểm tra: `GET http://localhost:8000/health` → `"openai_configured": true`

### 3. Frontend

```bash
cd frontend
cp .env.local.example .env.local
npm install
npm run dev
```

Mở http://localhost:3000

## Quy trình sử dụng

1. **Đăng ký / đăng nhập**
2. **Tạo hồ sơ** trên Dashboard
3. **Upload** passport, visa, I-20, I-94... (Upload Dashboard)
4. AI tự **phân loại → trích xuất → merge profile**
5. **Review Dashboard**: sửa field, giải quyết xung đột, duyệt hồ sơ
6. **Xuất Word** (DS-160 worksheet / I-539 worksheet)

## API chính

| Endpoint | Mô tả |
|----------|--------|
| `POST /api/v1/auth/register` | Đăng ký |
| `POST /api/v1/auth/login` | Đăng nhập |
| `POST /api/v1/applicants` | Tạo hồ sơ |
| `POST /api/v1/applicants/{id}/documents` | Upload file |
| `GET /api/v1/applicants/{id}/profile` | Xem profile đã merge |
| `POST /api/v1/applicants/{id}/review/approve` | Duyệt review |
| `POST /api/v1/applicants/{id}/export` | Xuất form Word |

Swagger: http://localhost:8000/docs

## Cấu trúc thư mục

```
backend/
  app/api/          # REST endpoints
  app/services/      # OCR, merge, export, storage (MinIO/S3)
  alembic/           # Migration schema (baseline — xem alembic/versions/)
  uploads/, exports/ # Fallback đĩa cục bộ khi không bật S3 (xem app/config.py s3_enabled)
frontend/
  src/app/           # Pages (dashboard, upload, review)
docker-compose.yml      # PostgreSQL + MinIO (dev)
docker-compose.prod.yml # Full stack HTTPS port 2026 (Postgres + MinIO + Backend + Frontend + Caddy)
deploy/                 # Caddy, certs, hướng dẫn triển khai
```

## Lưu trữ file (MinIO / S3)

Mặc định file upload + export lưu qua MinIO (S3-compatible). Để trống `S3_ENDPOINT_URL` trong `backend/.env` thì backend rơi về đĩa cục bộ (`backend/uploads`, `backend/exports`) như trước — xem `app/config.py` (`s3_enabled`) và `app/services/storage.py`.

Console web MinIO: http://localhost:9001 (đăng nhập bằng `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`).

## Triển khai Docker (HTTPS port 2026)

Xem chi tiết: [deploy/README.md](deploy/README.md)

```bash
cp .env.production.example .env.production
# Sửa .env.production: SECRET_KEY, POSTGRES_PASSWORD, MINIO_ROOT_PASSWORD, DOMAIN, OPENAI_API_KEY, ...
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

Mở **https://YOUR_DOMAIN:2026** (mặc định TLS self-signed — trình duyệt có thể cảnh báo).

## Lưu ý

- Dữ liệu nhạy cảm — chỉ dùng môi trường dev/local có bảo mật phù hợp.
- AI **hỗ trợ**, không thay tư vấn luật di trú. Luôn kiểm tra form trước khi nộp.
