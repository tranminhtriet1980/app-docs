import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field

from app.models.entities import ApplicantStatus, CaseType, ConflictStatus, DocumentStatus, UserRole


# Auth
class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    full_name: str | None = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str | None
    role: UserRole
    is_active: bool = True
    can_create_applicants: bool = True
    max_applicants_per_month: int = 50
    totp_enabled: bool = False
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6)


class TotpSetupOut(BaseModel):
    secret: str
    provisioning_uri: str


class TotpVerify(BaseModel):
    code: str = Field(min_length=6, max_length=6)


class LoginWithTotp(BaseModel):
    email: EmailStr
    password: str
    totp_code: str | None = None


class UserAdminOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str | None
    role: UserRole
    is_active: bool
    can_create_applicants: bool
    max_applicants_per_month: int = 50
    totp_enabled: bool = False
    created_at: datetime
    applicant_count: int = 0

    model_config = {"from_attributes": True}


class UserAdminCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    full_name: str | None = None
    role: UserRole = UserRole.user
    is_active: bool = True
    can_create_applicants: bool = True
    max_applicants_per_month: int = Field(default=50, ge=1, le=10000)


class UserAdminUpdate(BaseModel):
    full_name: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None
    can_create_applicants: bool | None = None
    max_applicants_per_month: int | None = None


# Applicant
class FamilyMemberCreate(BaseModel):
    role: Literal["principal", "spouse", "child", "grandchild", "sibling"] = "principal"
    display_name: str = Field(min_length=1, max_length=255)


class ApplicantCreate(BaseModel):
    display_name: str
    notes: str | None = None
    client_name: str | None = None
    project_name: str | None = None
    department: str | None = None
    case_type: CaseType = CaseType.immigration
    tags: list[str] | None = None
    is_family_bundle: bool = False
    members: list[FamilyMemberCreate] | None = None


class CaseMemberOut(BaseModel):
    id: uuid.UUID
    role: str
    display_name: str
    sort_order: int = 0
    member_number: str = "01"

    model_config = {"from_attributes": True}


class FamilyMembersUpdate(BaseModel):
    members: list[FamilyMemberCreate] = Field(min_length=1)


class FamilyMembersAppend(BaseModel):
    members: list[FamilyMemberCreate] = Field(min_length=1)


class CaseMemberUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=255)


class ApplicantUpdate(BaseModel):
    display_name: str | None = None
    notes: str | None = None
    client_name: str | None = None
    project_name: str | None = None
    department: str | None = None
    case_type: CaseType | None = None
    tags: list[str] | None = None
    assigned_staff_id: uuid.UUID | None = None


class ApplicantOut(BaseModel):
    id: uuid.UUID
    display_name: str
    status: ApplicantStatus
    notes: str | None
    client_name: str | None = None
    project_name: str | None = None
    department: str | None = None
    case_type: str = "immigration"
    tags: list[str] = []
    created_at: datetime
    updated_at: datetime
    document_count: int = 0
    open_conflicts: int = 0
    assigned_staff_id: uuid.UUID | None = None
    assigned_staff_email: str | None = None
    deleted_at: datetime | None = None
    is_family_bundle: bool = False
    member_count: int = 0

    model_config = {"from_attributes": True}


class ApplicantAdminOut(ApplicantOut):
    export_count: int = 0
    owner_id: uuid.UUID
    owner_email: str | None = None


class DashboardStatsOut(BaseModel):
    total_applicants: int
    total_documents: int
    total_exports: int
    open_conflicts: int
    applicants_this_week: int
    by_status: dict[str, int]
    total_users: int | None = None
    trend_weekly: list[dict[str, int | str]] | None = None
    quota_used: int | None = None
    quota_limit: int | None = None
    pending_count: int = 0
    completed_count: int = 0
    overdue_count: int = 0
    by_case_type: dict[str, int] = {}
    processing_trend: list[dict] = []
    monthly_growth_pct: float | None = None


class AuditLogOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    user_email: str | None = None
    action: str
    entity_type: str
    entity_id: str
    payload: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationOut(BaseModel):
    id: uuid.UUID
    title: str
    message: str
    link: str | None
    is_read: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class BackupInfoOut(BaseModel):
    filename: str
    size_bytes: int
    created_at: str


# Document
class DocumentOut(BaseModel):
    id: uuid.UUID
    applicant_id: uuid.UUID
    original_filename: str
    mime_type: str
    file_size: int
    document_type: str | None
    registry_doc_type: str | None = None
    is_exception: bool = False
    classification_confidence: float | None
    status: DocumentStatus
    error_message: str | None
    tags: list[str] = []
    duplicate_warning: bool = False
    member_number: str | None = None
    member_display_name: str | None = None
    member_file_label: str | None = None
    uploaded_at: datetime
    processed_at: datetime | None

    model_config = {"from_attributes": True}


class DocRecordOut(BaseModel):
    id: uuid.UUID
    doc_type: str
    display_name: str
    form_section: str
    variant: str
    source_document_id: uuid.UUID | None
    source_document_filename: str | None = None
    raw_data: dict[str, Any]
    form_data: dict[str, Any]
    updated_at: datetime | None


class DocRecordFieldUpdate(BaseModel):
    value: str = ""


class DocTableSummaryOut(BaseModel):
    doc_type: str
    display_name: str
    form_section: str
    record_count: int
    standard_count: int = 0
    reference_count: int = 0
    supports_reference: bool = False
    upload_hint: str | None = None


class Ds260FieldSourceOut(BaseModel):
    document_type: str
    source_field: str
    document_id: str | None = None
    document_filename: str | None = None
    variant: str | None = None
    record_id: str | None = None
    derived: str | None = None


class Ds260FieldUpdate(BaseModel):
    value: str


class Ds260ResolvedFieldOut(BaseModel):
    key: str
    label: str
    value: str
    review_hidden: bool = False
    source: Ds260FieldSourceOut


class Ds260SectionOut(BaseModel):
    id: str
    title: str
    subtitle: str
    fields: list[Ds260ResolvedFieldOut]
    filled_count: int = 0
    total_count: int = 0
    applicable_count: int = 0
    applicable_filled_count: int = 0
    document_missing: bool = False


class Ds260DocumentSnapshotOut(BaseModel):
    record_id: str
    document_id: str
    document_filename: str
    variant: str
    form_data: dict[str, Any]
    raw_data: dict[str, Any]
    updated_at: str | None = None


class Ds260FormOut(BaseModel):
    version: int
    filled_count: int
    total_count: int
    applicable_filled_count: int = 0
    applicable_count: int = 0
    member: dict[str, Any] | None = None
    sections: list[Ds260SectionOut]
    documents: dict[str, Ds260DocumentSnapshotOut]


class Ds260ValidationIssueOut(BaseModel):
    code: str
    message: str
    field_key: str | None = None
    document_type: str | None = None


class Ds260ValidationOut(BaseModel):
    valid: bool
    error_count: int
    warning_count: int
    errors: list[Ds260ValidationIssueOut]
    warnings: list[Ds260ValidationIssueOut]
    filled_count: int
    total_count: int


class Ds260ExportRequest(BaseModel):
    skip_validation: bool = False
    template_code: str = "6_eb3_tt_-___n_ds260_-_h_ng_1"
    member_id: uuid.UUID | None = None


class Ds260MappingFieldOut(BaseModel):
    key: str
    label: str
    document: str
    field: str
    aliases: list[str] = []


class Ds260MappingSectionOut(BaseModel):
    id: str
    title: str
    subtitle: str
    fields: list[Ds260MappingFieldOut]


class Ds260MappingOut(BaseModel):
    version: int
    description: str
    sections: list[Ds260MappingSectionOut]


class DocumentTypeGuideOut(BaseModel):
    code: str
    display_name: str
    form_section: str
    standard_filename: str
    exception_filename: str
    extract_keys: list[str]
    field_labels: dict[str, str] = Field(default_factory=dict)


class DocumentTagsUpdate(BaseModel):
    tags: list[str]


class SearchResultOut(BaseModel):
    query: str
    applicants: list[dict]
    documents: list[dict]


class AiChatRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)


class AiChatOut(BaseModel):
    answer: str
    model: str | None = None


class ExecutiveDashboardOut(BaseModel):
    total_applicants: int
    total_documents: int
    documents_today: int
    new_applicants_this_week: int
    ai_success_rate: float
    ai_processed_documents: int
    duplicate_documents: int
    profiles_incomplete: int
    by_document_type: dict[str, int]
    upload_trend_weekly: list[dict]
    top_users: list[dict]
    ai_calls_this_month: int
    ai_tokens_this_month: int


class ExtractedFieldOut(BaseModel):
    id: uuid.UUID
    field_key: str
    field_value: str | None
    confidence: float | None
    source_page: str | None

    model_config = {"from_attributes": True}


class DocumentDetailOut(DocumentOut):
    extracted_fields: list[ExtractedFieldOut] = []


# Profile
class ProfileFieldOut(BaseModel):
    field_key: str
    field_value: str | None
    source_document_id: uuid.UUID | None
    confidence: float | None
    is_manual: bool
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProfileFieldUpdate(BaseModel):
    field_value: str


class ProfileSeedApply(BaseModel):
    seed_name: str = "dang_van_hung"
    fill_empty_only: bool = True


class ConflictOut(BaseModel):
    id: uuid.UUID
    field_key: str
    value_a: str | None
    document_a_id: uuid.UUID | None
    document_a_filename: str | None = None
    value_b: str | None
    document_b_id: uuid.UUID | None
    document_b_filename: str | None = None
    status: ConflictStatus
    resolved_value: str | None
    conflict_type: str | None = None
    field_label: str | None = None

    model_config = {"from_attributes": True}


class ConflictResolve(BaseModel):
    resolved_value: str


class ProfileOut(BaseModel):
    applicant_id: uuid.UUID
    status: ApplicantStatus
    fields: dict[str, ProfileFieldOut]
    conflicts: list[ConflictOut]
    sections: dict[str, list[str]]
    field_labels: dict[str, str] = {}


# Export
class FormTemplateOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    description: str | None

    model_config = {"from_attributes": True}


class FormTemplateAdminOut(FormTemplateOut):
    is_active: bool = True
    template_path: str | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class ExportRequest(BaseModel):
    template_code: str


class ExportOut(BaseModel):
    id: uuid.UUID
    file_path: str
    download_url: str
    created_at: datetime

    model_config = {"from_attributes": True}


class Ds260MemberExportOut(ExportOut):
    member_id: uuid.UUID | None = None
    member_name: str | None = None
    member_role: str | None = None


class Ds260BatchExportOut(BaseModel):
    exports: list[Ds260MemberExportOut]
    failed: list[dict[str, str]] = []


class MessageOut(BaseModel):
    message: str
    detail: Any | None = None


class ApiUsageLogOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    user_email: str | None = None
    applicant_id: uuid.UUID | None
    document_id: uuid.UUID | None
    operation: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    filename: str | None
    doc_type: str | None
    success: bool
    error_message: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ApiUsageStatsOut(BaseModel):
    period_days: int
    total_calls: int
    successful_calls: int
    failed_calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    tokens_today: int
    estimated_cost_usd: float
    monthly_token_budget: int | None = None
    budget_used_percent: float | None = None
    by_operation: list[dict]
    by_model: list[dict]
    by_user: list[dict] | None = None
    current_model: str
