# Tổng quan mã nguồn — Frontend & Backend

> **Project:** Immigration AI / ImmiPath DS-260  
> **Stack:** Next.js 14 + FastAPI + SQLAlchemy + OpenAI Vision  
> **Cập nhật:** 2026-06-03

---

## 1. Kiến trúc tổng thể

```
┌──────────────────────────────────────────────────────────────┐
│  FRONTEND  frontend/src/                                     │
│  Next.js App Router · TypeScript · Tailwind                  │
│  Upload / Review / Dashboard / Admin                         │
└────────────────────────────┬─────────────────────────────────┘
                             │ HTTP /api/v1  (Bearer JWT)
┌────────────────────────────▼─────────────────────────────────┐
│  BACKEND  backend/app/                                       │
│  FastAPI · async SQLAlchemy · services layer                 │
│  OCR → DocRecord → DS-260 resolve → Word export              │
└────────────────────────────┬─────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────┐
│  DATA                                                        │
│  SQLite/PostgreSQL · uploads/ · exports/                     │
│  backend/data/doc_schemas/*.json                             │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. BACKEND

### 2.1. Cây thư mục chính

```
backend/
├── app/
│   ├── main.py                 # FastAPI app, CORS, routers
│   ├── config.py               # Settings (.env)
│   ├── database.py             # async engine, session
│   ├── schemas.py              # Pydantic request/response models
│   ├── api/                    # REST endpoints
│   │   ├── auth.py
│   │   ├── applicants.py
│   │   ├── documents.py
│   │   ├── profile.py          # DS-260 form, validate, conflicts, tables
│   │   ├── export.py           # export Word, export-ds260
│   │   ├── admin.py
│   │   └── ...
│   ├── models/
│   │   └── entities.py         # User, Applicant, Document, ApplicantDocRecord, Conflict, Export
│   └── services/               # Business logic
├── data/
│   └── doc_schemas/
│       ├── ds260_mapping.json      # ~130 field DS-260
│       ├── standard_templates.json
│       └── location_to_country.json, province_to_postal_code.json
├── tests/
│   └── test_ds260*.py          # ~79 tests DS-260
├── uploads/                    # PDF gốc
├── exports/                    # Word đã generate
├── requirements.txt
└── .env
```

### 2.2. API routes (`/api/v1`)

#### Auth & user
| Method | Path | File |
|--------|------|------|
| POST | `/auth/register` | auth.py |
| POST | `/auth/login` | auth.py |
| GET | `/auth/me` | auth.py |

#### Applicants
| Method | Path | Mô tả |
|--------|------|--------|
| GET/POST | `/applicants` | List / tạo hồ sơ |
| GET/PATCH/DELETE | `/applicants/{id}` | CRUD |
| GET | `/applicants/{id}/profile` | Profile merge (legacy DS-160 flow) |
| POST | `/applicants/{id}/review/approve` | Duyệt review |

#### Documents & OCR
| Method | Path | Mô tả |
|--------|------|--------|
| POST | `/applicants/{id}/documents` | Upload PDF |
| POST | `/applicants/{id}/documents/batch` | Upload nhiều file |
| POST | `/applicants/{id}/documents/{doc_id}/reprocess` | Chạy lại OCR |
| GET | `/applicants/{id}/documents/{doc_id}/table-record` | DocRecord của file |

#### DS-260 (ImmiPath) — **profile.py**
| Method | Path | Mô tả |
|--------|------|--------|
| GET | `/applicants/config/ds260-mapping` | Cấu hình mapping JSON |
| GET | `/applicants/{id}/ds260-form` | Grid form đã resolve |
| GET | `/applicants/{id}/ds260-validate` | Errors + warnings |
| GET | `/applicants/{id}/ds260-conflicts` | Conflict list |
| POST | `/applicants/{id}/conflicts/{id}/resolve` | User chọn giá trị |
| GET | `/applicants/{id}/tables` | Bảng Luồng 1 |
| GET | `/applicants/{id}/tables/reference` | Bảng đối chiếu + worksheet |
| GET | `/applicants/{id}/doc-records` | Tất cả ApplicantDocRecord |

#### Export
| Method | Path | Mô tả |
|--------|------|--------|
| POST | `/applicants/{id}/export-ds260` | Xuất Word DS-260 |
| POST | `/applicants/{id}/export` | Xuất form khác (DS-160, I-539) |
| GET | `/exports/{id}/download` | Tải file |

### 2.3. Services — luồng DS-260

```
documents.py upload
    → ocr_pipeline.py
        classify_document()
        extract_document()
        save_extracted_fields()
    → doc_record_sync.py
        sync_doc_record_from_document()
        finalize_applicant_after_ocr()
            → ds260_conflicts.sync_ds260_doc_conflicts()

profile.py GET ds260-form
    → ds260_mapping.resolve_ds260_form()
    → ds260_validate.validate_ds260()

export.py POST export-ds260
    → export_ds260.create_ds260_export()
        → fill_ds260_docx_template()
```

#### File service quan trọng

| File | Vai trò |
|------|---------|
| `document_registry.py` | 8 loại Luồng 1 + ds260_customer_form; parse filename; extract keys |
| `doc_record_sync.py` | OCR → `ApplicantDocRecord` |
| `ocr_pipeline.py` | OpenAI classify/extract; coerce ds260 worksheet |
| `ds260_mapping.py` | **Core:** `resolve_ds260_form()`, enrich, children union, priority |
| `ds260_field_allowed_docs.py` | `FIELD_ALLOWED_DOCS` per field |
| `ds260_conflicts.py` | document_vs_exception + document_vs_worksheet (12 field) |
| `ds260_customer_keys.py` | OCR key remap; context-gated `document_number` |
| `ds260_dates.py` | Full date + partial (`May 2023`, `2023`) |
| `ds260_validate.py` | Pre-export validation + warnings |
| `export_ds260.py` | Fill Word template `ds260_final` |
| `birth_location.py`, `postal_code.py` | Format địa danh VN |

#### Models (`entities.py`)

```python
Applicant          # Hồ sơ khách
Document           # File upload (status: uploaded/processing/done/failed)
ExtractedField     # OCR raw per document
ApplicantDocRecord # 1 row/file: doc_type, variant, form_data, raw_data
Conflict           # ds260.* field_key, value_a, value_b, status
Export             # Word output path
FormTemplate       # ds260_final.docx template
```

### 2.4. Config data

| File | Nội dung |
|------|----------|
| `ds260_mapping.json` | Section + field → document + OCR field + aliases |
| `standard_templates.json` | Schema OCR 8 loại giấy Luồng 1 |
| `location_to_country.json` | Map nơi sinh → quốc gia |
| `province_to_postal_code.json` | Mã bưu điện VN |

### 2.5. Tests DS-260

```
tests/test_ds260_field_allowed_docs.py
tests/test_ds260_enrich_whitelist.py
tests/test_ds260_fill_priority.py
tests/test_ds260_conflicts.py
tests/test_ds260_dates.py
tests/test_ds260_children.py
tests/test_ds260_customer_keys.py
tests/test_ds260_mapping.py (via các test trên)
... spouse, parents, marital, export context
```

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/ -k ds260 -q
```

---

## 3. FRONTEND

### 3.1. Cây thư mục chính

```
frontend/
├── src/
│   ├── app/                        # Next.js App Router
│   │   ├── page.tsx                # Landing
│   │   ├── login/page.tsx
│   │   ├── register/page.tsx
│   │   ├── dashboard/              # Admin dashboard
│   │   │   ├── page.tsx
│   │   │   ├── admin/, users/, search/, reports/, settings/, trash/
│   │   │   └── layout.tsx
│   │   └── applicants/
│   │       ├── layout.tsx
│   │       └── [id]/
│   │           ├── upload/page.tsx     # ★ Upload giấy tờ
│   │           └── review/page.tsx     # ★ Review DS-260
│   ├── components/
│   │   ├── layout/                 # AppHeader, AppSidebar, DashboardShell
│   │   ├── dashboard/              # KpiCard, charts
│   │   ├── AiChatPanel.tsx
│   │   └── StatusBadge.tsx
│   └── lib/
│       ├── api.ts                  # ★ HTTP client + types
│       ├── ds260Templates.ts
│       └── passportDs260Fields.ts
├── package.json
└── .env.local                      # NEXT_PUBLIC_API_URL
```

### 3.2. Trang ImmiPath / DS-260

#### `upload/page.tsx`
- Hướng dẫn tên file: `Passport.pdf`, `Passport_new.pdf`, `ds260.pdf`, …
- Upload batch → gọi `api.uploadDocuments()`
- Hiển thị trạng thái OCR (processing / done / failed)
- Reprocess document

#### `review/page.tsx` (trang chính DS-260)
- Load parallel:
  - `api.getDs260Form()` — grid ~130 field theo section
  - `api.validateDs260()` — errors/warnings (partial_date, children >3, …)
  - `api.getDs260Conflicts()` — 2 loại conflict
  - `api.getReferenceTables()` — bảng đối chiếu
- **Conflict panel:** chọn Luồng 1 vs _new hoặc official vs worksheet
- **Validate panel:** lỗi chặn export + warning
- **Export DS-260:** `api.exportDs260()` → tải Word

### 3.3. API client (`lib/api.ts`)

Hàm DS-260:

```typescript
api.getDs260Form(applicantId)
api.validateDs260(applicantId)
api.getDs260Conflicts(applicantId)
api.exportDs260(applicantId, skipValidation?, templateCode?)
api.getDs260Mapping()
api.resolveConflict(applicantId, conflictId, resolved_value)
api.getDocTables(applicantId)          // Luồng 1
api.getReferenceTables(applicantId)    // _new + worksheet
api.getDocRecords(applicantId)
api.reprocessDocument(applicantId, documentId)
```

Types chính:

```typescript
interface Ds260Form {
  sections: Ds260Section[];
  filled_count: number;
  documents: Record<string, DocRecordSummary>;
}

interface Ds260Field {
  key: string;
  label: string;
  value: string;
  source: { document_type, variant, derived?, ... };
}

interface Conflict {
  id: string;
  field_key: string;
  field_label?: string;
  conflict_type?: "document_vs_exception" | "document_vs_worksheet";
  value_a: string;
  value_b: string;
}

interface Ds260Validation {
  valid: boolean;
  errors: ValidationIssue[];
  warnings: ValidationIssue[];  // partial_date, passport_expiring_soon, ...
}
```

Auth: JWT trong `localStorage` → header `Authorization: Bearer …`

### 3.4. Dashboard (ngoài DS-260)

| Route | Chức năng |
|-------|-----------|
| `/dashboard` | KPI, biểu đồ hồ sơ |
| `/dashboard/admin` | Quản trị user, template |
| `/dashboard/search` | Tìm applicant |
| `/dashboard/reports` | Báo cáo executive |
| `/dashboard/trash` | Hồ sơ đã xóa |

---

## 4. Luồng end-to-end (code touchpoints)

```
1. UPLOAD
   FE: upload/page.tsx → api.uploadDocuments()
   BE: documents.py → ocr_pipeline → doc_record_sync

2. CONFLICT SYNC (auto sau OCR)
   BE: ds260_conflicts.sync_ds260_doc_conflicts()

3. REVIEW
   FE: review/page.tsx
   BE: profile.py → ds260_mapping.resolve_ds260_form()
                  → ds260_validate.validate_ds260()

4. RESOLVE CONFLICT
   FE: api.resolveConflict()
   BE: profile.py → lưu Conflict.resolved_value

5. EXPORT
   FE: api.exportDs260()
   BE: export.py → export_ds260.create_ds260_export()
                  → ds260_dates format
                  → python-docx fill template
```

---

## 5. Biến môi trường

### Backend (`backend/.env`)
```env
DATABASE_URL=sqlite+aiosqlite:///./immigration.db
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4.1
CORS_ORIGINS=http://localhost:3000
```

### Frontend (`frontend/.env.local`)
```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

## 6. Chạy dev

```powershell
# Terminal 1 — Backend
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000

# Terminal 2 — Frontend
cd frontend
npm run dev

# Hoặc một lệnh
cd "d:\app docs"
npm start
```

- Frontend: http://localhost:3000  
- API docs: http://localhost:8000/docs  
- Health: http://localhost:8000/health  

---

## 7. Tài liệu liên quan

| File | Nội dung |
|------|----------|
| `README.md` | Cài đặt nhanh |
| `DS260_IMPLEMENTATION_REVIEW.md` | Logic nghiệp vụ DS-260 chi tiết (gửi reviewer) |
| `CODE_OVERVIEW.md` | File này — map frontend/backend |

---

*Tổng hợp cấu trúc mã nguồn — không phải dump toàn bộ source code.*
