/** "" = same origin (Caddy hoặc Next.js rewrite). Hoạt động với mọi IP LAN. */
function resolveApiUrl(): string {
  const envUrl = process.env.NEXT_PUBLIC_API_URL;

  if (typeof window !== "undefined") {
    if (envUrl === "" || envUrl === undefined) {
      return "";
    }
    const host = window.location.hostname;
    const envIsLocal =
      envUrl.includes("127.0.0.1") || envUrl.includes("localhost");
    if (envIsLocal && host !== "localhost" && host !== "127.0.0.1") {
      return "";
    }
    return envUrl;
  }

  if (envUrl !== undefined) return envUrl;
  return "http://localhost:8000";
}

const API_URL = resolveApiUrl();

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("token");
}

export function setToken(token: string) {
  localStorage.setItem("token", token);
}

export function clearToken() {
  localStorage.removeItem("token");
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getToken();
  const headers: HeadersInit = {
    ...(options.headers || {}),
  };
  if (!(options.body instanceof FormData)) {
    (headers as Record<string, string>)["Content-Type"] = "application/json";
  }
  if (token) {
    (headers as Record<string, string>)["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_URL}${path}`, { ...options, headers });
  if (res.status === 401) {
    clearToken();
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new Error("Unauthorized");
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const detail = err.detail;
    let message = typeof detail === "string" ? detail : Array.isArray(detail) ? detail[0]?.msg : "Request failed";
    if (res.status === 413) {
      message = "File quá lớn (tối đa 20MB/file). Thử file nhỏ hơn hoặc liên hệ admin.";
    }
    throw new Error(message || "Request failed");
  }
  if (res.status === 204) return {} as T;
  return res.json();
}

import { DS260_DEFAULT_TEMPLATE_CODE } from "./ds260Templates";

export const api = {
  register: (email: string, password: string, full_name?: string) =>
    request("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, full_name }),
    }),

  login: async (email: string, password: string) => {
    const body = new URLSearchParams();
    body.set("username", email.trim().toLowerCase());
    body.set("password", password);
    let res: Response;
    try {
      res = await fetch(`${API_URL}/api/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body,
      });
    } catch {
      const target = API_URL || "(cùng domain qua Caddy)";
      throw new Error(`Không kết nối được API ${target}. Kiểm tra backend và reverse proxy.`);
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      const detail = err.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail[0]?.msg
            : "Invalid credentials";
      throw new Error(message || "Invalid credentials");
    }
    const data = await res.json();
    if (!data?.access_token) {
      throw new Error("Đăng nhập thất bại: không nhận được token.");
    }
    setToken(data.access_token);
    return data;
  },

  me: () =>
    request<User>("/api/v1/auth/me"),

  getStats: () => request<DashboardStats>("/api/v1/applicants/stats"),

  getAdminStats: () => request<DashboardStats>("/api/v1/admin/stats"),

  listApplicants: (params?: { status?: string; search?: string }) => {
    const q = new URLSearchParams();
    if (params?.status) q.set("status", params.status);
    if (params?.search) q.set("search", params.search);
    const qs = q.toString();
    return request<Applicant[]>(`/api/v1/applicants${qs ? `?${qs}` : ""}`);
  },

  deleteApplicant: (id: string, opts?: { force?: boolean; permanent?: boolean }) => {
    const q = new URLSearchParams();
    if (opts?.force) q.set("force", "true");
    if (opts?.permanent) q.set("permanent", "true");
    const qs = q.toString();
    return request(`/api/v1/applicants/${id}${qs ? `?${qs}` : ""}`, { method: "DELETE" });
  },

  restoreApplicant: (id: string) =>
    request<Applicant>(`/api/v1/applicants/${id}/restore`, { method: "POST" }),

  listTrash: () => request<Applicant[]>("/api/v1/applicants/trash"),

  downloadCsvReport: async () => {
    const token = getToken();
    const res = await fetch(`${API_URL}/api/v1/admin/export/csv`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error("Export failed");
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "applicants_report.csv";
    a.click();
    URL.revokeObjectURL(url);
  },

  listAuditLogs: () => request<AuditLog[]>("/api/v1/admin/audit-logs"),

  listBackups: () => request<BackupInfo[]>("/api/v1/admin/backups"),

  createBackup: () => request<{ message: string }>("/api/v1/admin/backups", { method: "POST" }),

  restoreBackup: (filename: string) =>
    request(`/api/v1/admin/backups/restore?filename=${encodeURIComponent(filename)}`, { method: "POST" }),

  listAdminTemplates: () => request<FormTemplateAdmin[]>("/api/v1/admin/form-templates"),

  toggleTemplate: (id: string, is_active: boolean) =>
    request(`/api/v1/admin/form-templates/${id}?is_active=${is_active}`, { method: "PATCH" }),

  deleteTemplate: (id: string) =>
    request(`/api/v1/admin/form-templates/${id}`, { method: "DELETE" }),

  changePassword: (current_password: string, new_password: string) =>
    request("/api/v1/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password, new_password }),
    }),

  setupTotp: () => request<{ secret: string; provisioning_uri: string }>("/api/v1/auth/totp/setup", { method: "POST" }),

  enableTotp: (code: string) =>
    request("/api/v1/auth/totp/enable", { method: "POST", body: JSON.stringify({ code }) }),

  disableTotp: (code: string) =>
    request("/api/v1/auth/totp/disable", { method: "POST", body: JSON.stringify({ code }) }),

  listNotifications: () => request<Notification[]>("/api/v1/notifications"),

  unreadCount: () => request<{ count: number }>("/api/v1/notifications/unread-count"),

  markNotificationRead: (id: string) =>
    request(`/api/v1/notifications/${id}/read`, { method: "POST" }),

  markAllNotificationsRead: () =>
    request("/api/v1/notifications/read-all", { method: "POST" }),

  assignStaff: (applicantId: string, assigned_staff_id: string | null) =>
    request<Applicant>(`/api/v1/applicants/${applicantId}`, {
      method: "PATCH",
      body: JSON.stringify({ assigned_staff_id }),
    }),

  listAdminApplicants: (params?: { status?: string; search?: string }) => {
    const q = new URLSearchParams();
    if (params?.status) q.set("status", params.status);
    if (params?.search) q.set("search", params.search);
    const qs = q.toString();
    return request<ApplicantAdmin[]>(`/api/v1/admin/applicants${qs ? `?${qs}` : ""}`);
  },

  listUsers: () => request<UserAdmin[]>("/api/v1/admin/users"),

  createUser: (data: {
    email: string;
    password: string;
    full_name?: string;
    role?: "user" | "staff" | "admin";
    is_active?: boolean;
    can_create_applicants?: boolean;
    max_applicants_per_month?: number;
  }) =>
    request<UserAdmin>("/api/v1/admin/users", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  updateUser: (id: string, patch: Partial<UserAdmin>) =>
    request<UserAdmin>(`/api/v1/admin/users/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  createApplicant: (data: {
    display_name: string;
    notes?: string;
    client_name?: string;
    project_name?: string;
    department?: string;
    case_type?: "immigration" | "study_abroad" | "tourism" | "other";
    tags?: string[];
    is_family_bundle?: boolean;
    members?: {
      role: "principal" | "spouse" | "child" | "grandchild" | "sibling";
      display_name: string;
    }[];
  }) =>
    request<Applicant>("/api/v1/applicants", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  updateApplicant: (id: string, patch: Partial<Applicant> & { tags?: string[] }) =>
    request<Applicant>(`/api/v1/applicants/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  globalSearch: (q: string) =>
    request<SearchResult>(`/api/v1/search?q=${encodeURIComponent(q)}`),

  getExecutiveReport: () => request<ExecutiveDashboard>("/api/v1/reports/executive"),

  aiChat: (applicantId: string, question: string) =>
    request<{ answer: string; model?: string }>(`/api/v1/applicants/${applicantId}/ai/chat`, {
      method: "POST",
      body: JSON.stringify({ question }),
    }),

  downloadApplicantZip: async (applicantId: string) => {
    const token = getToken();
    const res = await fetch(`${API_URL}/api/v1/applicants/${applicantId}/export-zip`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error("ZIP export failed");
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `ho_so_${applicantId}.zip`;
    a.click();
    URL.revokeObjectURL(url);
  },

  getApplicant: (id: string) => request<Applicant>(`/api/v1/applicants/${id}`),

  listCaseMembers: (applicantId: string) =>
    request<CaseMember[]>(`/api/v1/applicants/${applicantId}/members`),

  setCaseMembers: (
    applicantId: string,
    members: {
      role: "principal" | "spouse" | "child" | "grandchild" | "sibling";
      display_name: string;
    }[]
  ) =>
    request<CaseMember[]>(`/api/v1/applicants/${applicantId}/members`, {
      method: "PUT",
      body: JSON.stringify({ members }),
    }),

  addCaseMembers: (
    applicantId: string,
    members: { role: "spouse" | "child" | "grandchild" | "sibling"; display_name: string }[]
  ) =>
    request<CaseMember[]>(`/api/v1/applicants/${applicantId}/members`, {
      method: "POST",
      body: JSON.stringify({ members }),
    }),

  updateCaseMember: (applicantId: string, memberId: string, displayName: string) =>
    request<CaseMember>(`/api/v1/applicants/${applicantId}/members/${memberId}`, {
      method: "PATCH",
      body: JSON.stringify({ display_name: displayName }),
    }),

  deleteCaseMember: (applicantId: string, memberId: string) =>
    request<{ message: string }>(`/api/v1/applicants/${applicantId}/members/${memberId}`, {
      method: "DELETE",
    }),

  listDocuments: (applicantId: string) =>
    request<Document[]>(`/api/v1/applicants/${applicantId}/documents`),

  uploadDocument: (applicantId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Document>(`/api/v1/applicants/${applicantId}/documents`, {
      method: "POST",
      body: form,
    });
  },

  uploadDocumentsBatch: (applicantId: string, files: File[]) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    return request<Document[]>(`/api/v1/applicants/${applicantId}/documents/batch`, {
      method: "POST",
      body: form,
    });
  },

  reprocessDocument: (applicantId: string, documentId: string) =>
    request(`/api/v1/applicants/${applicantId}/documents/${documentId}/reprocess`, {
      method: "POST",
    }),

  reprocessAllDocuments: (applicantId: string) =>
    request(`/api/v1/applicants/${applicantId}/documents/reprocess-all`, {
      method: "POST",
    }),

  deleteDocument: (applicantId: string, documentId: string) =>
    request(`/api/v1/applicants/${applicantId}/documents/${documentId}`, {
      method: "DELETE",
    }),

  getProfile: (applicantId: string) =>
    request<Profile>(`/api/v1/applicants/${applicantId}/profile`),

  listDocRecords: (applicantId: string, params?: { doc_type?: string; document_id?: string }) => {
    const q = new URLSearchParams();
    if (params?.doc_type) q.set("doc_type", params.doc_type);
    if (params?.document_id) q.set("document_id", params.document_id);
    const qs = q.toString();
    return request<DocRecord[]>(`/api/v1/applicants/${applicantId}/doc-records${qs ? `?${qs}` : ""}`);
  },

  listDocumentTables: (applicantId: string) =>
    request<DocTableSummary[]>(`/api/v1/applicants/${applicantId}/tables`),

  listReferenceDocumentTables: (applicantId: string) =>
    request<DocTableSummary[]>(`/api/v1/applicants/${applicantId}/tables/reference`),

  getDocumentTable: (applicantId: string, docType: string, variant?: "standard" | "exception") => {
    const q = variant ? `?variant=${variant}` : "";
    return request<DocRecord[]>(`/api/v1/applicants/${applicantId}/tables/${docType}${q}`);
  },

  getDs260Form: (applicantId: string, memberId?: string) => {
    const q = memberId ? `?member_id=${encodeURIComponent(memberId)}` : "";
    return request<Ds260Form>(`/api/v1/applicants/${applicantId}/ds260-form${q}`);
  },

  updateDs260Field: (applicantId: string, fieldKey: string, value: string, memberId?: string) => {
    const q = memberId ? `?member_id=${encodeURIComponent(memberId)}` : "";
    return request<Ds260Form>(
      `/api/v1/applicants/${applicantId}/ds260-form/fields/${encodeURIComponent(fieldKey)}${q}`,
      {
        method: "PATCH",
        body: JSON.stringify({ value }),
      }
    );
  },

  getDs260Validation: (applicantId: string) =>
    request<Ds260Validation>(`/api/v1/applicants/${applicantId}/ds260-validate`),

  getDs260Conflicts: (applicantId: string) =>
    request<Conflict[]>(`/api/v1/applicants/${applicantId}/ds260-conflicts`),

  exportDs260: (
    applicantId: string,
    skipValidation = false,
    templateCode = DS260_DEFAULT_TEMPLATE_CODE,
    memberId?: string
  ) =>
    request<ExportResult>(`/api/v1/applicants/${applicantId}/export-ds260`, {
      method: "POST",
      body: JSON.stringify({
        skip_validation: skipValidation,
        template_code: templateCode,
        member_id: memberId || null,
      }),
    }),

  exportDs260Batch: (applicantId: string, skipValidation = false, templateCode = DS260_DEFAULT_TEMPLATE_CODE) =>
    request<{
      exports: Ds260MemberExportResult[];
      failed: { member: string; error: string }[];
    }>(`/api/v1/applicants/${applicantId}/export-ds260-batch`, {
      method: "POST",
      body: JSON.stringify({ skip_validation: skipValidation, template_code: templateCode }),
    }),

  getDs260Mapping: () =>
    request<Ds260MappingConfig>("/api/v1/applicants/config/ds260-mapping"),

  getDocumentTableRecord: (applicantId: string, documentId: string) =>
    request<DocRecord>(`/api/v1/applicants/${applicantId}/documents/${documentId}/table-record`),

  listDocumentTypes: () =>
    request<DocumentTypeGuide[]>("/api/v1/document-types"),

  updateField: (applicantId: string, fieldKey: string, field_value: string) =>
    request(`/api/v1/applicants/${applicantId}/profile/fields/${fieldKey}`, {
      method: "PATCH",
      body: JSON.stringify({ field_value }),
    }),

  updateDocRecordField: (applicantId: string, recordId: string, fieldKey: string, value: string) =>
    request<DocRecord>(
      `/api/v1/applicants/${applicantId}/doc-records/${recordId}/fields/${encodeURIComponent(fieldKey)}`,
      {
        method: "PATCH",
        body: JSON.stringify({ value }),
      }
    ),

  resolveConflict: (applicantId: string, conflictId: string, resolved_value: string) =>
    request(`/api/v1/applicants/${applicantId}/conflicts/${conflictId}/resolve`, {
      method: "POST",
      body: JSON.stringify({ resolved_value }),
    }),

  mergeProfile: (applicantId: string) =>
    request(`/api/v1/applicants/${applicantId}/merge`, { method: "POST" }),

  applyProfileSeed: (
    applicantId: string,
    seedName = "dang_van_hung",
    fillEmptyOnly = true
  ) =>
    request<{ message: string }>(`/api/v1/applicants/${applicantId}/profile/apply-seed`, {
      method: "POST",
      body: JSON.stringify({ seed_name: seedName, fill_empty_only: fillEmptyOnly }),
    }),

  approveReview: (applicantId: string) =>
    request<{ message: string }>(`/api/v1/applicants/${applicantId}/review/approve`, { method: "POST" }),

  listTemplates: () => request<FormTemplate[]>("/api/v1/form-templates"),

  deleteFormTemplate: (templateId: string) =>
    request<{ message: string }>(`/api/v1/form-templates/${templateId}`, { method: "DELETE" }),

  uploadFormTemplate: (code: string, name: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    form.append("code", code);
    form.append("name", name);
    return request<FormTemplate>("/api/v1/form-templates/upload", {
      method: "POST",
      body: form,
    });
  },

  exportForm: (applicantId: string, template_code: string) =>
    request<ExportResult>(`/api/v1/applicants/${applicantId}/export`, {
      method: "POST",
      body: JSON.stringify({ template_code }),
    }),

  getApiUsageStats: (days = 30) =>
    request<ApiUsageStats>(`/api/v1/api-usage/stats?days=${days}`),

  listApiUsageLogs: (limit = 50) =>
    request<ApiUsageLog[]>(`/api/v1/api-usage/logs?limit=${limit}`),

  downloadExportFile: async (exportId: string, downloadUrl: string, filename?: string) => {
    const token = getToken();
    if (!token) {
      throw new Error("Phiên đăng nhập hết hạn. Vui lòng đăng nhập lại.");
    }
    const res = await fetch(`${API_URL}${downloadUrl}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) {
      let detail = "Tải file thất bại";
      try {
        const body = await res.json();
        if (typeof body.detail === "string") detail = body.detail;
      } catch {
        /* ignore non-JSON body */
      }
      if (res.status === 401 || res.status === 403) {
        throw new Error(
          detail === "Not authenticated"
            ? "Phiên đăng nhập hết hạn. Vui lòng đăng nhập lại."
            : detail
        );
      }
      throw new Error(detail);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename || `export_${exportId}.docx`;
    a.click();
    URL.revokeObjectURL(url);
  },
};

export type User = {
  id: string;
  email: string;
  full_name: string | null;
  role: "user" | "staff" | "admin";
  is_active?: boolean;
  can_create_applicants?: boolean;
  totp_enabled?: boolean;
  max_applicants_per_month?: number;
  created_at?: string;
};

export type UserAdmin = User & {
  applicant_count: number;
  is_active: boolean;
  can_create_applicants: boolean;
  max_applicants_per_month?: number;
  totp_enabled?: boolean;
  created_at: string;
};

export type DashboardStats = {
  total_applicants: number;
  total_documents: number;
  total_exports: number;
  open_conflicts: number;
  applicants_this_week: number;
  by_status: Record<string, number>;
  total_users?: number | null;
  trend_weekly?: { week: string; count: number }[];
  quota_used?: number | null;
  quota_limit?: number | null;
  pending_count?: number;
  completed_count?: number;
  overdue_count?: number;
  by_case_type?: Record<string, number>;
  processing_trend?: { day: string; completed: number; processing: number; overdue: number }[];
  monthly_growth_pct?: number | null;
};

export type AuditLog = {
  id: string;
  user_email: string | null;
  action: string;
  entity_type: string;
  entity_id: string;
  payload: string | null;
  created_at: string;
};

export type BackupInfo = { filename: string; size_bytes: number; created_at: string };

export type Notification = {
  id: string;
  title: string;
  message: string;
  link: string | null;
  is_read: boolean;
  created_at: string;
};

export type FormTemplateAdmin = FormTemplate & {
  is_active: boolean;
  template_path?: string | null;
  created_at?: string;
};

export type Applicant = {
  id: string;
  display_name: string;
  status: string;
  notes: string | null;
  client_name?: string | null;
  project_name?: string | null;
  department?: string | null;
  case_type?: string;
  tags?: string[];
  document_count: number;
  open_conflicts: number;
  created_at: string;
  updated_at: string;
  assigned_staff_id?: string | null;
  assigned_staff_email?: string | null;
  deleted_at?: string | null;
  is_family_bundle?: boolean;
  member_count?: number;
};

export type CaseMember = {
  id: string;
  role: "principal" | "spouse" | "child" | "grandchild" | "sibling";
  display_name: string;
  sort_order: number;
  member_number?: string;
};

export type ApplicantAdmin = Applicant & {
  export_count?: number;
  owner_id?: string;
  owner_email?: string | null;
};

export type Document = {
  id: string;
  original_filename: string;
  document_type: string | null;
  registry_doc_type?: string | null;
  is_exception?: boolean;
  status: string;
  classification_confidence: number | null;
  error_message: string | null;
  tags?: string[];
  duplicate_warning?: boolean;
  member_number?: string | null;
  member_display_name?: string | null;
  member_file_label?: string | null;
  uploaded_at: string;
};

export type DocRecord = {
  id: string;
  doc_type: string;
  display_name: string;
  form_section: string;
  variant: string;
  source_document_id: string | null;
  source_document_filename: string | null;
  raw_data: Record<string, string>;
  form_data: Record<string, string>;
  updated_at: string | null;
};

export type DocTableSummary = {
  doc_type: string;
  display_name: string;
  form_section: string;
  record_count: number;
  standard_count?: number;
  reference_count?: number;
  supports_reference?: boolean;
  upload_hint?: string | null;
};

export type Ds260FieldSource = {
  document_type: string;
  source_field: string;
  document_id: string | null;
  document_filename: string | null;
  variant: string | null;
  record_id: string | null;
  derived?: string | null;
};

export type Ds260ResolvedField = {
  key: string;
  label: string;
  value: string;
  review_hidden?: boolean;
  source: Ds260FieldSource;
};

export type Ds260Section = {
  id: string;
  title: string;
  subtitle: string;
  fields: Ds260ResolvedField[];
  filled_count?: number;
  total_count?: number;
  applicable_count?: number;
  applicable_filled_count?: number;
  document_missing?: boolean;
};

export type Ds260DocumentSnapshot = {
  record_id: string;
  document_id: string;
  document_filename: string;
  variant: string;
  form_data: Record<string, string>;
  raw_data: Record<string, string>;
  updated_at: string | null;
};

export type Ds260Form = {
  version: number;
  filled_count: number;
  total_count: number;
  applicable_filled_count?: number;
  applicable_count?: number;
  member?: { id: string; display_name: string; role: string } | null;
  sections: Ds260Section[];
  documents: Record<string, Ds260DocumentSnapshot>;
};

export type Ds260ValidationIssue = {
  code: string;
  message: string;
  field_key?: string | null;
  document_type?: string | null;
};

export type Ds260Validation = {
  valid: boolean;
  error_count: number;
  warning_count: number;
  errors: Ds260ValidationIssue[];
  warnings: Ds260ValidationIssue[];
  filled_count: number;
  total_count: number;
};

export type Ds260MappingConfig = {
  version: number;
  description: string;
  sections: {
    id: string;
    title: string;
    subtitle: string;
    fields: { key: string; label: string; document: string; field: string; aliases: string[] }[];
  }[];
};

export type DocumentTypeGuide = {
  code: string;
  display_name: string;
  form_section: string;
  standard_filename: string;
  exception_filename: string;
  extract_keys: string[];
  field_labels?: Record<string, string>;
};

export type SearchResult = {
  query: string;
  applicants: {
    id: string;
    display_name: string;
    status: string;
    client_name?: string | null;
    project_name?: string | null;
    department?: string | null;
    tags: string[];
  }[];
  documents: {
    id: string;
    applicant_id: string;
    applicant_name: string;
    filename: string;
    document_type: string | null;
    status: string;
    tags: string[];
  }[];
};

export type ExecutiveDashboard = {
  total_applicants: number;
  total_documents: number;
  documents_today: number;
  new_applicants_this_week: number;
  ai_success_rate: number;
  ai_processed_documents: number;
  duplicate_documents: number;
  profiles_incomplete: number;
  by_document_type: Record<string, number>;
  upload_trend_weekly: { week: string; count: number }[];
  top_users: { email: string; uploads: number }[];
  ai_calls_this_month: number;
  ai_tokens_this_month: number;
};

export type ProfileField = {
  field_key: string;
  field_value: string | null;
  is_manual: boolean;
  confidence: number | null;
};

export type Conflict = {
  id: string;
  field_key: string;
  value_a: string | null;
  document_a_filename?: string | null;
  value_b: string | null;
  document_b_filename?: string | null;
  status: string;
  conflict_type?: string | null;
  field_label?: string | null;
};

export type Profile = {
  applicant_id: string;
  status: string;
  fields: Record<string, ProfileField>;
  conflicts: Conflict[];
  sections: Record<string, string[]>;
  field_labels?: Record<string, string>;
};

export type FormTemplate = {
  id: string;
  code: string;
  name: string;
  description: string | null;
};

export type ExportResult = {
  id: string;
  download_url: string;
};

export type Ds260MemberExportResult = ExportResult & {
  member_id?: string;
  member_name?: string;
  member_role?: string;
};

export type ApiUsageStats = {
  period_days: number;
  total_calls: number;
  successful_calls: number;
  failed_calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  tokens_today: number;
  estimated_cost_usd: number;
  monthly_token_budget: number | null;
  budget_used_percent: number | null;
  by_operation: { operation: string; calls: number; total_tokens: number }[];
  by_model: { model: string; calls: number; total_tokens: number }[];
  by_user?: { user_id: string | null; email: string; calls: number; total_tokens: number }[];
  current_model: string;
};

export type ApiUsageLog = {
  id: string;
  user_id: string | null;
  user_email: string | null;
  applicant_id: string | null;
  document_id: string | null;
  operation: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  filename: string | null;
  doc_type: string | null;
  success: boolean;
  error_message: string | null;
  created_at: string;
};
