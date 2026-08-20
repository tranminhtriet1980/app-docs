---
name: ds260-worksheet-is-primary-source
description: DS-260 worksheet is always filled FIRST; all other documents are only for comparison/conflict detection
metadata:
  type: feedback
---

**Rule:** DS-260 worksheet (ds260_customer_form) is ALWAYS filled first. All other document sources — birth_certificate, judicial_certificate, application_form, marriage_certificate, etc. — are ONLY used for comparison/conflict detection. Never for filling.

**Why:** The user (customer) declares information on their DS-260 worksheet themselves. Other documents (BC, judicial, passport, etc.) are secondary evidence for comparison only.

**How to apply:**
- In `resolve_ds260_form()`: for fields where DS-260 worksheet is the intended source, call `resolve_customer_form_field(records, "ds260_customer_form", mapping)` directly, bypassing `resolve_luong1_ds260_field()` which would otherwise fill from tier-0 documents first.
- In `enrich_empty_fields_from_all_doc_records()`: special-case `_PARENT_NAME_KEYS` (father/mother name fields) to fill from worksheet BEFORE falling through to tiered document priority.
- In `enrich_work_education_from_worksheet()`: if Application Form already has the same work info as worksheet (English matches Vietnamese), skip filling from worksheet — keep App Form English version.
- Conflict detection (`build_worksheet_conflict_rows`): still works correctly because it compares BC/Judicial against worksheet, creating conflict rows when they differ.
