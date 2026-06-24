# Immigration AI — Form Filler

Ứng dụng AI hỗ trợ điền form định cư & du học Mỹ: upload giấy tờ → OCR/trích xuất → hợp nhất hồ sơ → review → xuất Word.

## Kiến trúc

```
Next.js (Upload + Review Dashboard)
    ↓
FastAPI (Auth, Upload, OCR Pipeline, Export)
    ↓
PostgreSQL/SQLite + Local Storage (uploads/, exports/)
    ↓
OpenAI GPT-4.1 (classification + extraction) — demo mode nếu không có API key
```

## Yêu cầu

- Docker Desktop (PostgreSQL)
- Python 3.11+
- Node.js 18+

## Cài đặt nhanh

### 1. Database (tùy chọn)

**Cách A — SQLite (mặc định, không cần Docker):**  
File `backend/.env` đã cấu hình `sqlite+aiosqlite:///./immigration.db`

**Cách B — PostgreSQL (production):**

```powershell
cd "d:\app docs"
docker compose up -d
```

Đổi `DATABASE_URL` trong `backend/.env`:

```
DATABASE_URL=postgresql+asyncpg://immigration:immigration_dev@localhost:5432/immigration_ai
```

### 2. Backend

```powershell
cd backend
copy .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Thêm `OPENAI_API_KEY` vào `backend/.env` để dùng OCR thật. Không có key → **demo mode** (dữ liệu mẫu từ tên file).

```env
OPENAI_API_KEY=sk-your-openai-key
OPENAI_MODEL=gpt-4.1
```

Lấy API key tại [platform.openai.com/api-keys](https://platform.openai.com/api-keys).

Kiểm tra: `GET http://localhost:8000/health` → `"openai_configured": true`

### 3. Frontend

```powershell
cd frontend
copy .env.local.example .env.local
npm install
npm run dev
```

Mở http://localhost:3000

### Chạy 1 lệnh (Backend + Frontend)

```powershell
cd "d:\app docs"
npm start
```

Hoặc double-click **`run.bat`**, hoặc `.\dev.ps1` — cùng một việc.

Một terminal chạy cả hai — mở **http://localhost:3000**

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
  app/services/     # OCR, merge, export
  uploads/          # File gốc
  exports/          # Word đã generate
frontend/
  src/app/          # Pages (dashboard, upload, review)
docker-compose.yml      # PostgreSQL (dev)
docker-compose.prod.yml # Full stack HTTPS port 2026
deploy/                 # Caddy, certs, hướng dẫn triển khai
```

## Triển khai Docker (HTTPS port 2026)

Xem chi tiết: [deploy/README.md](deploy/README.md)

```powershell
cd "d:\app docs"
copy .env.production.example .env.production
# Sửa .env.production: SECRET_KEY, POSTGRES_PASSWORD, DOMAIN, OPENAI_API_KEY, ...
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

Mở **https://YOUR_DOMAIN:2026** (mặc định TLS self-signed — trình duyệt có thể cảnh báo).

## Lưu ý

- Dữ liệu nhạy cảm — chỉ dùng môi trường dev/local có bảo mật phù hợp.
- AI **hỗ trợ**, không thay tư vấn luật di trú. Luôn kiểm tra form trước khi nộp.
