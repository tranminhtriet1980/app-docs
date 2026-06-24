import re
import unicodedata
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.entities import (
    Applicant,
    ApplicantStatus,
    Conflict,
    ConflictStatus,
    Document,
    DocumentStatus,
    ExtractedField,
    ProfileField,
)
from app.services.field_mapping import FIELD_MAP, FIELD_LABELS_VI, PROFILE_SECTIONS, SOURCE_PRIORITY

CANONICAL_PROFILE_KEYS = {key for keys in PROFILE_SECTIONS.values() for key in keys}


def _sync_contact_phone_email_aliases(merged: dict) -> None:
    """Keep legacy single phone/email in sync when detailed fields exist."""
    primary = merged.get("contact.phone_primary")
    if primary and primary.field_value:
        if "contact.phone" not in merged:
            merged["contact.phone"] = ProfileField(
                applicant_id=primary.applicant_id,
                field_key="contact.phone",
                field_value=primary.field_value,
                source_document_id=primary.source_document_id,
                confidence=primary.confidence,
                is_manual=False,
            )


def _enrich_merged_from_documents(
    merged: dict[str, ProfileField],
    documents: list[Document],
    applicant_id: uuid.UUID,
) -> None:
    """Derive DS-160 fields from divorce / form documents when OCR used generic keys."""

    def _put(key: str, value: str, *, only_if_empty: bool = True) -> None:
        if key not in CANONICAL_PROFILE_KEYS or not value.strip():
            return
        existing = merged.get(key)
        if existing and (existing.field_value or "").strip() and only_if_empty:
            return
        merged[key] = ProfileField(
            applicant_id=applicant_id,
            field_key=key,
            field_value=value.strip(),
            source_document_id=existing.source_document_id if existing else None,
            confidence=existing.confidence if existing else None,
            is_manual=False,
        )

    for doc in documents:
        if doc.document_type != "divorce":
            fn = (doc.original_filename or "").upper()
            if "divorce" not in fn and "ly hon" not in fn:
                continue
        ex_name = ""
        for ef in doc.extracted_fields:
            if ef.field_key in {"wife_full_name", "plaintiff_name"} and ef.field_value:
                ex_name = ef.field_value.strip()
                break
            if ef.field_key == "spouse_name" and ef.field_value and " AND " not in ef.field_value.upper():
                ex_name = ef.field_value.strip()
        if not ex_name:
            continue
        _put("family.previous_spouses_used", "Yes", only_if_empty=True)
        hist_pf = merged.get("family.previous_spouses_history")
        if not hist_pf or not (hist_pf.field_value or "").strip():
            _put(
                "family.previous_spouses_history",
                f"{ex_name} (từ giấy ly hôn — bổ sung ngày cưới/ly hôn trên Review nếu cần)",
                only_if_empty=True,
            )
        _put("identity.marital_status", "Divorced", only_if_empty=True)
        spouse = merged.get("family.spouse_name")
        if spouse and ex_name and ex_name.upper() in (spouse.field_value or "").upper():
            _put("family.spouse_surname", "N/A", only_if_empty=False)
            _put("family.spouse_name", "N/A", only_if_empty=False)


def _sync_birth_state_from_city(merged: dict) -> None:
    """If Tỉnh/Bang nơi sinh is empty, copy from Thành phố nơi sinh (VN forms often use city only)."""
    if not merged:
        return
    sample = next(iter(merged.values()))
    pairs = [
        ("identity.birth_city", "identity.birth_state"),
        ("family.father_birth_city", "family.father_birth_state"),
        ("family.mother_birth_city", "family.mother_birth_state"),
        ("family.spouse_birth_city", "family.spouse_birth_state"),
    ]
    for city_key, state_key in pairs:
        city_pf = merged.get(city_key)
        state_pf = merged.get(state_key)
        city_val = ((city_pf.field_value if city_pf else None) or "").strip()
        state_val = ((state_pf.field_value if state_pf else None) or "").strip()
        if not city_val or state_val:
            continue
        merged[state_key] = ProfileField(
            applicant_id=sample.applicant_id,
            field_key=state_key,
            field_value=city_val,
            source_document_id=city_pf.source_document_id if city_pf else None,
            confidence=city_pf.confidence if city_pf else None,
            is_manual=False,
        )


def _sync_birth_city_from_place(merged: dict) -> None:
    """If Thành phố nơi sinh is empty, derive from place_of_birth."""
    if not merged:
        return
    sample = next(iter(merged.values()))

    city_pf = merged.get("identity.birth_city")
    city_val = ((city_pf.field_value if city_pf else None) or "").strip()
    if city_val:
        return

    pob_pf = merged.get("identity.place_of_birth")
    pob_val = ((pob_pf.field_value if pob_pf else None) or "").strip()
    if not pob_val:
        return

    parts = [p.strip() for p in pob_val.split(",") if p.strip()]
    candidate = parts[-1] if parts else pob_val
    candidate = re.sub(r"(?i)^thành phố\s+", "", candidate).strip()
    candidate = re.sub(r"(?i)^city\s+", "", candidate).strip()
    if not candidate:
        return

    merged["identity.birth_city"] = ProfileField(
        applicant_id=sample.applicant_id,
        field_key="identity.birth_city",
        field_value=candidate,
        source_document_id=pob_pf.source_document_id if pob_pf else None,
        confidence=pob_pf.confidence if pob_pf else None,
        is_manual=False,
    )


def _compose_place_of_birth(merged: dict) -> None:
    """Build identity.place_of_birth from city/state/country when missing."""
    existing = merged.get("identity.place_of_birth")
    if existing and (existing.field_value or "").strip():
        return
    parts: list[str] = []
    for key in ("identity.birth_city", "identity.birth_state", "identity.birth_country"):
        pf = merged.get(key)
        if pf and (pf.field_value or "").strip():
            parts.append(pf.field_value.strip())
    if not parts:
        return
    combined = ", ".join(parts)
    sample = next(iter(merged.values()))
    merged["identity.place_of_birth"] = ProfileField(
        applicant_id=sample.applicant_id,
        field_key="identity.place_of_birth",
        field_value=combined,
        source_document_id=sample.source_document_id,
        confidence=sample.confidence,
        is_manual=False,
    )


def _strip_accents(text: str) -> str:
    # Vietnamese Đ/đ does not decompose under NFD — map explicitly.
    text = text.replace("\u0110", "D").replace("\u0111", "d")
    normalized = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def _normalize(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip()
    if not v:
        return None
    v = _strip_accents(v)
    return re.sub(r"\s+", " ", v).upper()


def _normalize_name_like(value: str | None) -> str | None:
    n = _normalize(value)
    if not n:
        return None
    n = re.sub(r"\s+\d{1,3}$", "", n)
    n = re.sub(r"[^A-Z0-9\s]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n or None


def _normalize_gender(value: str | None) -> str | None:
    n = _normalize(value)
    if not n:
        return None
    if n in {"M", "MALE", "NAM", "MAN"}:
        return "MALE"
    if n in {"F", "FEMALE", "NU", "WOMAN"}:
        return "FEMALE"
    return n


def _normalize_country(value: str | None) -> str | None:
    n = _normalize(value)
    if not n:
        return None
    if "VIET" in n or n in {"VNM", "VN"}:
        return "VNM"
    return n


def _normalize_passport_number(value: str | None) -> str | None:
    n = _normalize(value)
    if not n:
        return None
    # Passport numbers: letter(s) + digits, e.g. C5059328 — not court certificate numbers
    if re.match(r"^[A-Z]{1,2}\d{6,9}$", n.replace(" ", "")):
        return n.replace(" ", "")
    return None


def _field_norm(field_key: str, value: str | None) -> str | None:
    key = (field_key or "").lower()
    if key == "identity.gender":
        return _normalize_gender(value)
    if key in {"passport.issuing_country", "identity.nationality"}:
        return _normalize_country(value)
    if key == "passport.number":
        return _normalize_passport_number(value) or _normalize(value)
    if "name" in key or key.endswith("_surname") or key.endswith("_given_names") or key in {
        "identity.family_name",
        "identity.given_names",
        "identity.full_name",
        "family.spouse_name",
        "family.father_name",
        "family.mother_name",
    }:
        return _normalize_name_like(value)
    return _normalize(value)


def _source_rank(doc_type: str | None) -> int:
    try:
        return SOURCE_PRIORITY.index(doc_type or "other")
    except ValueError:
        return len(SOURCE_PRIORITY)


def _tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    cleaned = re.sub(r"[^A-Za-z0-9\s]", " ", text.upper())
    return {t for t in cleaned.split() if len(t) >= 2}


def _name_similarity(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / max(len(a), 1)


def _document_name_score(doc: Document, applicant_tokens: set[str]) -> float:
    """
    Score how likely a document belongs to the target applicant.
    Higher score = more relevant to the applicant name.
    """
    if not applicant_tokens:
        return 0.0

    score = 0.0
    filename_tokens = _tokens(doc.original_filename)
    score = max(score, _name_similarity(filename_tokens, applicant_tokens))

    for ef in doc.extracted_fields:
        key = (ef.field_key or "").lower()
        if "name" not in key and key not in {"surname", "family_name", "given_names", "given_name"}:
            continue
        field_tokens = _tokens(ef.field_value)
        score = max(score, _name_similarity(field_tokens, applicant_tokens))
    return score


def _pick_item_by_value(
    items: list[tuple[str, Document, float, float]], value: str
) -> tuple[str, Document, float, float] | None:
    target = _normalize(value)
    for item in items:
        if _normalize(item[0]) == target:
            return item
    return None


def _auto_resolve_conflict_value(
    field_key: str,
    items: list[tuple[str, Document, float, float]],
    applicant_tokens: set[str],
) -> str | None:
    """
    Return auto-resolved value for conflicts when we can infer safely.

    Product rule (requested): if same canonical field has different content,
    keep it as an open conflict so users can choose the correct value.
    Therefore this function now only keeps manual-review behavior and does
    not auto-pick between genuinely different values.
    """
    return None


async def merge_applicant_profile(db: AsyncSession, applicant_id: uuid.UUID) -> Applicant:
    result = await db.execute(
        select(Applicant)
        .where(Applicant.id == applicant_id)
        .options(
            selectinload(Applicant.documents).selectinload(Document.extracted_fields),
            selectinload(Applicant.profile_fields),
            selectinload(Applicant.conflicts),
        )
    )
    applicant = result.scalar_one()
    documents = [d for d in applicant.documents if d.status == DocumentStatus.extracted]

    applicant_tokens = _tokens(applicant.display_name)
    doc_scores: dict[uuid.UUID, float] = {
        doc.id: _document_name_score(doc, applicant_tokens) for doc in documents
    }

    # Build candidates: canonical_key -> list of (value, doc, confidence, name_score)
    candidates: dict[str, list[tuple[str, Document, float, float]]] = {}

    for doc in documents:
        doc_type = doc.document_type or "other"
        mapping = FIELD_MAP.get(doc_type, {})
        for ef in doc.extracted_fields:
            if not ef.field_value:
                continue
            canonical = mapping.get(ef.field_key, f"other.{ef.field_key}")
            candidates.setdefault(canonical, []).append(
                (ef.field_value, doc, ef.confidence or 0.0, doc_scores.get(doc.id, 0.0))
            )

    # Sort by applicant-name relevance first, then source priority, then confidence.
    # If applicant-specific values are missing, list still falls back to related docs.
    for key in candidates:
        candidates[key].sort(
            key=lambda x: (-x[3], _source_rank(x[1].document_type), -x[2])
        )
    # Keep existing open conflicts so frontend conflict IDs remain stable across refresh/auto-merge.
    existing_open_conflicts: dict[str, Conflict] = {
        c.field_key: c for c in applicant.conflicts if c.status == ConflictStatus.open
    }

    merged: dict[str, ProfileField] = {}
    existing = {pf.field_key: pf for pf in applicant.profile_fields if pf.is_manual}

    for field_key, items in candidates.items():
        if field_key not in CANONICAL_PROFILE_KEYS:
            continue
        if field_key in existing:
            continue
        best = items[0]
        best_val, best_doc, best_conf, _best_name_score = best

        # Detect conflicts among distinct normalized values
        distinct: dict[str, tuple[str, Document]] = {}
        for val, doc, _, _name_score in items:
            norm = _field_norm(field_key, val)
            if norm and norm not in distinct:
                distinct[norm] = (val, doc)

        if len(distinct) > 1:
            # Conflict already exists for this field; keep it (stable ID) and wait for user resolution.
            if field_key in existing_open_conflicts:
                continue
            auto_value = _auto_resolve_conflict_value(field_key, items, applicant_tokens)
            if auto_value is not None:
                chosen = _pick_item_by_value(items, auto_value) or items[0]
                chosen_val, chosen_doc, chosen_conf, _chosen_name_score = chosen
                pf = ProfileField(
                    applicant_id=applicant_id,
                    field_key=field_key,
                    field_value=chosen_val,
                    source_document_id=chosen_doc.id,
                    confidence=chosen_conf,
                    is_manual=False,
                )
                merged[field_key] = pf
                continue

            vals = list(distinct.values())
            conflict = Conflict(
                applicant_id=applicant_id,
                field_key=field_key,
                value_a=vals[0][0],
                document_a_id=vals[0][1].id,
                value_b=vals[1][0],
                document_b_id=vals[1][1].id,
                status=ConflictStatus.open,
            )
            db.add(conflict)
            continue

        pf = ProfileField(
            applicant_id=applicant_id,
            field_key=field_key,
            field_value=best_val,
            source_document_id=best_doc.id,
            confidence=best_conf,
            is_manual=False,
        )
        merged[field_key] = pf

    # Remove non-manual profile fields and re-add merged
    await db.execute(
        delete(ProfileField).where(
            ProfileField.applicant_id == applicant_id,
            ProfileField.is_manual.is_(False),
        )
    )
    _enrich_merged_from_documents(merged, documents, applicant_id)
    _sync_birth_city_from_place(merged)
    _sync_birth_state_from_city(merged)
    _compose_place_of_birth(merged)
    _sync_contact_phone_email_aliases(merged)

    for pf in merged.values():
        db.add(pf)

    open_conflicts = await db.execute(
        select(Conflict).where(
            Conflict.applicant_id == applicant_id,
            Conflict.status == ConflictStatus.open,
        )
    )
    has_open = open_conflicts.scalars().first() is not None

    if has_open:
        applicant.status = ApplicantStatus.review
    elif documents:
        applicant.status = ApplicantStatus.review
    applicant.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return applicant


def build_profile_response(applicant: Applicant, conflicts: list[Conflict], fields: list[ProfileField]):
    from app.schemas import ConflictOut, ProfileFieldOut, ProfileOut

    doc_names: dict[uuid.UUID, str] = {}
    for doc in getattr(applicant, "documents", []) or []:
        doc_names[doc.id] = doc.original_filename or ""

    conflict_out: list[ConflictOut] = []
    for c in conflicts:
        base = ConflictOut.model_validate(c)
        conflict_out.append(
            base.model_copy(
                update={
                    "document_a_filename": doc_names.get(c.document_a_id) if c.document_a_id else None,
                    "document_b_filename": doc_names.get(c.document_b_id) if c.document_b_id else None,
                }
            )
        )

    field_map = {
        f.field_key: ProfileFieldOut(
            field_key=f.field_key,
            field_value=f.field_value,
            source_document_id=f.source_document_id,
            confidence=f.confidence,
            is_manual=f.is_manual,
            updated_at=f.updated_at,
        )
        for f in fields
    }
    return ProfileOut(
        applicant_id=applicant.id,
        status=applicant.status,
        fields=field_map,
        conflicts=conflict_out,
        sections=PROFILE_SECTIONS,
        field_labels=FIELD_LABELS_VI,
    )
