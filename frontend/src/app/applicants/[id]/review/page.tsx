"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import AiChatPanel from "@/components/AiChatPanel";
import StatusBadge from "@/components/StatusBadge";
import {
  api,
  Applicant,
  CaseMember,
  Conflict,
  DocRecord,
  DocTableSummary,
  DocumentTypeGuide,
  Ds260Form,
  Ds260Validation,
  FormTemplate,
  getToken,
  User,
} from "@/lib/api";
import { memberColorByNumber } from "@/lib/memberColors";
import {
  DS260_DEFAULT_TEMPLATE_CODE,
  isDs260FormTemplate,
  listDs260FormTemplates,
  normalizeDs260TemplateCode,
} from "@/lib/ds260Templates";

const DOC_TYPE_LABELS: Record<string, string> = {
  passport: "Passport",
  judicial_certificate: "JUDICIAL CERTIFICATE",
  divorce: "Divorce",
  birth_certificate: "Birth certificate",
  death_certificate: "Death certificate",
  marriage_certificate: "Marriage certificate",
  birth_certificate_child: "Birth certificate child",
  military_discharge: "Military discharge",
  ds260_customer_form: "DS-260 (khách khai)",
  address_document: "Address document",
};

const PRINCIPAL_ONLY_ID = "__principal__";

function buildDs260DisplayMembers(members: CaseMember[], applicant: Applicant | null): CaseMember[] {
  if (members.length > 0) return members;
  if (!applicant) return [];
  return [
    {
      id: PRINCIPAL_ONLY_ID,
      role: "principal",
      display_name: applicant.display_name,
      sort_order: 0,
      member_number: "01",
    },
  ];
}

function ds260FormForMember(
  member: CaseMember,
  byMember: Record<string, Ds260Form>,
  fallback: Ds260Form | null
): Ds260Form | null {
  if (member.id === PRINCIPAL_ONLY_ID) return fallback;
  return byMember[member.id] ?? null;
}

function memberRoleLabel(role: CaseMember["role"]) {
  if (role === "principal") return "Chủ hồ sơ";
  if (role === "spouse") return "Phối ngẫu";
  return "Con";
}

const CHILD_SKIP_DS260_SECTIONS = new Set([
  "section_spouse",
  "section_divorce",
  "section_previous_spouse",
  "section_children",
]);

function memberPanelClass(role: CaseMember["role"]) {
  if (role === "principal") return "border-brand-300 bg-brand-50/30 ring-brand-100";
  if (role === "spouse") return "border-violet-300 bg-violet-50/30 ring-violet-100";
  return "border-amber-300 bg-amber-50/30 ring-amber-100";
}

function visibleDs260Sections(sections: Ds260Form["sections"], role: CaseMember["role"]) {
  if (role !== "child") return sections;
  return sections.filter((sec) => !CHILD_SKIP_DS260_SECTIONS.has(sec.id));
}

function Ds260ConflictPanel({
  conflicts,
  onResolve,
  busyId,
}: {
  conflicts: Conflict[];
  onResolve: (conflictId: string, value: string) => void;
  busyId: string;
}) {
  const [customById, setCustomById] = useState<Record<string, string>>({});

  if (conflicts.length === 0) return null;
  return (
    <div className="card mb-6 border-amber-300 bg-amber-50/50">
      <h2 className="text-lg font-semibold text-slate-900">
        Xung đột dữ liệu DS-260 ({conflicts.length})
      </h2>
      <p className="mt-1 text-sm text-slate-600">
        Chọn <strong>nguồn A</strong> (Luồng 1 / giấy tờ chính) hoặc <strong>nguồn B</strong> (đối chiếu{" "}
        <code className="text-xs">_new</code> / worksheet). Giá trị đã chọn sẽ{" "}
        <strong>tự điền</strong> vào bảng DS-260 bên dưới và file Word khi xuất.
      </p>
      <div className="mt-4 space-y-3">
        {conflicts.map((c) => {
          const isWorksheet = c.conflict_type === "document_vs_worksheet";
          const title = c.field_label || c.field_key.replace(/^ds260\./, "");
          const custom = customById[c.id] ?? "";
          return (
            <div key={c.id} className="rounded-lg border border-amber-200 bg-white p-3">
              <p className="text-sm font-medium text-slate-800">{title}</p>
              {isWorksheet && (
                <p className="mt-0.5 text-xs text-slate-500">Loại: Giấy tờ vs DS-260 worksheet</p>
              )}
              <div className="mt-2 flex flex-col gap-2 sm:flex-row">
                <button
                  type="button"
                  disabled={busyId === c.id}
                  className="flex-1 rounded border border-green-200 bg-green-50/50 px-3 py-2 text-left text-sm hover:bg-green-50"
                  onClick={() => onResolve(c.id, c.value_a || "")}
                >
                  <span className="block text-xs font-medium text-green-700">
                    {isWorksheet ? "Nguồn A — Giấy tờ chính (Luồng 1)" : "Nguồn A — Luồng 1 (mẫu)"}
                  </span>
                  <span className="font-mono">{c.value_a || "—"}</span>
                  {c.document_a_filename && (
                    <span className="mt-1 block text-xs text-slate-400">{c.document_a_filename}</span>
                  )}
                </button>
                <button
                  type="button"
                  disabled={busyId === c.id}
                  className="flex-1 rounded border border-amber-200 bg-amber-50/50 px-3 py-2 text-left text-sm hover:bg-amber-50"
                  onClick={() => onResolve(c.id, c.value_b || "")}
                >
                  <span className="block text-xs font-medium text-amber-700">
                    {isWorksheet ? "Nguồn B — DS-260 khách khai" : "Nguồn B — Đối chiếu (_new)"}
                  </span>
                  <span className="font-mono">{c.value_b || "—"}</span>
                  {c.document_b_filename && (
                    <span className="mt-1 block text-xs text-slate-400">{c.document_b_filename}</span>
                  )}
                </button>
              </div>
              <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-end">
                <div className="flex-1">
                  <label className="text-xs text-slate-500">Hoặc nhập giá trị khác</label>
                  <input
                    className="input mt-0.5 min-h-0 py-1.5 font-mono text-sm"
                    value={custom}
                    disabled={busyId === c.id}
                    placeholder="Giá trị tùy chỉnh…"
                    onChange={(e) => setCustomById((prev) => ({ ...prev, [c.id]: e.target.value }))}
                  />
                </div>
                <button
                  type="button"
                  className="btn-secondary shrink-0 text-sm"
                  disabled={busyId === c.id || !custom.trim()}
                  onClick={() => onResolve(c.id, custom.trim())}
                >
                  Dùng giá trị này
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function deriveSourceHint(derived: string | undefined, sourceField: string): string {
  const fromMarriage = sourceField.includes("marriage");
  const fromBirth = sourceField.includes("birth") || sourceField.includes("place_of_birth");
  if (derived === "copy") {
    if (fromMarriage) return " · tách tỉnh/bang từ nơi kết hôn";
    if (fromBirth) return " · tách tỉnh/bang từ nơi sinh";
    return " · sao chép từ nguồn";
  }
  if (derived === "country_from_location") {
    if (fromMarriage) return " · tách quốc gia từ nơi kết hôn";
    return " · tách quốc gia từ nơi sinh";
  }
  if (derived === "city_from_place") {
    return fromMarriage ? " · tách thành phố từ nơi kết hôn" : " · tách thành phố từ nơi sinh";
  }
  if (derived === "spouse_from_marriage") return " · bổ sung từ giấy kết hôn";
  if (derived === "spouse_birth_from_birth_certificate") return " · bổ sung từ GKS phối ngẫu";
  if (derived === "spouse_occupation_from_spouse_ds260") return " · bổ sung từ hồ sơ phối ngẫu";
  return "";
}

function Ds260FieldGrid({
  applicantId,
  memberId,
  fields,
  canEdit,
  onFieldSaved,
}: {
  applicantId: string;
  memberId?: string;
  fields: Ds260Form["sections"][0]["fields"];
  canEdit: boolean;
  onFieldSaved: () => void;
}) {
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [savingKey, setSavingKey] = useState("");

  const displayValue = (f: Ds260Form["sections"][0]["fields"][0]) =>
    drafts[f.key] !== undefined ? drafts[f.key] : f.value || "";

  const isDirty = (f: Ds260Form["sections"][0]["fields"][0]) => {
    if (drafts[f.key] === undefined) return false;
    return drafts[f.key].trim() !== (f.value || "").trim();
  };

  const saveField = async (key: string, value: string, original: string) => {
    const trimmed = value.trim();
    if (trimmed === (original || "").trim()) {
      setDrafts((d) => {
        const next = { ...d };
        delete next[key];
        return next;
      });
      return;
    }
    setSavingKey(key);
    try {
      await api.updateDs260Field(applicantId, key, trimmed, memberId);
      setDrafts((d) => {
        const next = { ...d };
        delete next[key];
        return next;
      });
      onFieldSaved();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Không thể lưu trường DS-260");
    } finally {
      setSavingKey("");
    }
  };

  const clearOverride = async (key: string) => {
    setSavingKey(key);
    try {
      await api.updateDs260Field(applicantId, key, "");
      setDrafts((d) => {
        const next = { ...d };
        delete next[key];
        return next;
      });
      onFieldSaved();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Không thể xóa chỉnh sửa");
    } finally {
      setSavingKey("");
    }
  };

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {fields.filter((f) => !f.review_hidden).map((f) => {
        const isManual = f.source.derived === "manual_override";
        const busy = savingKey === f.key;
        return (
          <div
            key={f.key}
            className={`rounded-md border p-2 ${
              isManual
                ? "border-amber-300 bg-amber-50/40"
                : canEdit
                  ? "border-slate-200 bg-slate-50/80"
                  : "border-transparent"
            }`}
          >
            <p className="text-xs font-medium text-slate-500">
              {f.label}
              {canEdit && (
                <span className="ml-1.5 font-normal text-brand-600">· có thể sửa</span>
              )}
            </p>
            {canEdit ? (
              <div className="mt-1 flex gap-1">
                <input
                  className="input min-h-0 flex-1 border-brand-200 bg-white py-1.5 font-mono text-sm shadow-sm ring-1 ring-brand-100 focus:ring-brand-400"
                  value={displayValue(f)}
                  disabled={busy}
                  onChange={(e) => setDrafts((d) => ({ ...d, [f.key]: e.target.value }))}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      void saveField(f.key, e.currentTarget.value, f.value);
                    }
                  }}
                />
                <button
                  type="button"
                  title={isDirty(f) ? "Lưu thay đổi" : "Sửa ô trước, rồi bấm Lưu"}
                  className={`shrink-0 rounded-lg px-2.5 py-1.5 text-xs font-semibold ${
                    isDirty(f)
                      ? "btn-primary"
                      : "cursor-default border border-slate-200 bg-slate-100 text-slate-400"
                  }`}
                  disabled={busy || !isDirty(f)}
                  onClick={() => saveField(f.key, displayValue(f), f.value)}
                >
                  {busy ? "…" : "Lưu"}
                </button>
                {isManual && (
                  <button
                    type="button"
                    title="Khôi phục giá trị từ giấy tờ"
                    className="shrink-0 rounded border border-slate-200 px-2 text-xs text-slate-600 hover:bg-slate-50"
                    disabled={busy}
                    onClick={() => clearOverride(f.key)}
                  >
                    ↺
                  </button>
                )}
              </div>
            ) : (
              <p className="mt-0.5 break-words font-mono text-sm text-slate-900">{f.value || "—"}</p>
            )}
            {isManual && (
              <p className="mt-1 text-xs font-medium text-amber-800">Đã chỉnh tay trước export</p>
            )}
            {f.source.derived === "conflict_resolution" && (
              <p className="mt-1 text-xs font-medium text-blue-800">
                Đã chọn từ xung đột (Luồng 1 vs _new)
              </p>
            )}
            {f.source.derived === "worksheet_conflict_resolution" && (
              <p className="mt-1 text-xs font-medium text-blue-800">
                Đã chọn từ xung đột (giấy tờ vs worksheet)
              </p>
            )}
            {(f.source.document_filename || f.source.derived) &&
              f.source.derived !== "manual_override" &&
              f.source.derived !== "conflict_resolution" &&
              f.source.derived !== "worksheet_conflict_resolution" && (
              <p className="mt-1 text-xs text-slate-400">
                {DOC_TYPE_LABELS[f.source.document_type] || f.source.document_type} ·{" "}
                {f.source.source_field}
                {deriveSourceHint(f.source.derived ?? undefined, f.source.source_field || "")}
                {f.source.derived === "no_father_na" && " · không có thông tin cha → N/A"}
                {f.source.derived === "no_mother_na" && " · không có thông tin mẹ → N/A"}
                {f.source.variant === "exception" && " · _new"}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}

function Ds260MemberMappingBlock({
  applicantId,
  member,
  form,
  canEdit,
  onFieldSaved,
  onExport,
  exportBusy,
}: {
  applicantId: string;
  member: CaseMember;
  form: Ds260Form;
  canEdit: boolean;
  onFieldSaved: () => void;
  onExport: (member: CaseMember) => void;
  exportBusy: boolean;
}) {
  const sections = visibleDs260Sections(form.sections, member.role);

  return (
    <section
      id={`ds260-member-${member.id}`}
      className={`scroll-mt-24 rounded-xl border-2 p-4 ring-1 ${memberPanelClass(member.role)}`}
    >
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3 border-b border-slate-200/70 pb-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            {member.member_number ? (
              <span
                className={`mr-2 inline-flex h-7 min-w-[2rem] items-center justify-center rounded-md px-2 text-[11px] font-bold text-white ${memberColorByNumber(member.member_number).badge}`}
              >
                {member.member_number}
              </span>
            ) : null}
            {memberRoleLabel(member.role)}
          </p>
          <h3 className="text-xl font-bold text-slate-900">{member.display_name}</h3>
          <p className="mt-1 text-sm text-slate-600">
            <strong>{form.applicable_filled_count ?? form.filled_count}</strong> /{" "}
            {form.applicable_count ?? form.total_count} trường áp dụng
            {form.applicable_count != null && form.applicable_count < form.total_count && (
              <span className="text-slate-500">
                {" "}
                (tổng mapping {form.filled_count}/{form.total_count})
              </span>
            )}
          </p>
        </div>
        <button
          type="button"
          className="btn-secondary shrink-0"
          disabled={exportBusy}
          onClick={() => onExport(member)}
        >
          {exportBusy ? "Đang xuất…" : `Xuất DS-260 — ${member.display_name}`}
        </button>
      </div>

      {canEdit ? (
        <div className="mb-4 rounded-lg border border-brand-200 bg-brand-50 px-3 py-2 text-sm text-brand-900">
          <strong>Chỉnh sửa DS-260:</strong> mỗi ô có viền xanh và nút <strong>Lưu</strong> bên
          phải (sáng khi đã sửa). Bấm Lưu hoặc Enter để ghi — không có nút lưu chung cho cả bộ.
        </div>
      ) : (
        <div className="mb-4 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
          Chế độ <strong>chỉ xem</strong> — chỉ admin, chủ hồ sơ, hoặc staff được phân công mới
          sửa được.
        </div>
      )}

      <div className="space-y-4">
        {sections.map((sec) => (
          <div key={`${member.id}-${sec.id}`} className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h4 className="font-semibold text-slate-900">{sec.title}</h4>
              <span className="text-xs text-slate-500">
                {sec.filled_count ?? sec.fields.filter((f) => f.value?.trim()).length} /{" "}
                {sec.total_count ?? sec.fields.length}
                {sec.document_missing && (
                  <span className="ml-2 rounded bg-slate-100 px-1.5 py-0.5 text-slate-600">
                    chưa có tài liệu
                  </span>
                )}
                {!sec.document_missing &&
                  sec.applicable_count != null &&
                  sec.applicable_filled_count != null &&
                  sec.applicable_count < (sec.total_count ?? sec.fields.length) && (
                    <span className="ml-2 text-slate-400">
                      ({sec.applicable_filled_count}/{sec.applicable_count} áp dụng)
                    </span>
                  )}
              </span>
            </div>
            {sec.subtitle && <p className="mt-0.5 text-xs text-slate-500">{sec.subtitle}</p>}
            <div className="mt-3">
              <Ds260FieldGrid
                applicantId={applicantId}
                memberId={member.id === PRINCIPAL_ONLY_ID ? undefined : member.id}
                fields={sec.fields}
                canEdit={canEdit}
                onFieldSaved={onFieldSaved}
              />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function fieldKeysForRecord(rec: DocRecord, extractKeys: string[]): string[] {
  const keys: string[] = [];
  const seen = new Set<string>();
  for (const k of extractKeys) {
    keys.push(k);
    seen.add(k);
  }
  for (const k of Object.keys(rec.form_data).sort()) {
    if (!seen.has(k)) keys.push(k);
  }
  return keys;
}

function DocumentTablePanel({
  applicantId,
  docType,
  records,
  label,
  emptyHint,
  alwaysShow = false,
  defaultOpen = false,
  canEdit,
  fieldLabels,
  extractKeys,
  onFieldSaved,
}: {
  applicantId: string;
  docType: string;
  records: DocRecord[];
  label?: string;
  emptyHint?: string;
  alwaysShow?: boolean;
  defaultOpen?: boolean;
  canEdit: boolean;
  fieldLabels: Record<string, string>;
  extractKeys: string[];
  onFieldSaved: () => void;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [savingKey, setSavingKey] = useState("");

  if (records.length === 0 && !alwaysShow) return null;
  const title = label || DOC_TYPE_LABELS[docType] || docType;

  const saveField = async (
    recordId: string,
    fieldKey: string,
    value: string,
    original: string
  ) => {
    const trimmed = value.trim();
    const draftId = `${recordId}:${fieldKey}`;
    if (trimmed === (original || "").trim()) {
      setDrafts((d) => {
        const next = { ...d };
        delete next[draftId];
        return next;
      });
      return;
    }
    setSavingKey(draftId);
    try {
      await api.updateDocRecordField(applicantId, recordId, fieldKey, trimmed);
      setDrafts((d) => {
        const next = { ...d };
        delete next[draftId];
        return next;
      });
      onFieldSaved();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Không thể lưu trường giấy tờ");
    } finally {
      setSavingKey("");
    }
  };

  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <button
        type="button"
        className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-medium"
        onClick={() => setOpen((v) => !v)}
      >
        <span>
          {title}{" "}
          <span className="font-normal text-slate-500">({records.length} file)</span>
        </span>
        <span className="text-slate-400">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="space-y-3 border-t border-slate-100 px-4 pb-4 pt-3">
          {records.length === 0 ? (
            <p className="text-sm text-slate-500">{emptyHint || "Chưa có file — upload tại trang Upload."}</p>
          ) : (
            records.map((rec) => (
              <div key={rec.id} className="rounded border border-slate-100 bg-slate-50/50 p-3">
                <div className="mb-2 flex flex-wrap gap-2 text-xs text-slate-600">
                  {rec.variant === "exception" && (
                    <span className="rounded bg-amber-100 px-2 py-0.5 text-amber-900">Đối chiếu (_new)</span>
                  )}
                  {rec.variant === "standard" && (
                    <span className="rounded bg-green-100 px-2 py-0.5 text-green-900">Luồng 1 (mẫu)</span>
                  )}
                  {rec.source_document_filename && <span>📄 {rec.source_document_filename}</span>}
                </div>
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {fieldKeysForRecord(rec, extractKeys).map((k) => {
                    const draftId = `${rec.id}:${k}`;
                    const original = rec.form_data[k] || "";
                    const display =
                      drafts[draftId] !== undefined ? drafts[draftId] : original;
                    const busy = savingKey === draftId;
                    const dirty =
                      drafts[draftId] !== undefined &&
                      drafts[draftId].trim() !== (original || "").trim();
                    const fieldLabel = fieldLabels[k] || k.replace(/_/g, " ");
                    return (
                      <div key={k}>
                        <p className="text-xs text-slate-500">{fieldLabel}</p>
                        <p className="text-[10px] text-slate-400">{k}</p>
                        {canEdit ? (
                          <div className="mt-0.5 flex gap-1">
                            <input
                              className="input min-h-0 w-full flex-1 py-1.5 font-mono text-sm"
                              value={display}
                              disabled={busy}
                              onChange={(e) =>
                                setDrafts((d) => ({ ...d, [draftId]: e.target.value }))
                              }
                              onKeyDown={(e) => {
                                if (e.key === "Enter") {
                                  void saveField(rec.id, k, e.currentTarget.value, original);
                                }
                              }}
                            />
                            <button
                              type="button"
                              title={dirty ? "Lưu thay đổi" : "Sửa ô trước, rồi bấm Lưu"}
                              className={`shrink-0 rounded-lg px-2 py-1 text-xs font-semibold ${
                                dirty
                                  ? "btn-primary"
                                  : "cursor-default border border-slate-200 bg-slate-100 text-slate-400"
                              }`}
                              disabled={busy || !dirty}
                              onClick={() => saveField(rec.id, k, display, original)}
                            >
                              {busy ? "…" : "Lưu"}
                            </button>
                          </div>
                        ) : (
                          <p className="mt-0.5 font-mono text-sm text-slate-800">{original || "—"}</p>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

const PROTECTED_FORM_TEMPLATES = new Set(["ds160_worksheet", "i539_worksheet"]);

export default function ReviewPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [userRole, setUserRole] = useState<User["role"]>("user");
  const [currentUserId, setCurrentUserId] = useState("");
  const [applicant, setApplicant] = useState<Applicant | null>(null);
  const [ds260Form, setDs260Form] = useState<Ds260Form | null>(null);
  const [ds260FormsByMember, setDs260FormsByMember] = useState<Record<string, Ds260Form>>({});
  const [ds260Validation, setDs260Validation] = useState<Ds260Validation | null>(null);
  const [docTables, setDocTables] = useState<DocTableSummary[]>([]);
  const [referenceTables, setReferenceTables] = useState<DocTableSummary[]>([]);
  const [docRecordsByType, setDocRecordsByType] = useState<Record<string, DocRecord[]>>({});
  const [referenceRecordsByType, setReferenceRecordsByType] = useState<Record<string, DocRecord[]>>({});
  const [templates, setTemplates] = useState<FormTemplate[]>([]);
  const [ds260TemplateCode, setDs260TemplateCode] = useState(DS260_DEFAULT_TEMPLATE_CODE);
  const [templateCode, setTemplateCode] = useState("");
  const [templateName, setTemplateName] = useState("");
  const [ds260Conflicts, setDs260Conflicts] = useState<Conflict[]>([]);
  const [conflictBusy, setConflictBusy] = useState("");
  const [busy, setBusy] = useState("");
  const [caseMembers, setCaseMembers] = useState<CaseMember[]>([]);
  const [selectedMemberId, setSelectedMemberId] = useState<string>("");
  const [setupPrincipalName, setSetupPrincipalName] = useState("");
  const [setupSpouseName, setSetupSpouseName] = useState("");
  const [setupChildNames, setSetupChildNames] = useState("");
  const [appendChildNames, setAppendChildNames] = useState("");
  const [appendSpouseName, setAppendSpouseName] = useState("");
  const [editingMemberNames, setEditingMemberNames] = useState<Record<string, string>>({});
  const [reviewTab, setReviewTab] = useState<"ds260" | "documents">("ds260");
  const [docTypes, setDocTypes] = useState<DocumentTypeGuide[]>([]);
  const templateFileRef = useRef<HTMLInputElement>(null);

  const hasSpouseMember = caseMembers.some((m) => m.role === "spouse");

  const ds260DisplayMembers = useMemo(
    () => buildDs260DisplayMembers(caseMembers, applicant),
    [caseMembers, applicant]
  );

  const reloadMembers = useCallback(async () => {
    try {
      const members = await api.listCaseMembers(id);
      setCaseMembers(members);
      if (members.length > 0) {
        setSelectedMemberId((prev) => {
          if (prev && members.some((m) => m.id === prev)) return prev;
          return (members.find((m) => m.role === "principal") || members[0]).id;
        });
      }
      return members;
    } catch {
      setCaseMembers([]);
      return [];
    }
  }, [id]);

  const load = useCallback(async () => {
    const members = await api.listCaseMembers(id).catch(() => [] as CaseMember[]);
    setCaseMembers(members);
    if (members.length > 0) {
      setSelectedMemberId((prev) => {
        if (prev && members.some((m) => m.id === prev)) return prev;
        return (members.find((m) => m.role === "principal") || members[0]).id;
      });
    }

    const ds260Promises =
      members.length > 0
        ? members.map((m) => api.getDs260Form(id, m.id).catch(() => null))
        : [api.getDs260Form(id).catch(() => null)];

    const [user, app, tpls, validation, tables, refTables, conflicts, ...ds260Results] =
      await Promise.all([
        api.me(),
        api.getApplicant(id),
        api.listTemplates(),
        api.getDs260Validation(id).catch(() => null),
        api.listDocumentTables(id).catch(() => [] as DocTableSummary[]),
        api.listReferenceDocumentTables(id).catch(() => [] as DocTableSummary[]),
        api.getDs260Conflicts(id).catch(() => [] as Conflict[]),
        ...ds260Promises,
      ]);

    const byMember: Record<string, Ds260Form> = {};
    if (members.length > 0) {
      members.forEach((m, i) => {
        const form = ds260Results[i] as Ds260Form | null;
        if (form) byMember[m.id] = form;
      });
      setDs260FormsByMember(byMember);
      const principal = members.find((m) => m.role === "principal") || members[0];
      setDs260Form(byMember[principal.id] ?? null);
    } else {
      setDs260FormsByMember({});
      setDs260Form((ds260Results[0] as Ds260Form | null) ?? null);
    }
    setEmail(user.email);
    setUserRole(user.role);
    setCurrentUserId(user.id);
    setApplicant(app);
    setTemplates(tpls);
    setDs260Validation(validation);
    setDs260Conflicts(conflicts);
    setDocTables(tables);
    setReferenceTables(refTables);

    const withStandard = tables.filter((t) => (t.standard_count ?? t.record_count) > 0);
    const standardSets = await Promise.all(
      withStandard.map((t) =>
        api.getDocumentTable(id, t.doc_type, "standard").catch(() => [] as DocRecord[])
      )
    );
    const byType: Record<string, DocRecord[]> = {};
    withStandard.forEach((t, i) => {
      byType[t.doc_type] = standardSets[i];
    });
    setDocRecordsByType(byType);

    const refSets = await Promise.all(
      refTables.map((t) =>
        api.getDocumentTable(id, t.doc_type, "exception").catch(() => [] as DocRecord[])
      )
    );
    const refByType: Record<string, DocRecord[]> = {};
    refTables.forEach((t, i) => {
      refByType[t.doc_type] = refSets[i];
    });
    setReferenceRecordsByType(refByType);
  }, [id]);

  useEffect(() => {
    reloadMembers().catch(() => undefined);
    api.listDocumentTypes().then(setDocTypes).catch(() => undefined);
  }, [reloadMembers]);

  useEffect(() => {
    if (applicant?.display_name && !setupPrincipalName) {
      setSetupPrincipalName(applicant.display_name);
    }
  }, [applicant?.display_name, setupPrincipalName]);

  useEffect(() => {
    const map: Record<string, string> = {};
    caseMembers.forEach((m) => {
      map[m.id] = m.display_name;
    });
    setEditingMemberNames(map);
  }, [caseMembers]);

  useEffect(() => {
    if (setupSpouseName || caseMembers.length > 0) return;
    const marriage = docRecordsByType.marriage_certificate?.[0];
    const fd = marriage?.form_data || {};
    const husband = (fd.husband_full_name || fd.husband_name || "").trim();
    const wife = (fd.wife_full_name || fd.wife_name || "").trim();
    const principal = (applicant?.display_name || setupPrincipalName || "").trim();
    const norm = (s: string) => s.toUpperCase().replace(/\s+/g, " ");
    let spouse = "";
    if (husband && wife) {
      if (principal && norm(husband) === norm(principal)) spouse = wife;
      else if (principal && norm(wife) === norm(principal)) spouse = husband;
    }
    if (spouse) setSetupSpouseName(spouse);
  }, [docRecordsByType, applicant?.display_name, setupPrincipalName, setupSpouseName, caseMembers.length]);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    load().catch(() => router.replace("/dashboard"));
  }, [load, router]);

  const resolveDs260Conflict = async (conflictId: string, value: string) => {
    setConflictBusy(conflictId);
    try {
      await api.resolveConflict(id, conflictId, value);
      await load();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Không thể giải quyết xung đột");
    } finally {
      setConflictBusy("");
    }
  };

  const approve = async () => {
    if (ds260Validation && !ds260Validation.valid) {
      alert(
        `DS260 chưa hợp lệ (${ds260Validation.error_count} lỗi). Sửa lỗi trước khi duyệt.\n\n` +
          ds260Validation.errors.map((e) => `• ${e.message}`).join("\n")
      );
      return;
    }
    setBusy("approve");
    try {
      const res = await api.approveReview(id);
      alert(res.message || "Đã duyệt");
      await load();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Không thể duyệt");
    } finally {
      setBusy("");
    }
  };

  const exportFilenameForMember = (name: string) => {
    const safe = name.replace(/[^\w\s-]+/g, "").trim().replace(/\s+/g, "_") || "member";
    return `ds260_${safe}.docx`;
  };

  const confirmSkipValidation = () => {
    if (!ds260Validation || ds260Validation.valid) return true;
    return window.confirm(
      `DS260 có ${ds260Validation.error_count} lỗi. Vẫn xuất file nháp?\n\n` +
        ds260Validation.errors.map((e) => `• ${e.message}`).slice(0, 5).join("\n")
    );
  };

  const exportDs260ForMember = async (member: CaseMember) => {
    if (!confirmSkipValidation()) return;

    setBusy(`export-ds260-${member.id}`);
    try {
      const result = await api.exportDs260(id, Boolean(ds260Validation && !ds260Validation.valid), ds260TemplateCode, member.id);
      await api.downloadExportFile(
        result.id,
        result.download_url,
        exportFilenameForMember(member.display_name)
      );
      await load();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Xuất DS260 thất bại");
    } finally {
      setBusy("");
    }
  };

  const saveFamilyMembers = async () => {
    const principal = setupPrincipalName.trim() || applicant?.display_name?.trim() || "";
    const spouse = setupSpouseName.trim();
    const children = setupChildNames
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    if (!principal) {
      alert("Nhập tên chủ hồ sơ");
      return;
    }
    if (!spouse && children.length === 0) {
      alert("Nhập tên vợ/chồng hoặc ít nhất một con");
      return;
    }

    const members: { role: "principal" | "spouse" | "child"; display_name: string }[] = [
      { role: "principal", display_name: principal },
    ];
    if (spouse) members.push({ role: "spouse", display_name: spouse });
    children.forEach((name) => members.push({ role: "child", display_name: name }));

    setBusy("save-members");
    try {
      const saved = await api.setCaseMembers(id, members);
      setCaseMembers(saved);
      setSelectedMemberId((saved.find((m) => m.role === "principal") || saved[0]).id);
      await load();
      alert(`Đã thiết lập ${saved.length} thành viên. Bạn có thể tải DS-260 riêng cho từng người bên dưới.`);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Không thể lưu thành viên");
    } finally {
      setBusy("");
    }
  };

  const appendFamilyMembers = async () => {
    const spouse = appendSpouseName.trim();
    const children = appendChildNames
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    if (!spouse && children.length === 0) {
      alert("Nhập tên con mới hoặc phối ngẫu cần bổ sung");
      return;
    }
    if (spouse && hasSpouseMember) {
      alert("Hồ sơ đã có phối ngẫu. Chỉ có thể thêm con.");
      return;
    }

    const toAdd: { role: "spouse" | "child"; display_name: string }[] = [];
    if (spouse && !hasSpouseMember) toAdd.push({ role: "spouse", display_name: spouse });
    children.forEach((name) => toAdd.push({ role: "child", display_name: name }));

    setBusy("append-members");
    try {
      const saved = await api.addCaseMembers(id, toAdd);
      setCaseMembers(saved);
      setAppendChildNames("");
      setAppendSpouseName("");
      await load();
      alert(`Đã bổ sung ${toAdd.length} thành viên. Tổng ${saved.length} người trong hồ sơ.`);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Không thể bổ sung thành viên");
    } finally {
      setBusy("");
    }
  };

  const saveMemberName = async (member: CaseMember) => {
    const name = (editingMemberNames[member.id] || "").trim();
    if (!name) {
      alert("Tên không được để trống");
      return;
    }
    if (name === member.display_name) return;

    setBusy(`save-member-${member.id}`);
    try {
      await api.updateCaseMember(id, member.id, name);
      await reloadMembers();
      await load();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Không thể lưu tên");
    } finally {
      setBusy("");
    }
  };

  const deleteMember = async (member: CaseMember) => {
    if (member.role === "principal") return;
    const ok = window.confirm(
      `Xóa ${memberRoleLabel(member.role)} "${member.display_name}" khỏi hồ sơ?\n\nChỉ xóa khi nhầm người / hồ sơ test.`
    );
    if (!ok) return;

    setBusy(`delete-member-${member.id}`);
    try {
      const res = await api.deleteCaseMember(id, member.id);
      await reloadMembers();
      await load();
      alert(res.message || "Đã xóa");
    } catch (err) {
      alert(err instanceof Error ? err.message : "Không thể xóa thành viên");
    } finally {
      setBusy("");
    }
  };

  const exportDs260 = async () => {
    if (!confirmSkipValidation()) return;

    setBusy("export-ds260");
    try {
      const memberId = selectedMemberId || undefined;
      const member = caseMembers.find((m) => m.id === memberId);
      const result = await api.exportDs260(id, Boolean(ds260Validation && !ds260Validation.valid), ds260TemplateCode, memberId);
      const label = member?.display_name || applicant?.display_name || id;
      await api.downloadExportFile(result.id, result.download_url, exportFilenameForMember(label));
      await load();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Xuất DS260 thất bại");
    } finally {
      setBusy("");
    }
  };

  const exportDs260Batch = async () => {
    const skipValidation =
      ds260Validation &&
      !ds260Validation.valid &&
      window.confirm(`Một số trường chưa hợp lệ. Vẫn xuất tất cả thành viên?`);
    if (ds260Validation && !ds260Validation.valid && !skipValidation) return;

    setBusy("export-ds260-batch");
    try {
      const result = await api.exportDs260Batch(id, Boolean(skipValidation), ds260TemplateCode);
      for (const exp of result.exports) {
        const name = exp.member_name || caseMembers.find((m) => m.id === exp.member_id)?.display_name || exp.id;
        await api.downloadExportFile(exp.id, exp.download_url, exportFilenameForMember(name));
      }
      if (result.failed.length) {
        alert(
          `Đã xuất ${result.exports.length} file. Lỗi:\n` +
            result.failed.map((f) => `• ${f.member}: ${f.error}`).join("\n")
        );
      }
      await load();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Xuất hàng loạt thất bại");
    } finally {
      setBusy("");
    }
  };

  const deleteFormTemplate = async (tpl: FormTemplate) => {
    if (PROTECTED_FORM_TEMPLATES.has(tpl.code)) {
      alert("Không thể xóa template hệ thống mặc định.");
      return;
    }
    if (!confirm(`Xóa mẫu form "${tpl.name}" (${tpl.code})?\n\nFile .docx trên server cũng sẽ bị xóa.`)) return;
    setBusy(`del-tpl-${tpl.id}`);
    try {
      const res = await api.deleteFormTemplate(tpl.id);
      alert(res.message || "Đã xóa");
      const tpls = await api.listTemplates();
      setTemplates(tpls);
      if (ds260TemplateCode === tpl.code) {
        const next = tpls.find(isDs260FormTemplate)?.code || DS260_DEFAULT_TEMPLATE_CODE;
        setDs260TemplateCode(next);
      }
    } catch (err) {
      alert(err instanceof Error ? err.message : "Không thể xóa mẫu form");
    } finally {
      setBusy("");
    }
  };

  const uploadTemplate = async (file: File) => {
    const rawCode = templateCode.trim() || templateName.trim();
    if (!rawCode) {
      alert("Nhập mã form (vd: ds260_eb3_hang_1) hoặc tên hiển thị");
      return;
    }
    const code = normalizeDs260TemplateCode(rawCode);
    const displayName = templateName.trim() || templateCode.trim() || code.replace(/_/g, " ");
    setBusy("template");
    try {
      const t = await api.uploadFormTemplate(code, displayName, file);
      setTemplates((prev) => {
        const exists = prev.find((x) => x.code === t.code);
        if (exists) return prev.map((x) => (x.code === t.code ? t : x));
        return [...prev, t];
      });
      setDs260TemplateCode(t.code);
      alert(`Đã upload mẫu DS-260: ${t.name}`);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Upload mẫu thất bại");
    } finally {
      setBusy("");
    }
  };

  const exportZip = async () => {
    setBusy("zip");
    try {
      await api.downloadApplicantZip(id);
    } catch (err) {
      alert(err instanceof Error ? err.message : "ZIP thất bại");
    } finally {
      setBusy("");
    }
  };

  const deleteApplicant = async () => {
    if (!applicant) return;
    const ok = window.confirm(
      `Xóa vĩnh viễn hồ sơ "${applicant.display_name}"?\n\nToàn bộ dữ liệu trong database (giấy tờ, OCR, DS-260, thành viên gia đình) và file upload sẽ bị xóa. Không thể hoàn tác.`
    );
    if (!ok) return;
    setBusy("delete");
    try {
      await api.deleteApplicant(id, { permanent: true, force: true });
      router.push("/dashboard");
    } catch (err) {
      alert(err instanceof Error ? err.message : "Không thể xóa hồ sơ");
    } finally {
      setBusy("");
    }
  };

  const canEditDs260 =
    userRole === "admin" ||
    (userRole === "user" && !!applicant) ||
    (userRole === "staff" &&
      !!applicant?.assigned_staff_id &&
      applicant.assigned_staff_id === currentUserId);

  const docTypeMeta = (code: string) => {
    const guide = docTypes.find((t) => t.code === code);
    return {
      fieldLabels: guide?.field_labels || {},
      extractKeys: guide?.extract_keys || [],
    };
  };

  return (
    <div>
      <main className="mx-auto max-w-6xl">
        <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <Link href="/dashboard" className="text-sm text-accent hover:underline">
              ← Quay lại
            </Link>
            <h1 className="mt-2 text-2xl font-bold">Review Dashboard</h1>
            {applicant && (
              <p className="text-slate-500">
                {applicant.display_name} · <StatusBadge status={applicant.status} />
                {caseMembers.length > 0 ? (
                  <span className="ml-2 rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-800">
                    Gia đình: {caseMembers.length} người
                  </span>
                ) : (
                  <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-900">
                    Chưa thiết lập vợ/con — xem bên dưới
                  </span>
                )}
              </p>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            <Link href={`/applicants/${id}/upload`} className="btn-secondary">
              ← Upload thêm
            </Link>
            <button
              type="button"
              className="btn-secondary text-red-700 hover:border-red-200 hover:bg-red-50"
              disabled={busy === "delete"}
              onClick={deleteApplicant}
            >
              {busy === "delete" ? "Đang xóa…" : "Xóa hồ sơ"}
            </button>
          </div>
        </div>

        {caseMembers.length === 0 ? (
          <div id="family-download" className="card mb-6 border-amber-300 bg-amber-50/80 ring-1 ring-amber-200">
            <h2 className="text-lg font-semibold text-slate-900">Bước 1 — Thiết lập thành viên gia đình</h2>
            <p className="mt-1 text-sm text-slate-600">
              Hồ sơ <strong>{applicant?.display_name || "này"}</strong> hiện chỉ xuất được DS-260 cho chủ hồ sơ.
              Để <strong>tải DS-260 cho vợ và các con</strong>, nhập tên bên dưới rồi bấm Lưu — các nút tải riêng
              sẽ hiện ngay phía dưới.
            </p>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div>
                <label className="label">Chủ hồ sơ / Chồng</label>
                <input
                  className="input"
                  value={setupPrincipalName}
                  onChange={(e) => setSetupPrincipalName(e.target.value)}
                  placeholder="DANG VAN HUNG"
                />
              </div>
              <div>
                <label className="label">Vợ / Chồng (phối ngẫu)</label>
                <input
                  className="input"
                  value={setupSpouseName}
                  onChange={(e) => setSetupSpouseName(e.target.value)}
                  placeholder="MAI THI HUONG"
                />
              </div>
              <div className="sm:col-span-2">
                <label className="label">Các con (phân cách bằng dấu phẩy)</label>
                <input
                  className="input"
                  value={setupChildNames}
                  onChange={(e) => setSetupChildNames(e.target.value)}
                  placeholder="NGUYEN VAN A, NGUYEN THI B"
                />
              </div>
            </div>
            <button
              type="button"
              className="btn-primary mt-4"
              disabled={busy === "save-members"}
              onClick={saveFamilyMembers}
            >
              {busy === "save-members" ? "Đang lưu…" : "Lưu thành viên & bật xuất DS-260 từng người"}
            </button>
          </div>
        ) : (
          <div id="family-download" className="card mb-6 border-emerald-200 bg-emerald-50/40">
            <h2 className="text-lg font-semibold text-slate-900">Tải DS-260 (Word) theo từng người</h2>
            <p className="mt-1 text-sm text-slate-600">
              Mỗi nút tạo và tải file Word riêng. Đặt tên file passport theo từng người (vd.{" "}
              <code className="rounded bg-white px-1">PASSPORT - MAI THI HUONG.pdf</code>) để OCR đúng dữ
              liệu.
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              {caseMembers.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  className="btn-secondary"
                  disabled={busy === `export-ds260-${m.id}` || busy === "export-ds260-batch"}
                  onClick={() => exportDs260ForMember(m)}
                >
                  {busy === `export-ds260-${m.id}`
                    ? "Đang xuất…"
                    : `Tải DS-260 — ${memberRoleLabel(m.role)}: ${m.display_name}`}
                </button>
              ))}
              {caseMembers.length > 1 && (
                <button
                  type="button"
                  className="btn-primary"
                  disabled={busy === "export-ds260-batch" || caseMembers.some((m) => busy === `export-ds260-${m.id}`)}
                  onClick={exportDs260Batch}
                >
                  {busy === "export-ds260-batch"
                    ? "Đang xuất tất cả…"
                    : `Tải tất cả (${caseMembers.length} file)`}
                </button>
              )}
            </div>

            <div className="mt-5 rounded-lg border border-slate-200 bg-white p-4">
              <h3 className="text-sm font-semibold text-slate-900">Chỉnh sửa tên thành viên</h3>
              <p className="mt-1 text-xs text-slate-600">
                Sửa nếu gõ sai (vd. <strong>Dinh</strong> → <strong>Dang</strong>). Tên phải khớp tên trên
                file upload (PASSPORT, giấy khai sinh…).
              </p>
              <div className="mt-3 space-y-2">
                {caseMembers.map((m) => {
                  const dirty =
                    (editingMemberNames[m.id] || "").trim() !== m.display_name.trim();
                  return (
                    <div
                      key={m.id}
                      className="flex flex-col gap-2 rounded-md border border-slate-100 bg-slate-50/80 p-3 sm:flex-row sm:items-end"
                    >
                      <div className="min-w-[120px] text-sm font-medium text-slate-700">
                        {memberRoleLabel(m.role)}
                      </div>
                      <div className="flex-1">
                        <input
                          className="input"
                          value={editingMemberNames[m.id] ?? m.display_name}
                          onChange={(e) =>
                            setEditingMemberNames((prev) => ({ ...prev, [m.id]: e.target.value }))
                          }
                          placeholder="Họ tên IN HOA"
                        />
                      </div>
                      <button
                        type="button"
                        className="btn-secondary shrink-0"
                        disabled={!dirty || busy === `save-member-${m.id}`}
                        onClick={() => saveMemberName(m)}
                      >
                        {busy === `save-member-${m.id}` ? "Đang lưu…" : "Lưu tên"}
                      </button>
                      {m.role !== "principal" && (
                        <button
                          type="button"
                          className="btn-secondary shrink-0 text-red-700 hover:border-red-200 hover:bg-red-50"
                          disabled={busy === `delete-member-${m.id}`}
                          onClick={() => deleteMember(m)}
                        >
                          {busy === `delete-member-${m.id}` ? "…" : "Xóa"}
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="mt-5 rounded-lg border border-slate-200 bg-white p-4">
              <h3 className="text-sm font-semibold text-slate-900">Bổ sung thành viên</h3>
              <p className="mt-1 text-xs text-slate-600">
                Tạo hồ sơ thiếu con hoặc thiếu vợ? Thêm tên mới tại đây — thành viên cũ giữ nguyên, không
                cần tạo hồ sơ mới.
              </p>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                {!hasSpouseMember && (
                  <div>
                    <label className="label">Thêm phối ngẫu (nếu chưa có)</label>
                    <input
                      className="input"
                      value={appendSpouseName}
                      onChange={(e) => setAppendSpouseName(e.target.value)}
                      placeholder="MAI THI HUONG"
                    />
                  </div>
                )}
                <div className={hasSpouseMember ? "sm:col-span-2" : ""}>
                  <label className="label">Thêm con (phân cách bằng dấu phẩy)</label>
                  <input
                    className="input"
                    value={appendChildNames}
                    onChange={(e) => setAppendChildNames(e.target.value)}
                    placeholder="DANG MAI PHUONG THAO, DANG MAI PHUONG LINH"
                  />
                </div>
              </div>
              <button
                type="button"
                className="btn-secondary mt-3"
                disabled={busy === "append-members"}
                onClick={appendFamilyMembers}
              >
                {busy === "append-members" ? "Đang thêm…" : "Thêm vào hồ sơ"}
              </button>
            </div>
          </div>
        )}

        <div className="mb-6 flex flex-wrap gap-2 border-b border-slate-200 pb-1">
          <button
            type="button"
            className={`rounded-t-lg px-4 py-2 text-sm font-medium ${
              reviewTab === "ds260"
                ? "border border-b-white border-slate-200 bg-white text-brand-700"
                : "text-slate-600 hover:bg-slate-50"
            }`}
            onClick={() => setReviewTab("ds260")}
          >
            DS-260 — mapping & xuất
          </button>
          <button
            type="button"
            className={`rounded-t-lg px-4 py-2 text-sm font-medium ${
              reviewTab === "documents"
                ? "border border-b-white border-slate-200 bg-white text-brand-700"
                : "text-slate-600 hover:bg-slate-50"
            }`}
            onClick={() => setReviewTab("documents")}
          >
            Giấy tờ OCR — từng file
          </button>
        </div>

        {reviewTab === "ds260" && ds260Form && ds260DisplayMembers.length === 1 && caseMembers.length === 0 && (
          <p className="mb-4 text-sm text-slate-600">
            DS-260: <strong>{ds260Form.filled_count}</strong> / {ds260Form.total_count} trường
            {ds260Form.applicable_count != null && ds260Form.applicable_count < ds260Form.total_count && (
              <>
                {" "}
                — <strong>{ds260Form.applicable_filled_count ?? ds260Form.filled_count}</strong> /{" "}
                {ds260Form.applicable_count} trường áp dụng
              </>
            )}
            .
          </p>
        )}

        {reviewTab === "ds260" && caseMembers.length > 1 && (
          <p className="mb-4 text-sm text-slate-600">
            Bộ hồ sơ gia đình: <strong>{caseMembers.length} người</strong> — mỗi khối bên dưới là DS-260
            riêng (passport/GKS khớp tên từng người).
          </p>
        )}

        {reviewTab === "ds260" && (
          <>
            <div className="card mb-6 border-brand-200 bg-brand-50/30">
              <h2 className="text-lg font-semibold text-slate-900">DS-260 — Fill từ Document Mapping</h2>
              <p className="mt-1 text-sm text-slate-600">
                Mỗi trường DS260 = <code className="rounded bg-white px-1">documents[loại][field]</code>.
                Passport và Birth certificate có thể cùng tên field nhưng lưu riêng — không gộp.
                File <code className="rounded bg-white px-1">_new</code> = cùng loại, lấy bản mới nhất.
                {canEditDs260 && (
                  <>
                    {" "}
                    Sửa từng ô → bấm nút <strong>Lưu</strong> cạnh ô (hoặc phím Enter). Không có nút lưu
                    chung — mỗi trường lưu riêng. Giá trị chỉnh tay ưu tiên hơn OCR khi xuất Word.
                  </>
                )}
              </p>

              {!ds260Form && ds260DisplayMembers.length === 0 ? (
                <p className="mt-4 text-sm text-amber-800">Đang tải dữ liệu DS-260…</p>
              ) : ds260DisplayMembers.length > 0 ? (
                <div className="mt-4 space-y-8">
                  {ds260DisplayMembers.length > 1 && (
                    <nav className="flex flex-wrap gap-2 rounded-lg border border-slate-200 bg-white p-3">
                      <span className="w-full text-xs font-medium text-slate-500">Nhảy tới:</span>
                      {ds260DisplayMembers.map((m) => (
                        <a
                          key={m.id}
                          href={`#ds260-member-${m.id}`}
                          className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-sm text-slate-700 hover:bg-white hover:text-brand-700"
                        >
                          {memberRoleLabel(m.role)} — {m.display_name}
                        </a>
                      ))}
                    </nav>
                  )}
                  {ds260DisplayMembers.map((m) => {
                    const form = ds260FormForMember(m, ds260FormsByMember, ds260Form);
                    if (!form) {
                      return (
                        <div
                          key={m.id}
                          className="rounded-xl border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-500"
                        >
                          Đang tải DS-260 cho {m.display_name}…
                        </div>
                      );
                    }
                    return (
                      <Ds260MemberMappingBlock
                        key={m.id}
                        applicantId={id}
                        member={m}
                        form={form}
                        canEdit={canEditDs260}
                        onFieldSaved={load}
                        onExport={(member) => {
                          if (member.id === PRINCIPAL_ONLY_ID) void exportDs260();
                          else void exportDs260ForMember(member);
                        }}
                        exportBusy={
                          m.id === PRINCIPAL_ONLY_ID
                            ? busy === "export-ds260"
                            : busy === `export-ds260-${m.id}`
                        }
                      />
                    );
                  })}
                </div>
              ) : (
                <p className="mt-4 text-sm text-amber-800">Chưa có cấu hình mapping DS-260.</p>
              )}
            </div>

            <Ds260ConflictPanel
              conflicts={ds260Conflicts}
              onResolve={resolveDs260Conflict}
              busyId={conflictBusy}
            />

            {ds260Validation && (
          <div
            className={`card mb-6 ${
              ds260Validation.valid
                ? "border-green-200 bg-green-50/40"
                : "border-red-200 bg-red-50/40"
            }`}
          >
            <h2 className="text-lg font-semibold text-slate-900">
              Validate DS-260{" "}
              {ds260Validation.valid ? (
                <span className="text-sm font-normal text-green-700">✓ Hợp lệ</span>
              ) : (
                <span className="text-sm font-normal text-red-700">
                  ✗ {ds260Validation.error_count} lỗi
                </span>
              )}
            </h2>
            {ds260Validation.warning_count > 0 && (
              <p className="mt-1 text-sm text-amber-800">
                {ds260Validation.warning_count} cảnh báo — nên kiểm tra trước khi nộp
              </p>
            )}
            {ds260Validation.errors.length > 0 && (
              <ul className="mt-3 space-y-1 text-sm text-red-800">
                {ds260Validation.errors.map((e, i) => (
                  <li key={`err-${i}`}>• {e.message}</li>
                ))}
              </ul>
            )}
            {ds260Validation.warnings.length > 0 && (
              <ul className="mt-3 space-y-1 text-sm text-amber-900">
                {ds260Validation.warnings.map((w, i) => (
                  <li key={`warn-${i}`}>⚠ {w.message}</li>
                ))}
              </ul>
            )}
            <div className="mt-4 flex flex-wrap items-end gap-3">
              <div className="min-w-[200px] flex-1">
                <label className="label text-xs">Mẫu DS-260</label>
                <select
                  className="input"
                  value={ds260TemplateCode}
                  onChange={(e) => setDs260TemplateCode(e.target.value)}
                >
                  {listDs260FormTemplates(templates).map((t) => (
                      <option key={t.code} value={t.code}>
                        {t.name || t.code}
                      </option>
                    ))}
                </select>
              </div>
              <button
                type="button"
                className="btn-primary"
                disabled={busy === "export-ds260"}
                onClick={exportDs260}
              >
                {busy === "export-ds260"
                  ? "Đang xuất DS-260…"
                  : caseMembers.length > 0 && selectedMemberId
                    ? `Xuất DS-260 — ${
                        caseMembers.find((m) => m.id === selectedMemberId)?.display_name || "đang chọn"
                      }`
                    : "Xuất DS-260 (Word)"}
              </button>
              {caseMembers.length > 1 && (
                <button
                  type="button"
                  className="btn-secondary"
                  disabled={busy === "export-ds260-batch"}
                  onClick={exportDs260Batch}
                >
                  {busy === "export-ds260-batch"
                    ? "Đang xuất tất cả…"
                    : `Xuất tất cả (${caseMembers.length} người)`}
                </button>
              )}
              <button
                type="button"
                className="btn-secondary"
                disabled={busy === "approve" || !ds260Validation.valid}
                onClick={approve}
              >
                {busy === "approve" ? "..." : "Duyệt DS-260"}
              </button>
            </div>
          </div>
        )}

            <div className="card mt-6 border-blue-100 bg-blue-50/50">
              <h2 className="mb-2 font-semibold">Upload mẫu Word DS-260 (output)</h2>
              <p className="mb-4 text-sm text-slate-600">
                File form Word cần điền từ dữ liệu giấy tờ (label như{" "}
                <code className="rounded bg-white px-1">Date of Birth</code>,{" "}
                <code className="rounded bg-white px-1">Passport ID</code>).
              </p>
              <div className="grid gap-3 sm:grid-cols-3">
                <div>
                  <label className="label">Mã form</label>
                  <input
                    className="input"
                    placeholder="vd: ds260_eb3_hang_1"
                    value={templateCode}
                    onChange={(e) => setTemplateCode(e.target.value)}
                  />
                </div>
                <div>
                  <label className="label">Tên hiển thị</label>
                  <input
                    className="input"
                    placeholder="6 EB3 TT - Đơn DS260 - Hãng 1"
                    value={templateName}
                    onChange={(e) => setTemplateName(e.target.value)}
                  />
                </div>
                <div className="flex items-end">
                  <input
                    ref={templateFileRef}
                    type="file"
                    accept=".docx"
                    className="hidden"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) uploadTemplate(f);
                      e.target.value = "";
                    }}
                  />
                  <button
                    type="button"
                    className="btn-secondary w-full"
                    disabled={busy === "template"}
                    onClick={() => templateFileRef.current?.click()}
                  >
                    {busy === "template" ? "Đang upload..." : "Chọn file .docx mẫu"}
                  </button>
                </div>
              </div>
              <p className="mt-2 text-xs text-slate-500">
                Hoặc copy file vào{" "}
                <code className="rounded bg-white px-1">backend/templates/forms/ten_form.docx</code> rồi restart
                server.
              </p>

              {userRole === "admin" && templates.filter((t) => !PROTECTED_FORM_TEMPLATES.has(t.code)).length > 0 && (
                <div className="mt-4 border-t border-blue-100 pt-4">
                  <p className="mb-2 text-sm font-medium text-slate-700">Mẫu form đã upload</p>
                  <ul className="space-y-2">
                    {templates
                      .filter((t) => !PROTECTED_FORM_TEMPLATES.has(t.code))
                      .map((t) => (
                        <li
                          key={t.id}
                          className="flex flex-wrap items-center justify-between gap-2 rounded border border-slate-200 bg-white px-3 py-2 text-sm"
                        >
                          <span>
                            {t.name} <span className="text-slate-500">({t.code})</span>
                          </span>
                          <button
                            type="button"
                            className="btn-secondary text-xs text-red-700 hover:border-red-200 hover:bg-red-50"
                            disabled={busy === `del-tpl-${t.id}`}
                            onClick={() => deleteFormTemplate(t)}
                          >
                            {busy === `del-tpl-${t.id}` ? "Đang xóa…" : "Xóa mẫu"}
                          </button>
                        </li>
                      ))}
                  </ul>
                </div>
              )}
            </div>
          </>
        )}

        {reviewTab === "documents" && (
          <>
            <p className="mb-4 text-sm text-slate-600">
              Dữ liệu OCR theo <strong>từng file giấy tờ</strong> — bấm ▼ để mở từng loại.
              {canEditDs260 && (
                <>
                  {" "}
                  Sửa từng ô → bấm <strong>Lưu</strong> cạnh ô (hoặc Enter). Sau khi lưu, chuyển tab DS-260 để
                  thấy giá trị cập nhật.
                </>
              )}
            </p>

            {docTables.some((t) => (t.standard_count ?? 0) > 0) && (
              <div className="card mb-6">
                <h2 className="mb-2 text-lg font-semibold">Bảng tài liệu — Luồng 1 (file mẫu)</h2>
                <p className="mb-4 text-sm text-slate-600">
                  Passport, Birth certificate, Judicial, Marriage — OCR từ file chuẩn (không hậu tố{" "}
                  <code className="rounded bg-slate-100 px-1">_new</code>).
                </p>
                <div className="space-y-2">
                  {docTables
                    .filter((t) => (t.standard_count ?? 0) > 0)
                    .map((t, i) => {
                      const meta = docTypeMeta(t.doc_type);
                      return (
                        <DocumentTablePanel
                          key={`std-${t.doc_type}`}
                          applicantId={id}
                          docType={t.doc_type}
                          records={docRecordsByType[t.doc_type] || []}
                          defaultOpen={i === 0}
                          canEdit={canEditDs260}
                          fieldLabels={meta.fieldLabels}
                          extractKeys={meta.extractKeys}
                          onFieldSaved={load}
                        />
                      );
                    })}
                </div>
              </div>
            )}

            <div className="card mb-6 border-amber-200 bg-amber-50/30">
              <h2 className="mb-2 text-lg font-semibold text-amber-950">
                Bảng đối chiếu DS-260 — Khách hàng upload
              </h2>
              <p className="mb-4 text-sm text-amber-900/80">
                Mỗi file upload hậu tố <code className="rounded bg-white px-1">_new</code> = 1 record
                để validate và xử lý xung đột với Luồng 1. Ví dụ:{" "}
                <code className="rounded bg-white px-1">Passport_new.pdf</code>
                {" · "}
                Form DS-260 khách khai (mục 3–5):{" "}
                <code className="rounded bg-white px-1">ds260.pdf</code> hoặc{" "}
                <code className="rounded bg-white px-1">DS260_new.pdf</code>
              </p>
              <div className="space-y-2">
                {referenceTables.map((t) => {
                  const meta = docTypeMeta(t.doc_type);
                  return (
                    <DocumentTablePanel
                      key={`ref-${t.doc_type}`}
                      applicantId={id}
                      docType={t.doc_type}
                      records={referenceRecordsByType[t.doc_type] || []}
                      alwaysShow
                      defaultOpen
                      canEdit={canEditDs260}
                      fieldLabels={meta.fieldLabels}
                      extractKeys={meta.extractKeys}
                      onFieldSaved={load}
                      emptyHint={
                        t.upload_hint
                          ? `Chưa có file. Upload tên: ${t.upload_hint}`
                          : "Chưa có file đối chiếu."
                      }
                    />
                  );
                })}
              </div>
            </div>
          </>
        )}

        <div className="card mt-6">
          <h2 className="mb-2 font-semibold">Tải gói tài liệu scan (ZIP)</h2>
          <button type="button" className="btn-secondary" disabled={busy === "zip"} onClick={exportZip}>
            {busy === "zip" ? "..." : "ZIP tài liệu đã upload"}
          </button>
          <p className="mt-3 text-xs text-slate-500">
            ZIP chỉ gồm file PDF/ảnh gốc đã upload — <strong>không</strong> chứa DS-260 Word cho vợ/con.
            Để tải form DS-260 từng người, dùng panel{" "}
            <a href="#family-download" className="text-brand-600 underline">
              Tải DS-260 theo từng người
            </a>{" "}
            ở đầu trang (cần thiết lập thành viên gia đình trước).
          </p>
        </div>

        <AiChatPanel applicantId={id} />
      </main>
    </div>
  );
}
