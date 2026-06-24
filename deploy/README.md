# Triển khai Docker (HTTPS port 2026)

Stack gồm **PostgreSQL**, **FastAPI backend**, **Next.js frontend**, **Caddy** (reverse proxy + HTTPS).

Truy cập: `https://DOMAIN:2026`

## Yêu cầu server

- Docker Engine 24+ và Docker Compose v2
- Mở firewall: **2026** (HTTPS), **80** (Let's Encrypt nếu dùng `TLS_MODE=auto`)
- RAM khuyến nghị ≥ 2 GB

## Cài đặt nhanh

```bash
cd /path/to/app
cp .env.production.example .env.production
nano .env.production   # sửa SECRET_KEY, POSTGRES_PASSWORD, DOMAIN, OPENAI_API_KEY, ...
./deploy/up.sh up -d --build
```

Hoặc:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

> **Quan trọng:** Mọi lệnh `docker compose` phải có `--env-file .env.production`, nếu không sẽ báo lỗi `POSTGRES_PASSWORD is missing`.

Kiểm tra:

```bash
./deploy/up.sh ps
curl -k https://localhost:2026/health
```

Trên **Windows PowerShell**, dùng:

```powershell
.\deploy\up.ps1 ps
curl.exe -k https://localhost:2026/health
```

(Không dùng `curl -k` thuần — PowerShell alias `curl` = `Invoke-WebRequest`, không có `-k`.)

Swagger API: `https://YOUR_DOMAIN:2026/api/v1/docs` (qua proxy — backend `/docs` tại `/docs` nếu truy cập trực tiếp backend; qua Caddy dùng `/api` prefix).

> Frontend gọi API cùng origin (`NEXT_PUBLIC_API_URL=""`), Caddy chuyển `/api/*` → backend.

## Truy cập LAN (mọi IP trong mạng nội bộ)

Có thể đăng nhập từ máy khác qua IP server, ví dụ `http://172.16.10.15:3000/login`:

1. Frontend publish port **3000** (`FRONTEND_PORT` trong `.env.production`, mặc định 3000).
2. Next.js proxy `/api/*` → backend (không cần gọi `localhost:8000` từ trình duyệt client).
3. Backend cho phép CORS từ IP private (10.x, 172.16–31.x, 192.168.x).
4. Mở firewall Windows/Linux cho port **3000** (và **2026** nếu dùng Caddy).

```powershell
# Windows — mở port 3000 (chạy PowerShell Admin)
New-NetFirewallRule -DisplayName "ImmiFill Frontend 3000" -Direction Inbound -LocalPort 3000 -Protocol TCP -Action Allow
```

Sau khi sửa code, build lại frontend:

```powershell
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build frontend
```

Hoặc dev local (không Docker):

```bash
cd frontend && npm run dev
# Truy cập http://<IP-máy-dev>:3000/login
# Đặt NEXT_PUBLIC_API_URL= (trống) trong .env.local
```

## Chế độ TLS

### 1. `TLS_MODE=internal` (mặc định — thử nhanh)

Caddy tự tạo chứng chỉ self-signed. Trình duyệt sẽ cảnh báo — chấp nhận exception hoặc dùng IP/domain nội bộ.

```env
TLS_MODE=internal
DOMAIN=203.0.113.10
HTTPS_PORT=2026
```

### 2. `TLS_MODE=auto` (Let's Encrypt — production)

```env
TLS_MODE=auto
DOMAIN=immigration.edupath.org.vn
ACME_EMAIL=admin@edupath.org.vn
HTTPS_PORT=2026
HTTP_PORT=80
```

- DNS `DOMAIN` phải trỏ về IP server
- Port **80** mở ra internet (xác thực ACME)
- Người dùng truy cập: `https://immigration.edupath.org.vn:2026`

### 3. `TLS_MODE=custom` (chứng chỉ có sẵn)

```bash
./deploy/generate-self-signed-cert.sh your-domain.com
# hoặc copy fullchain.pem + privkey.pem vào deploy/certs/
```

```env
TLS_MODE=custom
DOMAIN=your-domain.com
```

## Lệnh quản trị

```bash
# Xem log
docker compose -f docker-compose.prod.yml logs -f

# Dừng
docker compose -f docker-compose.prod.yml down

# Cập nhật code và build lại
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build

# Backup volume PostgreSQL (ví dụ)
docker run --rm -v immigration-ai_postgres_data:/data -v $(pwd):/backup alpine \
  tar czf /backup/postgres-backup.tar.gz -C /data .
```

## Biến môi trường quan trọng

| Biến | Mô tả |
|------|--------|
| `DOMAIN` | Domain hoặc IP public |
| `HTTPS_PORT` | Port host (mặc định **2026**) |
| `FRONTEND_PORT` | Port frontend LAN (mặc định **3000**) — `http://IP:3000/login` |
| `TLS_MODE` | `internal` / `auto` / `custom` |
| `SECRET_KEY` | Bắt buộc — key JWT |
| `POSTGRES_PASSWORD` | Bắt buộc |
| `OPENAI_API_KEY` | OCR thật; để trống = demo mode |

## Kiến trúc

```
Internet :2026 (HTTPS)
    ↓
  Caddy
    ├─ /api/*  → backend:8000
    └─ /*      → frontend:3000
         ↓
    postgres:5432 (nội bộ Docker)
```

Dữ liệu lưu trong Docker volumes: `postgres_data`, `backend_uploads`, `backend_exports`, `backend_backups`.

## Xử lý lỗi thường gặp

### 1. `POSTGRES_PASSWORD is missing`

Chưa tạo hoặc chưa truyền file env:

```bash
cp .env.production.example .env.production
nano .env.production
./deploy/up.sh up -d --build
```

### 2. Backend / Caddy restart liên tục

Xem log:

```bash
./deploy/up.sh logs backend --tail 80
./deploy/up.sh logs caddy --tail 80
```

Nguyên nhân hay gặp:
- `SECRET_KEY` hoặc `POSTGRES_PASSWORD` chưa sửa trong `.env.production`
- Copy từ Windows làm hỏng script (đã chuyển sang `deploy/Caddyfile` tĩnh — copy lại thư mục hoặc chỉ copy file mới)
- Port **2026** hoặc **80** bị chiếm bởi service khác

Khởi động lại sạch:

```bash
./deploy/up.sh down
./deploy/up.sh up -d --build
```

### 3. Trạng thái container mong đợi

| Container | Trạng thái |
|-----------|------------|
| immigration-ai-db | Running (healthy) |
| immigration-ai-backend | Running (healthy) |
| immigration-ai-frontend | Running |
| immigration-ai-caddy | Running, port **2026:443** |

### 4. Kiểm tra health

```bash
curl -k https://localhost:2026/health
```

Kết quả OK: `{"status":"ok",...}`
