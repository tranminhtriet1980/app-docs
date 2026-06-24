# Luồng triển khai: Cursor → GitHub → Docker

Repo GitHub: [github.com/tranminhtriet1980/app-docs](https://github.com/tranminhtriet1980/app-docs)

```
┌─────────────┐     git push      ┌─────────────┐    git pull + build    ┌─────────────┐
│   Cursor    │ ───────────────►  │   GitHub    │ ────────────────────►  │   Docker    │
│  d:\app docs│                   │  app-docs   │   (máy server)         │  production │
└─────────────┘                   └─────────────┘                        └─────────────┘
```

## Vai trò từng nơi

| Nơi | Đường dẫn gợi ý | Mục đích |
|-----|-----------------|----------|
| **Cursor (dev)** | `d:\app docs` | Sửa code, test local |
| **GitHub** | `tranminhtriet1980/app-docs` | Lưu source, lịch sử thay đổi |
| **Docker (prod)** | `C:\Docker\app docs` | Chạy `docker-compose.prod.yml` |

> Giữ **2 thư mục tách nhau**: dev không ghi đè trực tiếp lên prod. Prod chỉ cập nhật qua `git pull` + build Docker.

---

## Bước 1 — Lần đầu: đẩy code lên GitHub (từ Cursor)

Mở terminal trong `d:\app docs`:

```powershell
cd "d:\app docs"

# Gắn remote GitHub (chỉ làm 1 lần)
git remote add origin https://github.com/tranminhtriet1980/app-docs.git

# Đổi nhánh chính thành main (GitHub mặc định dùng main)
git branch -M main

# Stage và commit lần đầu
git add .
git status   # kiểm tra: KHÔNG có .env, .env.production, Data test/

git commit -m "Initial commit: ImmiFill DS-260 app"

# Đẩy lên GitHub (đăng nhập GitHub khi được hỏi)
git push -u origin main
```

### Xác thực GitHub

- **HTTPS:** dùng [Personal Access Token](https://github.com/settings/tokens) thay mật khẩu khi `git push`.
- **SSH (khuyến nghị lâu dài):**
  ```powershell
  ssh-keygen -t ed25519 -C "your@email.com"
  # Thêm public key vào GitHub → Settings → SSH keys
  git remote set-url origin git@github.com:tranminhtriet1980/app-docs.git
  ```

### File KHÔNG được commit

Đã cấu hình trong `.gitignore`:

- `.env`, `.env.production`, `backend/.env`
- `node_modules/`, `backend/.venv/`
- `Data test/` (dữ liệu thật)
- File tạm Word `~$*.docx`

---

## Bước 2 — Lần đầu: clone trên máy Docker

Trên máy chạy Docker production:

```powershell
cd C:\Docker
git clone https://github.com/tranminhtriet1980/app-docs.git "app docs"
cd "app docs"

copy .env.production.example .env.production
# Sửa .env.production: SECRET_KEY, POSTGRES_PASSWORD, OPENAI_API_KEY, DOMAIN...

docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

Hoặc dùng script:

```powershell
.\deploy\up.ps1 up -d --build
```

---

## Bước 3 — Quy trình hàng ngày (sau khi sửa code trong Cursor)

### Trên máy dev (Cursor)

```powershell
cd "d:\app docs"

git status
git add backend/ frontend/ deploy/   # hoặc git add . nếu chắc chắn
git commit -m "Mô tả ngắn thay đổi"
git push origin main
```

### Trên máy Docker (production)

```powershell
cd "C:\Docker\app docs"
.\deploy\pull-and-deploy.ps1
```

Script sẽ: `git pull` → `docker compose up -d --build`.

Chỉ build lại 1 service (nhanh hơn):

```powershell
.\deploy\pull-and-deploy.ps1 -Service frontend
.\deploy\pull-and-deploy.ps1 -Service backend
```

Kiểm tra:

```powershell
.\deploy\up.ps1 ps
curl.exe -k https://localhost:2026/health
```

---

## Sơ đồ quy trình đề xuất

```
1. Sửa code trong Cursor (d:\app docs)
2. Test local (tùy chọn): npm start hoặc docker compose
3. git commit + git push → GitHub
4. SSH/RDP vào máy Docker
5. .\deploy\pull-and-deploy.ps1
6. Kiểm tra /health và Review UI
```

---

## Lưu ý quan trọng

### `.env.production` chỉ ở máy Docker

- File này **không** nằm trên GitHub.
- Sau `git pull`, `.env.production` trên server **giữ nguyên** — không bị ghi đè.

### Dữ liệu production (upload, DB)

Lưu trong Docker volumes (`postgres_data`, `backend_uploads`…). `git pull` **không** xóa dữ liệu.

Backup trước khi deploy lớn:

```powershell
docker compose -f docker-compose.prod.yml --env-file .env.production ps
# backup volume theo hướng dẫn deploy/README.md
```

### Nhánh (branch)

| Nhánh | Dùng cho |
|-------|----------|
| `main` | Production — deploy từ nhánh này |
| `dev` | (tùy chọn) thử nghiệm trước khi merge vào main |

---

## (Tùy chọn) Tự động deploy khi push GitHub

Nếu sau này muốn **không cần SSH thủ công**, có thể thêm GitHub Actions:

1. Push lên `main` → workflow chạy
2. SSH vào máy Docker → chạy `pull-and-deploy.ps1`

Cần cấu hình Secrets trên GitHub: `SSH_HOST`, `SSH_USER`, `SSH_KEY`.

Hiện tại dùng **pull thủ công** là đủ cho giai đoạn pilot.

---

## Xử lý lỗi thường gặp

| Lỗi | Cách xử lý |
|-----|------------|
| `Permission denied` khi push | Dùng PAT hoặc SSH key |
| `POSTGRES_PASSWORD is missing` | Tạo `.env.production` trên máy Docker |
| Code mới không lên UI | Chạy lại `--build`, đặc biệt `frontend` |
| Conflict khi pull | `git stash` hoặc không sửa code trực tiếp trên máy Docker |

---

## Tóm tắt 1 dòng

**Cursor push GitHub → trên máy Docker: `.\deploy\pull-and-deploy.ps1`**
