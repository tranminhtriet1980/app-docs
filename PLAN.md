# Plan: Cải thiện logic marital status và spouse information

## Status: ✅ COMPLETED

## Context

Yêu cầu:
1. **Marital status**: Khi có cả `married certificate` VÀ `divorce`, so sánh ngày kết hôn với ngày ly hôn. Nếu ngày kết hôn gần hơn (sau) ngày ly hôn → Married.
2. **Previous Spouse**: Nếu tái hôn cùng người đã ly hôn, vẫn hiển thị đầy đủ cả "Spouse Information" VÀ "Previous Spouse".
3. **Spouse occupation**: Compare dữ liệu giữa DS-260 của spouse applicant với dữ liệu trong family case.

## File modified

- `backend/app/services/ds260_mapping.py`
- `backend/app/services/ds260_conflicts.py`

## Implementation (Completed)

### 1. ✅ `_marriage_is_the_divorced_one` — so sánh ngày kết hôn với ngày ly hôn (ds260_mapping.py:737-779)

Logic đã có:
- So sánh `marriage_date > divorce_date` → tái hôn → `return False` (không phải cuộc hôn nhân đã ly hôn)
- Nếu `marriage_date <= divorce_date` hoặc không so sánh được → coi là cùng cuộc hôn nhân → `return True`

### 2. ✅ `enrich_previous_spouse_from_divorce` — giữ Previous Spouse khi tái hôn cùng người (ds260_mapping.py:1555-1638)

Logic đã có:
- Tham số `is_same_person_remarried` đã được thêm
- Khi `is_same_person_remarried=True`, ex_full IS the ex-spouse (same as current spouse) nên KHÔNG reset

### 3. ✅ `reconcile_previous_spouse_with_marital_status` — giữ Previous Spouse khi Married có divorce (ds260_mapping.py:823-850)

Logic đã có:
- Khi `final_status == "Single"` → xóa Previous Spouse
- Khi `final_status == "Married"` và có divorce record → giữ nguyên (không xóa) vì đây là tái hôn cùng người

### 4. ✅ So sánh spouse giữa family case và spouse applicant DS-260 (ds260_conflicts.py)

**Bug Fixed:** `sync_ds260_doc_conflicts` có bug `desired` được sử dụng trước khi khai báo → đã fix bằng cách khởi tạo `desired = {}` trước khi sử dụng.

**Functions đã có:**
- `build_spouse_work_conflict_rows`: So sánh `spouse_occupation` giữa marriage certificate và spouse's DS-260 worksheet
- `build_spouse_identity_conflict_rows`: So sánh `spouse_birth_city/state/country/address` giữa marriage certificate và spouse's DS-260 worksheet

## Verification

1. Run tests: `cd backend && python -m pytest tests/test_ds260_spouse.py -v`
2. Manual test: Tạo case với married + divorce cùng người → status = Married, hiển thị cả Spouse Info và Previous Spouse
3. Test spouse comparison: Verify dữ liệu spouse nhất quán giữa family case và DS-260
