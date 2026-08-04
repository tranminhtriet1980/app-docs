# 📚 IMMIGRATION AI — COMPLETE SYSTEM GUIDE

**Project:** Immigration AI Form Filler — DS-260 (USCIS)  
**Last Updated:** 2026-08-04  
**Status:** Full Documentation

---

# 📋 TABLE OF CONTENTS

1. [Hệ Thống Tổng Quan](#hệ-thống-tổng-quan)
2. [Tạo Hồ Sơ (Create Applicant)](#tạo-hồ-sơ-create-applicant)
3. [OCR Pipeline](#ocr-pipeline)
4. [Extract Fields — Đầy Đủ](#extract-fields--đầy-đủ)
5. [Validation & Error Handling](#validation--error-handling)
6. [Database Schema](#database-schema)
7. [File References](#file-references)

---

# 🏗️ Hệ Thống Tổng Quan

## Kiến Trúc

```
┌─────────────────────────────────────┐
│ Frontend (Next.js)                  │
│ - Upload, Review, Export            │
└──────────────┬──────────────────────┘
               │ HTTP REST API
┌──────────────▼──────────────────────┐
│ Backend (FastAPI)                   │
│ - Auth, Upload, OCR, Export         │
└──────────────┬──────────────────────┘
               │ Async Database
┌──────────────▼──────────────────────┐
│ Database (SQLite/PostgreSQL)        │
│ - Users, Applicants, Documents      │
│ - ExtractedFields, Conflicts        │
└─────────────────────────────────────┘
```

## Quy Trình End-to-End

```
1. ĐĂNG NHẬP / ĐĂNG KÝ
2. TẠO HỒ SƠ (Applicant)
3. UPLOAD TÀI LIỆU (PDF/JPG)
4. OCR (Classify + Extract)
   ├─ OpenAI Vision API
   └─ Demo Mode (filename heuristic)
5. SYNC CONFLICTS (tự động)
6. REVIEW DS-260 FORM
7. RESOLVE CONFLICTS
8. EXPORT WORD
```

---

# 📝 Tạo Hồ Sơ (Create Applicant)

## Endpoint

```
POST /api/v1/applicants
Content-Type: application/json
Authorization: Bearer <JWT_TOKEN>
```

## Request Body — REQUIRED

```json
{
  "display_name": "Nguyễn Văn A"
}
```

## Request Body — OPTIONAL

```json
{
  "display_name": "Nguyễn Văn A",
  "notes": "Ghi chú thêm",
  "client_name": "Tên client",
  "project_name": "Tên dự án",
  "department": "Phòng ban",
  "case_type": "immigration",
  "tags": ["priority", "family"],
  "is_family_bundle": true,
  "members": [
    {"role": "principal", "display_name": "Nguyễn Văn A"},
    {"role": "spouse", "display_name": "Trần Thị B"},
    {"role": "child", "display_name": "Nguyễn Văn C"}
  ]
}
```

## Case Types

- `immigration` — Định cư Mỹ (mặc định)
- `study_abroad` — Du học
- `tourism` — Du lịch
- `other` — Khác

## Member Roles

- `principal` — Chủ hồ sơ (bắt buộc)
- `spouse` — Vợ/Chồng
- `child` — Con em
- `grandchild` — Cháu
- `sibling` — Anh/Chị/Em (F4)

## Backend Logic — 8 Steps

### Step 1: Kiểm Tra Authentication

```python
# JWT token hợp lệ?
if not token:
    raise HTTPException(401, "Not authenticated")
```

### Step 2: Kiểm Tra Quyền

```python
# user.is_active == True?
# user.can_create_applicants == True?
if not can_create_applicant(user):
    raise HTTPException(403, "Bạn không có quyền tạo hồ sơ")
```

### Step 3: Kiểm Tra Quota

```python
# Số hồ sơ tháng này < limit (mặc định 50)?
await check_applicant_quota(db, user)
# Nếu >= limit → 403 Forbidden
```

### Step 4: Kiểm Tra Trùng Hồ Sơ

```python
# Cùng user_id + cùng năm + cùng tên (normalized)?
duplicate = await _find_duplicate_applicant(
    db, user_id=user.id, display_name=body.display_name, year=2026
)
if duplicate:
    raise HTTPException(409, "Hồ sơ trùng")
```

**Normalization Logic:**
- Convert to UPPERCASE
- Gộp khoảng trắng
- Bỏ qua soft-deleted hồ sơ

### Step 5: Tạo Applicant Record

```python
applicant = Applicant(
    user_id=user.id,
    display_name=body.display_name,
    status=ApplicantStatus.draft,
    case_type=body.case_type.value,
    notes=body.notes,
    client_name=body.client_name,
    project_name=body.project_name,
    department=body.department,
    tags=dump_tags(body.tags),
    is_family_bundle=bool(body.is_family_bundle),
)
db.add(applicant)
await db.flush()  # Lấy applicant.id
```

### Step 6: Tạo Family Members (nếu là_family_bundle)

```python
if body.is_family_bundle and body.members:
    await create_case_members(db, applicant.id, body.members)
elif body.is_family_bundle:
    # Auto-create principal từ display_name
    await create_case_members(
        db, applicant.id,
        [{"role": "principal", "display_name": body.display_name}]
    )
```

### Step 7: Log Audit Trail

```python
await log_audit(
    db, user=user,
    action="applicant.create",
    entity_type="applicant",
    entity_id=applicant.id,
    payload={"name": body.display_name, "family": body.is_family_bundle}
)
```

### Step 8: Commit + Return

```python
await db.commit()
await db.refresh(applicant)
return await _applicant_out(db, applicant)
```

## Response (201 Created)

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
  "display_name": "Nguyễn Văn A",
  "status": "draft",
  "case_type": "immigration",
  "is_family_bundle": true,
  "notes": null,
  "client_name": null,
  "project_name": null,
  "department": null,
  "tags": [],
  "doc_count": 0,
  "conflict_count": 0,
  "created_at": "2026-08-04T10:30:45.123456+00:00",
  "updated_at": "2026-08-04T10:30:45.123456+00:00",
  "members": [
    {
      "id": "uuid-1",
      "role": "principal",
      "display_name": "Nguyễn Văn A",
      "sort_order": 0,
      "member_number": "01"
    },
    {
      "id": "uuid-2",
      "role": "spouse",
      "display_name": "Trần Thị B",
      "sort_order": 1,
      "member_number": "02"
    }
  ]
}
```

## Errors

### 401 — Not Authenticated

```json
{"detail": "Not authenticated"}
```

### 403 — Forbidden (Quyền)

```json
{"detail": "Bạn không có quyền tạo hồ sơ."}
```

### 403 — Quota Exceeded

```json
{"detail": "Đã đạt giới hạn 50 hồ sơ/tháng. Liên hệ admin để tăng quota."}
```

### 409 — Conflict (Trùng)

```json
{"detail": "Hồ sơ trùng: đã tồn tại hồ sơ \"Nguyễn Văn A\" do bạn phụ trách trong năm 2026."}
```

### 400 — Bad Request

```json
{"detail": [{"type": "string_too_short", "loc": ["body", "display_name"], "msg": "..."}]}
```

## Database Tables

### users

| Column | Type | Mô Tả |
|--------|------|--------|
| id | UUID | Primary Key |
| email | VARCHAR | Email duy nhất |
| hashed_password | VARCHAR | Mật khẩu hash |
| full_name | VARCHAR | Tên đầy đủ |
| role | ENUM | user \| staff \| admin |
| is_active | BOOLEAN | Tài khoản hoạt động? |
| can_create_applicants | BOOLEAN | Quyền tạo hồ sơ? |
| max_applicants_per_month | INT | Giới hạn/tháng (default 50) |
| totp_secret | VARCHAR | 2FA secret |
| totp_enabled | BOOLEAN | 2FA bật? |
| created_at | TIMESTAMP | Ngày tạo |

### applicants

| Column | Type | Mô Tả |
|--------|------|--------|
| id | UUID | Primary Key |
| user_id | UUID | FK users.id (người tạo) |
| display_name | VARCHAR | Tên hồ sơ (REQUIRED, 1-255) |
| status | ENUM | draft \| processing \| review \| ready_for_export \| exported |
| notes | TEXT | Ghi chú |
| client_name | VARCHAR | Tên client |
| project_name | VARCHAR | Tên dự án |
| department | VARCHAR | Phòng ban |
| case_type | VARCHAR | immigration \| study_abroad \| tourism \| other |
| is_family_bundle | BOOLEAN | Gia đình? |
| tags | TEXT | JSON array ["tag1", "tag2"] |
| assigned_staff_id | UUID | FK users.id (nhân viên phụ trách) |
| deleted_at | TIMESTAMP | Soft delete |
| created_at | TIMESTAMP | Auto |
| updated_at | TIMESTAMP | Auto |

### case_members

| Column | Type | Mô Tả |
|--------|------|--------|
| id | UUID | Primary Key |
| applicant_id | UUID | FK applicants.id |
| role | VARCHAR | principal \| spouse \| child \| grandchild \| sibling |
| display_name | VARCHAR | Tên thành viên |
| sort_order | INT | Thứ tự (0=principal, 1=spouse, 2+child) |
| created_at | TIMESTAMP | Auto |

---

# 🔍 OCR Pipeline

## Flow Tổng Quan

```
Upload File (Passport.pdf, 2MB)
    ↓
STEP 1: RESOLVE IMAGES
    PDF → JPEG (3 trang, 180 DPI, max 2600px)
    DOCX/XLSX/TXT → Extract text
    PNG/JPG → Dùng trực tiếp
    ↓
[image_paths, hint]
hint = "pdf_pages" | "pdf_text_only" | "direct_image" | "filename_only"
    ↓
STEP 2: CLASSIFY
    OpenAI Mode:
      Vision API nhìn ảnh + AI classification prompt
      → {"document_type": "passport", "confidence": 0.95}
    Demo Mode:
      Tìm keyword trong filename
      → {"document_type": "passport", "confidence": 0.85}
    ↓
STEP 3: EXTRACT
    OpenAI Mode:
      Type-specific extraction prompt
      Vision API đọc ảnh
      Filter to schema
      Enrich from filename nếu null
      → {"fields": {...}}
    Demo Mode:
      Parse tên từ filename
      Generate mock values
      → {"fields": {...}, "confidence": 0.5}
    ↓
STEP 4: FILTER TO SCHEMA
    Chỉ giữ field belong to doc_type
    Loại bỏ field trùng tên, LLM bịa
    ↓
STEP 5: ENRICH FROM FILENAME
    Nếu null → lấy từ filename
    confidence = 0.35 (thấp hơn OCR)
    ↓
STEP 6: SAVE TO DATABASE
    ExtractedField (OCR raw)
    ApplicantDocRecord (summary)
    Trigger Conflict Sync
    ↓
✅ Status = extracted
```

## Classification

### OpenAI Mode

**Prompt Template:**

```
Bạn là hệ thống phân loại hồ sơ DS260 / định cư Mỹ.

Bước 1: Xác định loại tài liệu từ nội dung (ảnh/PDF). Các loại chuẩn:
- passport
- judicial_certificate
- divorce
- birth_certificate
- death_certificate
- marriage_certificate
- birth_certificate_child
- military_discharge

Các loại khác: visa, i20, i94, diploma_transcript, financial, employment_letter,
address_document, ds260_customer_form, photo, other

ds260_customer_form = bản DS-260 khách tự khai (worksheet). 
Chọn loại này cho MỌI worksheet khách tự khai — KHÔNG hạ xuống "other".

Trả về ONLY valid JSON:
{"document_type": "<code>", "confidence": 0.0-1.0, "reason": "brief"}
```

**Example Output:**

```json
{
  "document_type": "passport",
  "confidence": 0.95,
  "reason": "Passport data page with personal information visible"
}
```

### Demo Mode

**Heuristic Rules:**

```python
rules = [
    ("passport", "passport"),
    ("visa", "visa"),
    ("i-20", "i20"),
    ("i-94", "i94"),
    ("birth", "birth_certificate"),
    ("marriage", "marriage_certificate"),
    ("divorce", "divorce"),
    ("judicial", "judicial_certificate"),
    ("death", "death_certificate"),
    ("military", "military_discharge"),
    ("transcript", "diploma_transcript"),
    ("diploma", "diploma_transcript"),
    ("employment", "employment_letter"),
    ("financial", "financial"),
    ("address", "address_document"),
    ("utility", "address_document"),
    ("lease", "address_document"),
    ("residence", "address_document"),
    ("ds260", "ds260_customer_form"),
    ("photo", "photo"),
]
```

**Logic:**
- Find token in filename (case-insensitive)
- Match → return doc_type + confidence=0.75
- No match → confidence=0.5 + "unknown"

**Example:**
- `Passport.pdf` → `{"document_type": "passport", "confidence": 0.85}`
- `MyDocument.pdf` → `{"document_type": "other", "confidence": 0.5}`

## Extraction

### OpenAI Mode

**Process:**

```python
async def _openai_extract(file_path, doc_type, filename, db, ctx):
    # 1. Get expected keys for doc_type
    expected_keys = get_extract_keys_for_doc_type(doc_type)
    
    # 2. Get type-specific extraction hint
    extra = DOC_TYPE_EXTRACT_HINTS.get(doc_type, "")
    
    # 3. Check if exception variant
    _, is_exception = parse_document_filename(filename)
    
    # 4. Build extraction prompt
    prompt = EXTRACTION_PROMPT_TEMPLATE.format(
        doc_type=doc_type,
        expected_keys=",\n".join(expected_keys)
    )
    
    # 5. Call Vision API
    response = await chat_completion(...)
    extraction = _parse_json_response(response.choices[0].message.content)
    
    # 6. Coerce (remap field names)
    extraction = _coerce_birth_certificate_extraction(extraction)
    
    # 7. Filter to schema
    extraction = _filter_extraction_to_schema(doc_type, extraction)
    
    # 8. Enrich from filename
    extraction = _fallback_enrich_extraction(doc_type, filename, extraction)
    
    return extraction
```

**Prompt Template:**

```
Bạn trích xuất dữ liệu có cấu trúc cho form DS260.

Loại tài liệu đã xác định: {doc_type}

CHỈ trích xuất các field thuộc loại tài liệu này — KHÔNG gộp field trùng tên.
Ví dụ passport có full_name; birth_certificate cũng có full_name — chỉ trích field của {doc_type}.

Trả về ONLY valid JSON:
{
  "document_type": "{doc_type}",
  "fields": {
    "<field_key>": {"value": "<string or null>", "confidence": 0.0-1.0, "source_page": "page_1"}
  }
}

Quy tắc:
- ISO dates YYYY-MM-DD khi có thể
- UPPERCASE cho tên như in trên giấy
- null chỉ khi thật sự không đọc được
- CHỈ dùng các key sau (không thêm key ngoài schema):
{expected_keys}
```

### Demo Mode

**Logic:**

```python
def _mock_extraction(doc_type, filename):
    keys = get_extract_keys_for_doc_type(doc_type)
    person = _person_name_from_filename(filename)
    fields = {}
    
    for key in keys:
        if key in {"family_name", "surname"}:
            val = person["family_name"] or "NGUYEN"
        elif key in {"given_names", "given_name"}:
            val = person["given_names"] or "VAN A"
        elif key == "date_of_birth":
            val = "1990-01-15"
        elif key == "passport_number":
            val = "B1234567"
        elif key == "gender":
            val = "MALE"
        else:
            val = f"[demo — {doc_type}]"
        
        fields[key] = {
            "value": val,
            "confidence": 0.5,
            "source_page": "demo"
        }
    
    return {"document_type": doc_type, "fields": fields}
```

**Filename Parsing:**

```python
def _person_name_from_filename(filename):
    """Extract uppercase person name hints from filename."""
    stem = Path(filename).stem
    # Replace separators with space
    text = re.sub(r"[_\-]+", " ", stem)
    # Remove parentheses
    text = re.sub(r"[()]+", " ", text)
    # Normalize spaces
    text = re.sub(r"\s+", " ", text).strip()
    
    # If "A & B", take first
    if "&" in text:
        text = text.split("&", 1)[0].strip()
    
    # Remove stop words
    stop_words = {"PASSPORT", "PHOTO", "BIRTH", "CERTIFICATE", "JUDICIAL", ...}
    parts = [p for p in text.upper().split(" ") if p and p not in stop_words and not p.isdigit()]
    
    # Return parsed names
    if not parts:
        return {"full_name": "", "family_name": "", "given_names": ""}
    
    full_name = " ".join(parts)
    family_name = parts[0]
    given_names = " ".join(parts[1:]) if len(parts) > 1 else ""
    
    return {
        "full_name": full_name,
        "family_name": family_name,
        "given_names": given_names,
    }
```

**Example:**
- `Passport_Nguyen_Van_A_new.pdf`
  → family_name = "NGUYEN"
  → given_names = "VAN A"
  → full_name = "NGUYEN VAN A"
  → date_of_birth = "1990-01-15" (mock)
  → confidence = 0.5

## Confidence Levels

### OpenAI Mode

| Scenario | Confidence |
|----------|------------|
| Clear document, all fields visible | 0.9 - 1.0 |
| Handwritten, some unclear | 0.7 - 0.9 |
| Partial page, missing some fields | 0.5 - 0.7 |
| Text extracted fallback | 0.4 - 0.6 |
| Enriched from filename | 0.3 - 0.5 |

### Demo Mode

| Source | Confidence |
|--------|------------|
| Filename registry match | 0.85 |
| Filename heuristic | 0.75 |
| Default value | 0.5 |
| Unknown type | 0.5 |

## PDF Rendering

**Settings:**

```python
_MAX_RENDER_PX = 2600  # Max pixel dimension
_RENDER_JPEG_QUALITY = 85  # JPEG quality (1-95)
_TILE_OVERLAP_X = 0.18  # Horizontal overlap (18%)
_TILE_OVERLAP_Y = 0.08  # Vertical overlap (8%)
```

**Logic:**

```python
def _pdf_pages_to_images(path, max_pages=3, dpi=180):
    """Render PDF pages to JPEG for Vision API."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(path))
        for i in range(min(len(doc), max_pages)):
            page = doc[i]
            zoom = dpi / 72.0
            longest = max(page.rect.width, page.rect.height) * zoom
            
            # Cap cạnh dài ≤ 2600px (tránh 502 Bad Gateway)
            if longest > _MAX_RENDER_PX:
                zoom *= _MAX_RENDER_PX / longest
            
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            out = path.parent / f"{path.stem}_page{i+1}.jpg"
            out.write_bytes(pix.tobytes(output="jpg", jpg_quality=85))
            images.append(out)
    except:
        # Fallback to pdf2image or text extraction
        pass
    
    return images
```

## Special Cases

### Handwritten Documents (Chữ Viết Tay)

**Problem:** Vision API khó đọc chữ viết tay

**Solution:** Cắt thành tiles (overlap)

```python
def _split_image_into_tiles(path, rows, cols):
    """Cắt ảnh thành rows x cols tiles, overlap 18% ngang + 8% dọc."""
    # Ví dụ: DS-260 worksheet 20 trang
    # → Cắt 4 rows x 1 col = 80 tiles
    # Mỗi tile gửi riêng → tránh vượt trần tokens-per-minute
```

### Multi-Page Long Form

**Problem:** DS-260 worksheet ~60k characters, vượt trần Vision API

**Solution:** Chia batch

```python
def _split_images_into_batches(image_paths, max_per_batch=4):
    """Chia ảnh thành batch để mỗi request < trần tokens."""
    # Prod incident 30/07/2026: worksheet 20 trang cắt 4x1 → 80 ảnh
    # ≈ 116k token, vượt trần 30k → request hỏng vĩnh viễn
    # Solution: chia nhỏ, batch 4 ảnh/request
    
    batches = []
    for start in range(0, len(image_paths), max_per_batch):
        stop = start + max_per_batch
        batches.append({
            "images": image_paths[start:stop],
            "batch_position": (len(batches) + 1, math.ceil(len(image_paths) / max_per_batch))
        })
    return batches
```

**LLM Instruction:**

```
IMPORTANT: this is PART 1 of 3 of the document —
you are seeing only some of its pages. Extract only what is VISIBLE in
these images. Leave every other field empty; do NOT guess or infer
fields whose page is not shown here.
```

### Merge Batch Results

```python
def _merge_batch_results(results):
    """Gộp kết quả nhiều lô: giá trị khác rỗng đầu tiên thắng."""
    if not results or len(results) == 1:
        return results[0] if results else {}
    
    merged = {}
    for result in results:
        if not isinstance(result, dict):
            continue
        for key, value in result.items():
            # Chỉ ghi đè nếu merged[key] empty
            if key not in merged or _is_blank_for_merge(merged[key]):
                merged[key] = value
    return merged
```

---

# 📊 Extract Fields — Đầy Đủ

## 1. PASSPORT (Hộ Chiếu)

**Form Section:** DS-260 Mục A — Passport (Personal + Travel Document)

**Extract Keys (12 fields):**

```
full_name, family_name, given_names
date_of_birth, place_of_birth, birth_city, birth_state, birth_country
gender, nationality, id_card_number
passport_type, country_code, passport_number
issue_date, expiration_date, expiry_date
place_of_issue, issuing_country, issuing_authority
```

**Example Output:**

```json
{
  "full_name": {"value": "NGUYEN VAN A", "confidence": 0.95, "source_page": "page_1"},
  "family_name": {"value": "NGUYEN", "confidence": 0.96, "source_page": "page_1"},
  "given_names": {"value": "VAN A", "confidence": 0.95, "source_page": "page_1"},
  "date_of_birth": {"value": "1990-01-15", "confidence": 0.92, "source_page": "page_1"},
  "place_of_birth": {"value": "HA NOI, VIETNAM", "confidence": 0.90, "source_page": "page_1"},
  "birth_city": {"value": "HA NOI", "confidence": 0.90, "source_page": "page_1"},
  "birth_country": {"value": "VIETNAM", "confidence": 0.95, "source_page": "page_1"},
  "gender": {"value": "MALE", "confidence": 0.93, "source_page": "page_1"},
  "nationality": {"value": "VIETNAM", "confidence": 0.97, "source_page": "page_1"},
  "id_card_number": {"value": "0123456789", "confidence": 0.88, "source_page": "page_1"},
  "passport_type": {"value": "P", "confidence": 0.99, "source_page": "page_1"},
  "country_code": {"value": "VNM", "confidence": 0.99, "source_page": "page_1"},
  "passport_number": {"value": "B1234567", "confidence": 0.94, "source_page": "page_1"},
  "issue_date": {"value": "2018-03-20", "confidence": 0.91, "source_page": "page_1"},
  "expiry_date": {"value": "2028-03-20", "confidence": 0.91, "source_page": "page_1"},
  "issuing_country": {"value": "VIETNAM", "confidence": 0.95, "source_page": "page_1"}
}
```

---

## 2. JUDICIAL CERTIFICATE (Lý Lịch Tư Pháp)

**Form Section:** DS-160 — Lý lịch tư pháp

**Extract Keys (8 fields):**

```
full_name, date_of_birth, nationality
father_name, mother_name
document_number, issue_date, document_type
```

**Example:**

```json
{
  "full_name": {"value": "NGUYEN VAN A", "confidence": 0.94},
  "date_of_birth": {"value": "1990-01-15", "confidence": 0.92},
  "nationality": {"value": "VIETNAM", "confidence": 0.96},
  "father_name": {"value": "NGUYEN VAN B", "confidence": 0.90},
  "mother_name": {"value": "TRAN THI C", "confidence": 0.88},
  "document_number": {"value": "123456789", "confidence": 0.95},
  "issue_date": {"value": "2024-01-15", "confidence": 0.93},
  "document_type": {"value": "JUDICIAL CERTIFICATE", "confidence": 0.97}
}
```

---

## 3. DIVORCE DECREE (Quyết Định Ly Hôn)

**Form Section:** DS-160 / DS-260 — Ly hôn

**Extract Keys (8 fields):**

```
husband_full_name, wife_full_name
husband_date_of_birth, wife_date_of_birth
spouse_name, plaintiff_name, defendant_name
marriage_date, divorce_date
document_number, document_type
```

**Example:**

```json
{
  "husband_full_name": {"value": "NGUYEN VAN A", "confidence": 0.92},
  "wife_full_name": {"value": "TRAN THI B", "confidence": 0.91},
  "husband_date_of_birth": {"value": "1990-01-15", "confidence": 0.89},
  "wife_date_of_birth": {"value": "1992-06-20", "confidence": 0.88},
  "marriage_date": {"value": "2015-10-10", "confidence": 0.93},
  "divorce_date": {"value": "2023-05-15", "confidence": 0.94},
  "document_number": {"value": "2023/QĐST", "confidence": 0.95}
}
```

---

## 4. BIRTH CERTIFICATE — APPLICANT (Giấy Khai Sinh Chủ Hồ Sơ)

**Form Section:** DS-160 — Giấy khai sinh (chủ hồ sơ)

**Extract Keys (~30 fields):**

```
APPLICANT:
full_name, date_of_birth, place_of_birth, gender
registration_number

FATHER:
father_name, father_surname, father_given_names
father_date_of_birth, father_dob, father_year_of_birth
father_birth_city, father_place_of_birth
father_birth_state, father_birth_country
father_address, father_residence

MOTHER:
mother_name, mother_surname, mother_given_names
mother_date_of_birth, mother_dob, mother_year_of_birth
mother_birth_city, mother_city
mother_place_of_birth, mother_address, mother_residence
mother_birth_country, mother_country, mother_nationality
mother_birth_state
```

**Example:**

```json
{
  "full_name": {"value": "NGUYEN VAN A", "confidence": 0.96},
  "date_of_birth": {"value": "1990-01-15", "confidence": 0.94},
  "place_of_birth": {"value": "HA NOI, VIETNAM", "confidence": 0.92},
  "gender": {"value": "MALE", "confidence": 0.98},
  "father_name": {"value": "NGUYEN VAN B", "confidence": 0.93},
  "father_date_of_birth": {"value": "1965", "confidence": 0.70},
  "father_birth_city": {"value": "QUANG BINH", "confidence": 0.88},
  "father_birth_country": {"value": "VIETNAM", "confidence": 0.96},
  "mother_name": {"value": "TRAN THI C", "confidence": 0.92},
  "mother_date_of_birth": {"value": "1968-05-20", "confidence": 0.91},
  "mother_birth_city": {"value": "HA NOI", "confidence": 0.95},
  "mother_birth_country": {"value": "VIETNAM", "confidence": 0.97},
  "registration_number": {"value": "1234567890", "confidence": 0.94}
}
```

---

## 5. DEATH CERTIFICATE (Giấy Báo Tử)

**Form Section:** DS-260 — Giấy báo tử

**Extract Keys (5 fields):**

```
deceased_full_name, date_of_death
place_of_death, relationship_to_applicant
document_number
```

**Example:**

```json
{
  "deceased_full_name": {"value": "NGUYEN VAN B", "confidence": 0.95},
  "date_of_death": {"value": "2020-05-15", "confidence": 0.93},
  "place_of_death": {"value": "HA NOI", "confidence": 0.88},
  "relationship_to_applicant": {"value": "FATHER", "confidence": 0.90},
  "document_number": {"value": "2020/BT", "confidence": 0.94}
}
```

---

## 6. MARRIAGE CERTIFICATE (Giấy Kết Hôn)

**Form Section:** DS-160 / DS-260 — Giấy kết hôn

**Extract Keys (~20 fields):**

```
HUSBAND:
husband_full_name, husband_surname, husband_given_names
husband_date_of_birth
husband_birth_city, husband_birth_state, husband_birth_country
husband_address, husband_occupation

WIFE:
wife_full_name, wife_surname, wife_given_names
wife_date_of_birth
wife_birth_city, wife_birth_state, wife_birth_country
wife_address, wife_occupation

MARRIAGE:
marriage_date, marriage_place, marriage_city
marriage_state, marriage_country
spouse_name, spouse_full_name, spouse_date_of_birth
document_number, registration_number
```

---

## 7. BIRTH CERTIFICATE — CHILD (Giấy Khai Sinh Con)

**Form Section:** DS-260 — 5. THÔNG TIN CỦA CON CÁI

**Extract Keys (~10 fields):**

```
CHILD:
child_full_name, child_date_of_birth
child_place_of_birth
child_birth_city, child_birth_state, child_birth_country
child_gender, registration_number

PARENTS:
father_name, mother_name
```

---

## 8. MILITARY DISCHARGE (Giấy Xuất Ngũ / NVQS)

**Form Section:** DS-160 — Nghĩa vụ quân sự

**Extract Keys (8 fields):**

```
full_name
military_country, military_branch
military_rank, military_specialty
service_from_date, service_to_date
document_number
```

---

## 9. DS-260 WORKSHEET (Khách Tự Khai — FULL FORM) ⭐⭐⭐

**Form Section:** DS-260 toàn bộ worksheet khách khai (7 section)

**Extract Keys (~150+ fields):**

```
SECTION 1 — PERSONAL INFORMATION (THÔNG TIN CÁ NHÂN):
applicant_name, applicant_name_native
other_name_used, other_names
gender, current_marital_status
date_of_birth, birth_city, birth_state, birth_country
nationality, id_card_number

SECTION 2 — PASSPORT (HỘ CHIẾU):
passport_number, passport_type, country_code
passport_issue_date, passport_expiration_date
passport_place_of_issue, passport_issuing_country
other_nationality_used, other_nationality_history

SECTION 3 — ADDRESS & RESIDENCE HISTORY (ĐỊA CHỈ & LỊCH SỬ CƯ TRÚ):
current_address, address_city, address_state
postal_code, address_country, address_from_date
other_addresses_since_16 (Yes/No)
other_addresses_history

SECTION 4 — CONTACT INFORMATION (THÔNG TIN LIÊN LẠC):
primary_phone_number, secondary_phone_number, work_phone_number
other_phones_used (Yes/No), other_phones_history
email_address
other_emails_used (Yes/No), other_emails_history

SECTION 5 — SOCIAL MEDIA (MẠNG XÃ HỘI):
social_media_platform, social_media_identifier
other_social_media_used (Yes/No), other_social_history

SECTION 6 — FAMILY INFORMATION (ĐỨC CHA/MẸ/PHỐI NGẪU/CON):
father_surname, father_given_names, father_date_of_birth, ...
mother_surname, mother_given_names, mother_date_of_birth, ...
spouse_surname, spouse_given_names, spouse_full_name, ...
previous_spouses_used, previous_spouse_full_name, ...
children_used, children_count, child_1_full_name, child_2_full_name, ...

SECTION D — WORK / EDUCATION / TRAINING (CÔNG VIỆC / HỌC VẤN):
work_primary_occupation, work_present_employer, work_job_title, work_start_date
work_prior_jobs_history (10-year narrative)
edu_middle_school_name, edu_high_school_name, edu_college_name
edu_middle_school_period, edu_high_school_period, edu_college_period, edu_college_major

SECTION C — HISTORY OF TRAVEL TO US (LỊCH SỬ ĐẾN MỸ):
been_in_us (Yes/No), issued_us_visa (Yes/No), refused_us_visa (Yes/No)
us_travel_history, us_visa_history

SECTION E.2 — ADDITIONAL INFORMATION (THÔNG TIN KHÁC):
other_languages_used, other_languages_list
traveled_countries_5yr_used, traveled_countries_history

SECTION F — SECURITY & BACKGROUND (AN NINH & LÝ LỊCH):
has_contagious_disease, has_vaccination_docs, drug_use, criminal_record
human_trafficking, money_laundering, terrorism, deportation (all Yes/No)

SECTION G — SOCIAL SECURITY NUMBER (SỐ AN SINH XÃ HỘI):
applied_ssn_before, want_ssn_issued, authorize_ssn_disclosure
ssn_number (nếu có)
```

**Complexity:** ⭐⭐⭐⭐⭐ VERY HIGH (150+ fields, 20 trang, handwritten)
**OCR Time:** 30-60 giây
**Confidence:** 0.5-0.8 (thấp vì chữ tay)

---

## 10. VISA (Visa — Thị Thực Mỹ)

**Extract Keys:**

```
visa_type (e.g., B-1/B-2, F-1, H-1B)
visa_number, visa_issue_date, visa_expiration_date
visa_issuing_country, visa_stamps
entry_dates, exit_dates, port_of_entry
```

---

## 11. I-20 (F-1 Student Visa Document)

**Extract Keys:**

```
STUDENT:
student_full_name, student_date_of_birth
student_id_number, passport_number

SCHOOL:
school_name, school_code, school_address, school_country

PROGRAM:
program_level (Bachelor, Master, PhD)
program_field, program_name
program_start_date, program_end_date
start_class_date, completion_date

FINANCIAL:
financial_backing (amount, sponsor name)
```

---

## 12. I-94 (Arrival/Departure Record)

**Extract Keys:**

```
TRAVELER:
full_name, date_of_birth
passport_number, country_of_citizenship

TRAVEL:
arrival_date, departure_date
port_of_entry (airport/border)
country_of_residence
i94_number, admitted_until_date
visa_class (B-1, F-1, H-1B, etc.)
```

---

## 13. DIPLOMA / TRANSCRIPT (Bằng Cấp / Phiếu Điểm)

**Extract Keys:**

```
STUDENT:
student_full_name, student_id_number
date_of_graduation, graduation_year, graduation_date

SCHOOL:
school_name, school_address, school_location
school_phone, school_website

PROGRAM:
program_level (Associate, Bachelor, Master, PhD)
program_name, program_field, major, minor
start_date, end_date, graduation_date

GRADES:
gpa, total_credits, credit_system (GPA 4.0, etc.)
degree_awarded, honors (Cum Laude, etc.)
```

---

## 14. FINANCIAL DOCUMENT (Giấy Tờ Tài Chính — Bank Statement, Savings, ...)

**Extract Keys:**

```
ACCOUNT HOLDER:
account_holder_name, account_number, account_type
taxpayer_id, ssn (if shown)

BANK INFO:
bank_name, bank_address, bank_phone
bank_routing_number, swift_code

BALANCE:
current_balance, balance_date, currency
transaction_period_from, transaction_period_to

TRANSACTIONS:
deposits (total, count)
withdrawals (total, count)
average_balance
```

---

## 15. EMPLOYMENT LETTER (Thư Xác Nhận Công Việc Hiện Tại)

**Extract Keys:**

```
EMPLOYEE:
employee_full_name, employee_id, employee_title
employee_phone, employee_email
employment_start_date, employment_end_date (nếu đã rời)

EMPLOYER:
employer_name, employer_type (corporation, nonprofit, government)
employer_address, employer_phone
employer_website, employer_tax_id

POSITION:
job_title, position_description
department, supervisor_name
employment_status (Full-time, Part-time, Contract, Temporary)

COMPENSATION:
salary_amount, salary_currency, salary_frequency (annual, monthly)
benefits_offered (health insurance, retirement, etc.)

LETTER:
letter_date, letter_signature
letter_on_company_letterhead (Yes/No)
authorized_signatory_name, authorized_signatory_title
```

---

## 16. ADDRESS DOCUMENT (Chứng Minh Cư Trú — Hoá Đơn, Hợp Thuê Nhà, ...)

**Extract Keys:**

```
ADDRESS:
current_address, address_line1, address_line2
city, state, postal_code, country

DATES:
document_date, issued_date
address_from_date, address_to_date
utility_bill_date, service_period
lease_start_date, lease_end_date

PROVIDER / LANDLORD:
utility_provider_name (Vietnam Electricity, Water, Gas, etc.)
landlord_name, landlord_phone, landlord_email
property_address, property_owner

UTILITY / BILL INFO:
account_number, meter_number
bill_amount, currency
service_type (Electricity, Water, Gas, Phone, Internet, etc.)
payment_status (Paid, Overdue, etc.)

CONTACT:
primary_phone_number, email_address
secondary_phone_number
```

---

## 17. APPLICATION FORM (DS-260 D — Work/Education/Training)

**Extract Keys (~30 fields):**

```
WORK (CÔNG VIỆC):
primary_occupation (nghề chính, e.g., Engineer, Teacher, Manager)
occupation_other_specify (ngành nghề chi tiết)
present_employer, employer_name
employer_address, employer_city
employer_state, employer_postal_code, employer_country
job_title, employment_start_date, start_date
other_occupation_used (Yes/No)
other_occupation_detail
prior_jobs_10_years_used (Yes/No)
prior_jobs_history (narrative of last 10 years)
```

---

## 18. PHOTO (Ảnh Hộ Chiếu)

**Extract Keys:**

```
photo_date (taken date)
photo_quality (standard, professional)
background_color (white, blue, etc.)
photo_dimensions, photo_format

METADATA:
photographer_name, photo_location
```

---

## 19. OTHER (Tài Liệu Khác Không Phân Loại)

**Extract Keys:**

```
[Generic fields — ít được dùng]
full_name, date_of_birth
document_number, document_date
document_title, document_type
organization_name, organization_phone

NOTES:
content_summary (một vài dòng mô tả)
extracted_text (toàn bộ text đọc được từ tài liệu)
```

---

# ✅ Validation & Error Handling

## File Upload Validation

- Max file size: 50MB
- Allowed MIME types: PDF, PNG, JPG, WEBP, GIF, DOCX, TXT
- Filename max length: 512 characters
- File hash: SHA256 calculated

## Extraction Validation

- Filter to schema: Chỉ giữ allowed keys
- Enrich from filename: Confidence 0.35
- Date validation: ISO format YYYY-MM-DD or partial

---

# 🗄️ Database Schema

- **users** — User accounts with role-based access
- **applicants** — Hồ sơ (status: draft → processing → review → ready_for_export → exported)
- **case_members** — Family members (principal, spouse, child, ...)
- **documents** — Uploaded files
- **extracted_fields** — OCR extracted data
- **applicant_doc_records** — Document summary per applicant
- **conflicts** — Data conflicts needing resolution
- **exports** — Generated Word documents

---

# 📁 File References

**Key Backend Files:**
- `backend/app/api/applicants.py` — Create/Update/Delete Applicant
- `backend/app/services/ocr_pipeline.py` — Classification + Extraction
- `backend/app/services/document_registry.py` — Document type definitions
- `backend/app/services/ds260_mapping.py` — Form merge logic

**Key Frontend Files:**
- `frontend/src/app/dashboard/page.tsx` — Create Applicant form
- `frontend/src/app/applicants/[id]/upload/page.tsx` — Upload Documents
- `frontend/src/app/applicants/[id]/review/page.tsx` — Review DS-260 Form

---

# 🔧 Configuration

**Backend (.env):**
- DATABASE_URL (SQLite/PostgreSQL)
- OPENAI_API_KEY (for Vision OCR)
- OPENAI_MODEL (gpt-4-vision)
- CORS_ORIGINS

**Frontend (.env.local):**
- NEXT_PUBLIC_API_URL

---

# 📊 Summary

| Metric | Value |
|--------|-------|
| Document Types | 19 (8 standard + 11 supplemental) |
| Extract Fields | 200+ total |
| Largest Form | DS-260 Worksheet (~150 fields) |
| OCR Confidence | 0.5-1.0 (OpenAI), 0.5-0.85 (Demo) |
| Max File Size | 50MB |
| Supported Formats | PDF, PNG, JPG, WEBP, DOCX, XLSX, TXT |

---

END OF GUIDE
