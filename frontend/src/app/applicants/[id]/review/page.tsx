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
  Ds260ValidationIssue,
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
  if (role === "grandchild") return "Cháu";
  if (role === "sibling") return "Anh/Chị/Em";
  return "Con";
}

// Các section này chỉ dùng nội bộ để điền DS-260/export, không hiển thị trên Review UI.
const ALWAYS_HIDDEN_DS260_SECTIONS = new Set([
  "section_birth_certificate",
  "section_judicial",
  "section_divorce",
]);

function memberPanelClass(role: CaseMember["role"]) {
  if (role === "principal") return "border-brand-300 bg-brand-50/30 ring-brand-100";
  if (role === "spouse") return "border-violet-300 bg-violet-50/30 ring-violet-100";
  if (role === "grandchild") return "border-teal-300 bg-teal-50/30 ring-teal-100";
  if (role === "sibling") return "border-sky-300 bg-sky-50/30 ring-sky-100";
  return "border-amber-300 bg-amber-50/30 ring-amber-100";
}

function visibleDs260Sections(sections: Ds260Form["sections"], role: CaseMember["role"]) {
  return sections.filter((sec) => !ALWAYS_HIDDEN_DS260_SECTIONS.has(sec.id));
}

type ConflictResolveModalState = {
  phase: "processing" | "done";
  returnScrollY: number | null;
};

function ConflictResolveModal({
  state,
  onScrollUp,
  onDismiss,
}: {
  state: ConflictResolveModalState;
  onScrollUp: () => void;
  onDismiss: () => void;
}) {
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-900/40 p-4">
      <div className="w-full max-w-sm rounded-xl bg-white p-5 text-center shadow-xl">
        {state.phase === "processing" ? (
          <>
            <div className="mx-auto mb-3 h-8 w-8 animate-spin rounded-full border-4 border-brand-200 border-t-brand-600" />
            <p className="text-sm font-medium text-slate-800">Đang xử lý xung đột…</p>
          </>
        ) : (
          <>
            <div className="mx-auto mb-3 flex h-8 w-8 items-center justify-center rounded-full bg-green-100 text-green-600">
              ✓
            </div>
            <p className="text-sm font-semibold text-slate-900">Đã xử lý xung đột</p>
            <p className="mt-1 text-xs text-slate-500">
              Dữ liệu đã được cập nhật vào bảng DS-260.
            </p>
            <div className="mt-4 flex flex-col gap-2 sm:flex-row">
              {state.returnScrollY !== null && (
                <button type="button" className="btn-secondary flex-1 text-sm" onClick={onScrollUp}>
                  Cuộn lên vị trí cũ
                </button>
              )}
              <button type="button" className="btn-primary flex-1 text-sm" onClick={onDismiss}>
                Đã biết
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function Ds260ConflictPanel({
  conflicts,
  warnings,
  onResolve,
  busyId,
}: {
  conflicts: Conflict[];
  warnings: Ds260ValidationIssue[];
  onResolve: (conflictId: string, value: string) => Promise<boolean>;
  busyId: string;
}) {
  const [customById, setCustomById] = useState<Record<string, string>>({});
  // Đánh dấu nút vừa bấm (a/b/custom) để tô sáng ngay lập tức, không đợi API trả về.
  const [pickedById, setPickedById] = useState<Record<string, "a" | "b" | "custom">>({});
  const [resolveModal, setResolveModal] = useState<ConflictResolveModalState | null>(null);

  const handlePick = async (c: Conflict, choice: "a" | "b" | "custom", value: string) => {
    setPickedById((prev) => ({ ...prev, [c.id]: choice }));
    // Ghi lại vị trí cuộn hiện tại (thường là vị trí field bị xung đột mà người dùng đã bấm
    // "cuộn xuống đây") để sau khi xử lý xong có thể đưa họ quay lại đúng chỗ.
    setResolveModal({ phase: "processing", returnScrollY: pendingConflictReturnScrollY });
    const ok = await onResolve(c.id, value);
    if (ok) {
      pendingConflictReturnScrollY = null;
      setResolveModal((prev) => (prev ? { ...prev, phase: "done" } : prev));
    } else {
      // Thất bại — lỗi đã báo qua alert(), đóng modal và bỏ trạng thái "đã chọn".
      setResolveModal(null);
      setPickedById((prev) => {
        const next = { ...prev };
        delete next[c.id];
        return next;
      });
    }
  };

  // Khi resolve xong xung đột cuối cùng, `conflicts` sẽ rỗng ngay — nhưng modal "Đã xử lý"
  // vẫn phải hiện, nên không được return null sớm trong lúc modal đang mở.
  if (conflicts.length === 0 && warnings.length === 0 && !resolveModal) return null;

  const modal = resolveModal && (
    <ConflictResolveModal
      state={resolveModal}
      onScrollUp={() => {
        if (resolveModal.returnScrollY !== null) {
          window.scrollTo({ top: resolveModal.returnScrollY, behavior: "smooth" });
        }
        setResolveModal(null);
      }}
      onDismiss={() => setResolveModal(null)}
    />
  );

  if (conflicts.length === 0 && warnings.length === 0) return modal;

  return (
    <div id="ds260-conflicts-section" className="card mb-6 border-amber-300 bg-amber-50/50 scroll-mt-24">
      {modal}
      <h2 className="text-lg font-semibold text-slate-900">
        Cảnh báo DS-260
        {conflicts.length > 0 && <span className="ml-2 text-sm font-normal text-amber-700">({conflicts.length} xung đột{typeof window !== "undefined" && warnings.length > 0 ? ` · ${warnings.length} cảnh báo` : ""})</span>}
        {conflicts.length === 0 && warnings.length > 0 && <span className="ml-2 text-sm font-normal text-amber-700">({warnings.length} cảnh báo)</span>}
      </h2>
      {conflicts.length > 0 && (
        <p className="mt-1 text-sm text-slate-600">
          Chọn <strong>nguồn A</strong> (Luồng 1 / giấy tờ chính) hoặc <strong>nguồn B</strong> (đối chiếu{" "}
          <code className="text-xs">_new</code> / worksheet). Giá trị đã chọn sẽ{" "}
          <strong>tự điền</strong> vào bảng DS-260 bên dưới và file Word khi xuất.
        </p>
      )}
      {warnings.length > 0 && (
        <ul className="mt-3 space-y-2">
          {warnings.map((w, i) => (
            <li key={`warn-${i}`} className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              <span className="mt-0.5 shrink-0">⚠</span>
              <span>{w.message}</span>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-4 space-y-3">
        {conflicts.map((c) => {
          const isWorksheet = c.conflict_type === "document_vs_worksheet";
          const isOutlier = c.conflict_type === "identity_outlier";
          const title = c.field_label || c.field_key.replace(/^ds260\./, "");
          const custom = customById[c.id] ?? "";
          const isBusy = busyId === c.id;
          const picked = pickedById[c.id];
          return (
            <div
              key={c.id}
              id={`ds260-conflict-${c.id}`}
              className={`relative overflow-hidden rounded-lg border bg-white p-3 transition-colors scroll-mt-24 ${
                isOutlier ? "border-rose-300" : "border-amber-200"
              }`}
            >
              <p className="text-sm font-medium text-slate-800">{title}</p>
              {isWorksheet && (
                <p className="mt-0.5 text-xs text-slate-500">Loại: Giấy tờ vs DS-260 worksheet</p>
              )}
              {isOutlier && (
                <p className="mt-0.5 text-xs font-medium text-rose-600">
                  {c.majority_count ?? "?"}/{c.total_count ?? "?"} tài liệu cùng ghi giá trị này — tài
                  liệu còn lại có thể bị trích xuất sai
                </p>
              )}
              <div className="mt-2 flex flex-col gap-2 sm:flex-row">
                <button
                  type="button"
                  disabled={isBusy}
                  className={`flex-1 rounded border px-3 py-2 text-left text-sm transition ${
                    picked === "a"
                      ? "border-green-500 bg-green-100 ring-2 ring-green-300"
                      : "border-green-200 bg-green-50/50 hover:bg-green-50"
                  }`}
                  onClick={() => handlePick(c, "a", c.value_a || "")}
                >
                  <span className="flex items-center gap-1 text-xs font-medium text-green-700">
                    {picked === "a" && <span>✓</span>}
                    {isOutlier
                      ? `Đa số tài liệu (${c.majority_count ?? "?"}/${c.total_count ?? "?"})`
                      : isWorksheet
                        ? "Nguồn A — Giấy tờ chính (Luồng 1)"
                        : "Nguồn A — Luồng 1 (mẫu)"}
                  </span>
                  <span className="font-mono">{c.value_a || "—"}</span>
                  {c.document_a_filename && (
                    <span className="mt-1 block text-xs text-slate-400">{c.document_a_filename}</span>
                  )}
                </button>
                <button
                  type="button"
                  disabled={isBusy}
                  className={`flex-1 rounded border px-3 py-2 text-left text-sm transition ${
                    picked === "b"
                      ? isOutlier
                        ? "border-rose-500 bg-rose-100 ring-2 ring-rose-300"
                        : "border-amber-500 bg-amber-100 ring-2 ring-amber-300"
                      : isOutlier
                        ? "border-rose-200 bg-rose-50/50 hover:bg-rose-50"
                        : "border-amber-200 bg-amber-50/50 hover:bg-amber-50"
                  }`}
                  onClick={() => handlePick(c, "b", c.value_b || "")}
                >
                  <span
                    className={`flex items-center gap-1 text-xs font-medium ${isOutlier ? "text-rose-700" : "text-amber-700"}`}
                  >
                    {picked === "b" && <span>✓</span>}
                    {isOutlier
                      ? `${c.document_b_filename || "Tài liệu này"} — khác biệt`
                      : isWorksheet
                        ? "Nguồn B — DS-260 khách khai"
                        : "Nguồn B — Đối chiếu (_new)"}
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
                    disabled={isBusy}
                    placeholder="Giá trị tùy chỉnh…"
                    onChange={(e) => setCustomById((prev) => ({ ...prev, [c.id]: e.target.value }))}
                  />
                </div>
                <button
                  type="button"
                  className={`btn-secondary shrink-0 text-sm ${picked === "custom" ? "ring-2 ring-brand-300" : ""}`}
                  disabled={isBusy || !custom.trim()}
                  onClick={() => handlePick(c, "custom", custom.trim())}
                >
                  {picked === "custom" && "✓ "}Dùng giá trị này
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

function slugifyName(name: string): string {
  return (
    (name || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/đ/g, "d")
      .replace(/Đ/g, "D")
      .toUpperCase()
      .replace(/[^A-Z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "") || "unknown"
  );
}

function findConflictForField(
  f: Ds260Form["sections"][0]["fields"][0],
  conflicts: Conflict[],
  memberNumber: string | undefined,
  isFamilyCase: boolean,
  allSectionFields?: Ds260Form["sections"][0]["fields"],
  memberDisplayName?: string
): Conflict | undefined {
  if (!conflicts || conflicts.length === 0) return undefined;

  return conflicts.find((c) => {
    let cleanKey = c.field_key;
    let suffixMember: string | null = null;

    // Check for member suffix .memberNN
    const suffixMatch = cleanKey.match(/\.member(\d{2})$/);
    if (suffixMatch) {
      suffixMember = suffixMatch[1];
      cleanKey = cleanKey.substring(0, cleanKey.length - suffixMatch[0].length);
    }

    // 1. Child identity conflict: ds260.child_identity.<child_slug>.<field>
    if (cleanKey.startsWith("ds260.child_identity.")) {
      const rest = cleanKey.substring("ds260.child_identity.".length);
      const lastDot = rest.lastIndexOf(".");
      if (lastDot !== -1) {
        const childSlug = rest.substring(0, lastDot);
        const childField = rest.substring(lastDot + 1);

        // Case A: In section_children on Principal/Spouse (field is child_N_...)
        const childSlotMatch = f.key.match(/^child_(\d+)_(.+)$/);
        if (childSlotMatch) {
          const slotNum = childSlotMatch[1];
          const slotField = childSlotMatch[2];
          if (slotField === childField) {
            const nameField = allSectionFields?.find((sf) => sf.key === `child_${slotNum}_full_name`);
            const childName = nameField?.value || "";
            if (childName && slugifyName(childName) === childSlug) {
              return true;
            }
          }
          return false;
        }

        // Case B: On Child's own personal section (member role is child)
        if (memberDisplayName && slugifyName(memberDisplayName) === childSlug) {
          return f.key === childField || f.key === `child_${childField}`;
        }
      }
      return false;
    }

    // 2. Child parent identity conflict: ds260.child_parent_identity.<child_slug>.<parent>.<field>
    if (cleanKey.startsWith("ds260.child_parent_identity.")) {
      const rest = cleanKey.substring("ds260.child_parent_identity.".length);
      const parts = rest.split(".");
      if (parts.length >= 3) {
        const childSlug = parts[0];
        const parentRole = parts[1]; // father or mother
        const parentField = parts[2]; // date_of_birth or birth_country
        if (memberDisplayName && slugifyName(memberDisplayName) === childSlug) {
          return f.key === `${parentRole}_${parentField}`;
        }
      }
      return false;
    }

    // 3. Spouse worksheet / identity conflicts
    if (cleanKey.startsWith("ds260.spouse_worksheet.") || cleanKey.startsWith("ds260.spouse_identity.")) {
      const parts = cleanKey.split(".");
      if (parts.length >= 3) {
        const fieldKey = parts.slice(2).join(".");
        return f.key === fieldKey;
      }
      return false;
    }

    // 4. Check member suffix for member-scoped conflicts
    if (isFamilyCase) {
      const targetSuffix = memberNumber || "01";
      const currentSuffix = suffixMember || "01";
      if (currentSuffix !== targetSuffix) {
        return false;
      }
    }

    // 5. Worksheet conflict: ds260.document_vs_worksheet.<key>
    if (cleanKey.startsWith("ds260.document_vs_worksheet.")) {
      const mappingKey = cleanKey.substring("ds260.document_vs_worksheet.".length);
      return mappingKey === f.key;
    }

    // 6. Standard document conflict: ds260.<doc_type>.<source_field>
    if (cleanKey.startsWith("ds260.")) {
      const rest = cleanKey.substring("ds260.".length);
      const firstDot = rest.indexOf(".");
      if (firstDot !== -1) {
        const docType = rest.substring(0, firstDot);
        const sourceField = rest.substring(firstDot + 1);
        if (docType === f.source.document_type) {
          if (sourceField === f.source.source_field || sourceField === f.key) {
            return true;
          }
        }
      }
    }

    return false;
  });
}

// Vị trí cuộn trước khi nhảy tới 1 conflict card cụ thể — dùng để đưa người dùng quay lại
// đúng chỗ (field) sau khi họ đã xử lý xong xung đột đó. Biến module-level vì nút "quay lại"
// nằm trong modal xử lý xung đột, một component khác với field đã kích hoạt việc cuộn.
let pendingConflictReturnScrollY: number | null = null;

function scrollToConflictCard(conflictId: string) {
  const el = document.getElementById(`ds260-conflict-${conflictId}`);
  if (!el) return;
  pendingConflictReturnScrollY = window.scrollY;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.add("ring-4", "ring-blue-400");
  window.setTimeout(() => {
    el.classList.remove("ring-4", "ring-blue-400");
  }, 1600);
}

function scrollToField(fieldKey: string) {
  const el = document.getElementById(`field-${fieldKey}`);
  if (!el) return;
  pendingConflictReturnScrollY = window.scrollY;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.add("ring-4", "ring-amber-400");
  window.setTimeout(() => {
    el.classList.remove("ring-4", "ring-amber-400");
  }, 2000);
}

function AddressWarningModal({
  warnings,
  onDismiss,
}: {
  warnings: Ds260ValidationIssue[];
  onDismiss: () => void;
}) {
  const missingBefore16 = warnings.find((w) => w.code === "missing_address_before_16");
  const contradiction = warnings.find((w) => w.code === "address_contradiction");

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-900/50 p-4">
      <div className="w-full max-w-sm rounded-xl bg-white p-6 text-center shadow-2xl">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-amber-100 text-2xl">
          ⚠
        </div>
        <h3 className="text-base font-semibold text-slate-900">Cảnh báo DS-260</h3>

        {missingBefore16 && (
          <p className="mt-3 text-sm text-slate-700">{missingBefore16.message}</p>
        )}
        {contradiction && (
          <p className="mt-3 text-sm text-slate-700">{contradiction.message}</p>
        )}

        <div className="mt-5 flex flex-col gap-2">
          {(missingBefore16 || contradiction) && (
            <button
              type="button"
              className="w-full rounded-lg bg-amber-500 px-4 py-2.5 text-sm font-medium text-white hover:bg-amber-600 transition"
              onClick={() => {
                if (missingBefore16) {
                  scrollToField("other_addresses_used");
                } else if (contradiction) {
                  scrollToField("other_addresses_used");
                }
                onDismiss();
              }}
            >
              Điền ngay
            </button>
          )}
          <button
            type="button"
            className="w-full rounded-lg border border-slate-300 px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50 transition"
            onClick={onDismiss}
          >
            Đã biết
          </button>
        </div>
      </div>
    </div>
  );
}

function InputTooltip({ value }: { value: string }) {
  if (!value || value.length <= 18) return null;
  return (
    <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 hidden group-hover:block z-30 w-72 bg-slate-900 text-white text-xs rounded-lg p-2.5 shadow-xl border border-slate-700/50 pointer-events-none break-all">
      <div className="font-semibold text-slate-400 mb-1 border-b border-slate-800 pb-0.5">Dữ liệu chi tiết:</div>
      <div className="font-mono text-[13px] text-white whitespace-pre-wrap leading-relaxed">{value}</div>
      <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-slate-900" />
    </div>
  );
}

const FE_HIDDEN_KEYS = new Set([
  "divorce_husband_name",
  "divorce_wife_name",
  "military_document_number",
]);

function Ds260FieldGrid({
  applicantId,
  memberId,
  memberNumber,
  memberDisplayName,
  isFamilyCase,
  ds260Conflicts,
  fields,
  canEdit,
  onFieldSaved,
  addressWarnings,
}: {
  applicantId: string;
  memberId?: string;
  memberNumber?: string;
  memberDisplayName?: string;
  isFamilyCase: boolean;
  ds260Conflicts: Conflict[];
  fields: Ds260Form["sections"][0]["fields"];
  canEdit: boolean;
  onFieldSaved: (updatedForm?: Ds260Form, savedMemberId?: string) => void;
  addressWarnings?: Ds260ValidationIssue[];
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
    let trimmed = value.trim();
    if (key.toLowerCase().includes("email") && trimmed.toUpperCase() !== "N/A") {
      trimmed = trimmed.toLowerCase();
    }
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
      const updatedForm = await api.updateDs260Field(applicantId, key, trimmed, memberId);
      setDrafts((d) => {
        const next = { ...d };
        delete next[key];
        return next;
      });
      onFieldSaved(updatedForm, memberId);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Không thể lưu trường DS-260");
    } finally {
      setSavingKey("");
    }
  };

  const clearOverride = async (key: string) => {
    setSavingKey(key);
    try {
      const updatedForm = await api.updateDs260Field(applicantId, key, "", memberId);
      setDrafts((d) => {
        const next = { ...d };
        delete next[key];
        return next;
      });
      onFieldSaved(updatedForm, memberId);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Không thể xóa chỉnh sửa");
    } finally {
      setSavingKey("");
    }
  };

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {fields.filter((f) => !f.review_hidden && !FE_HIDDEN_KEYS.has(f.key)).map((f) => {
        const isManual = f.source.derived === "manual_override";
        const matchedConflict = findConflictForField(
          f,
          ds260Conflicts,
          memberNumber,
          isFamilyCase,
          fields,
          memberDisplayName
        );
        const isConflicted = !!matchedConflict;
        const busy = savingKey === f.key;
        // Warning / trống cho other_addresses_used: highlight đỏ nếu khách chưa khai (để trống) hoặc có warning
        const hasAddressWarning = f.key === "other_addresses_used" &&
          addressWarnings?.some((w) => w.code === "missing_address_before_16" || w.code === "address_contradiction");
        const needsWarningHighlight = (f.key === "other_addresses_used" && !displayValue(f).trim()) || (hasAddressWarning && !f.value);
        return (
          <div
            key={f.key}
            id={`field-${f.key}`}
            className={`rounded-md border p-2 ${
              isConflicted
                ? "border-red-400 bg-rose-50/30 ring-1 ring-red-100"
                : needsWarningHighlight
                  ? "border-red-400 bg-red-50/50 ring-2 ring-red-200"
                  : isManual
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
                <div className="relative flex-1 group">
                  <input
                    className="input min-h-0 w-full border-brand-200 bg-white py-1.5 font-mono text-sm shadow-sm ring-1 ring-brand-100 focus:ring-brand-400"
                    value={displayValue(f)}
                    disabled={busy}
                    onChange={(e) => {
                      const val = f.key.toLowerCase().includes("email") && e.target.value.toUpperCase() !== "N/A"
                        ? e.target.value.toLowerCase()
                        : e.target.value;
                      setDrafts((d) => ({ ...d, [f.key]: val }));
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        void saveField(f.key, e.currentTarget.value, f.value);
                      }
                    }}
                    onBlur={(e) => {
                      // Tự lưu khi rời khỏi ô — tránh trường hợp người dùng gõ xong rồi
                      // click sang chỗ khác mà quên bấm "Lưu", làm mất thay đổi vừa nhập.
                      if (drafts[f.key] !== undefined) {
                        void saveField(f.key, e.currentTarget.value, f.value);
                      }
                    }}
                  />
                  <InputTooltip value={displayValue(f)} />
                </div>
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
              <div className="relative group inline-block max-w-full">
                <p className="mt-0.5 break-words font-mono text-sm text-slate-900">{f.value || "—"}</p>
                <InputTooltip value={f.value || ""} />
              </div>
            )}
            {isConflicted && matchedConflict && (
              <button
                type="button"
                className="mt-1 flex items-center gap-1 text-xs font-semibold text-red-600 underline decoration-dotted hover:text-red-700"
                onClick={() => scrollToConflictCard(matchedConflict.id)}
              >
                <span>⚠️ Cần chọn trong xung đột — bấm để đến phần xử lý</span>
              </button>
            )}
            {needsWarningHighlight && (
              <p className="mt-1 flex items-center gap-1 text-xs font-medium text-red-600">
                ⚠️ Cần điền thông tin này
              </p>
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
  ds260Conflicts,
  isFamilyCase,
  ds260Validation,
}: {
  applicantId: string;
  member: CaseMember;
  form: Ds260Form;
  canEdit: boolean;
  onFieldSaved: (updatedForm?: Ds260Form, savedMemberId?: string) => void;
  onExport: (member: CaseMember) => void;
  exportBusy: boolean;
  ds260Conflicts: Conflict[];
  isFamilyCase: boolean;
  ds260Validation?: Ds260Validation | null;
}) {
  const sections = visibleDs260Sections(form.sections, member.role);
  // Thành viên chưa có dữ liệu gì (chưa upload/chưa điền field nào) → mặc định thu nhỏ, tránh
  // hiện 1 khối rỗng chiếm chỗ làm rối màn hình Review khi hồ sơ có nhiều thành viên.
  const hasAnyData = (form.applicable_filled_count ?? form.filled_count) > 0;
  const [isCollapsed, setIsCollapsed] = useState(!hasAnyData);

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
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="btn-secondary flex items-center gap-1.5 shrink-0"
            onClick={() => setIsCollapsed(!isCollapsed)}
            title={isCollapsed ? "Mở rộng" : "Thu nhỏ"}
          >
            {isCollapsed ? (
              <>
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
                <span>Mở rộng</span>
              </>
            ) : (
              <>
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
                </svg>
                <span>Thu nhỏ</span>
              </>
            )}
          </button>
          <button
            type="button"
            className="btn-secondary shrink-0"
            disabled={exportBusy}
            onClick={() => onExport(member)}
          >
            {exportBusy ? "Đang xuất…" : `Xuất DS-260 — ${member.display_name}`}
          </button>
        </div>
      </div>

      {!isCollapsed && (
        <>
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
                    memberNumber={member.member_number || undefined}
                    memberDisplayName={member.display_name}
                    isFamilyCase={isFamilyCase}
                    ds260Conflicts={ds260Conflicts}
                    fields={sec.fields}
                    canEdit={canEdit}
                    onFieldSaved={onFieldSaved}
                    addressWarnings={ds260Validation?.warnings}
                  />
                </div>
              </div>
            ))}
          </div>
        </>
      )}
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
    let trimmed = value.trim();
    if (fieldKey.toLowerCase().includes("email") && trimmed.toUpperCase() !== "N/A") {
      trimmed = trimmed.toLowerCase();
    }
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
                    const isEmail = k.toLowerCase().includes("email");
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
                              onChange={(e) => {
                                const val =
                                  isEmail && e.target.value.toUpperCase() !== "N/A"
                                    ? e.target.value.toLowerCase()
                                    : e.target.value;
                                setDrafts((d) => ({ ...d, [draftId]: val }));
                              }}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") {
                                  e.preventDefault();
                                  void saveField(rec.id, k, e.currentTarget.value, original);
                                }
                              }}
                              onBlur={(e) => {
                                // Tự lưu khi rời khỏi ô — tránh mất thay đổi nếu người dùng
                                // quên bấm "Lưu" sau khi gõ xong.
                                if (drafts[draftId] !== undefined) {
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
  const [showConflictModal, setShowConflictModal] = useState(false);
  const [hasShownConflictModal, setHasShownConflictModal] = useState(false);
  const [confirmModal, setConfirmModal] = useState<{
    isOpen: boolean;
    message: string;
    onConfirm: () => void;
  }>({
    isOpen: false,
    message: "",
    onConfirm: () => {},
  });
  // Warning modal chỉ hiện LẦN ĐẦU trong session — dùng sessionStorage để không hiện lại khi refresh
  const [hasShownAddressWarningModal, setHasShownAddressWarningModal] = useState(() => {
    if (typeof window !== "undefined") {
      return sessionStorage.getItem(`ds260_address_warning_shown_${id}`) === "true";
    }
    return false;
  });
  const [conflictBusy, setConflictBusy] = useState("");
  const [busy, setBusy] = useState("");
  const [caseMembers, setCaseMembers] = useState<CaseMember[]>([]);
  const [selectedMemberId, setSelectedMemberId] = useState<string>("");
  const [setupPrincipalName, setSetupPrincipalName] = useState("");
  const [setupSpouseName, setSetupSpouseName] = useState("");
  const [setupChildNames, setSetupChildNames] = useState("");
  const [appendChildNames, setAppendChildNames] = useState("");
  const [appendGrandchildNames, setAppendGrandchildNames] = useState("");
  const [appendSiblingNames, setAppendSiblingNames] = useState("");
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

  const loadInner = useCallback(async () => {
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
    setHasShownConflictModal((prev) => {
      if (!prev && conflicts.length > 0) {
        setShowConflictModal(true);
        return true;
      }
      return prev;
    });
    if (validation?.warnings?.some((w) => w.code === "missing_address_before_16" || w.code === "address_contradiction")) {
      if (typeof window !== "undefined" && sessionStorage.getItem(`ds260_address_warning_shown_${id}`) !== "true") {
        sessionStorage.setItem(`ds260_address_warning_shown_${id}`, "true");
        setHasShownAddressWarningModal(true);
      }
    }
    setDocTables(tables);
    setReferenceTables(refTables);

    // Tải bảng tài liệu gốc trong nền để không chặn render DS-260
    const withStandard = tables.filter((t) => (t.standard_count ?? t.record_count) > 0);
    Promise.all(
      withStandard.map((t) =>
        api.getDocumentTable(id, t.doc_type, "standard").catch(() => [] as DocRecord[])
      )
    ).then((standardSets) => {
      const byType: Record<string, DocRecord[]> = {};
      withStandard.forEach((t, i) => {
        byType[t.doc_type] = standardSets[i];
      });
      setDocRecordsByType(byType);
    });

    Promise.all(
      refTables.map((t) =>
        api.getDocumentTable(id, t.doc_type, "exception").catch(() => [] as DocRecord[])
      )
    ).then((refSets) => {
      const refByType: Record<string, DocRecord[]> = {};
      refTables.forEach((t, i) => {
        refByType[t.doc_type] = refSets[i];
      });
      setReferenceRecordsByType(refByType);
    });
  }, [id]);

  const load = useCallback(async () => {
    // Refresh sau khi resolve conflict / lưu field làm re-render toàn trang, khiến trình duyệt
    // cuộn ngược lên đầu. Ghi lại vị trí cuộn trước khi load rồi khôi phục sau khi DOM đã vẽ lại.
    const scrollY = window.scrollY;
    try {
      await loadInner();
    } finally {
      requestAnimationFrame(() => {
        requestAnimationFrame(() => window.scrollTo(0, scrollY));
      });
    }
  }, [loadInner]);

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

  const resolveDs260Conflict = async (conflictId: string, value: string): Promise<boolean> => {
    setConflictBusy(conflictId);
    try {
      await api.resolveConflict(id, conflictId, value);
      await load();
      return true;
    } catch (err) {
      alert(err instanceof Error ? err.message : "Không thể giải quyết xung đột");
      return false;
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
    const grandchildren = appendGrandchildNames
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    const siblings = appendSiblingNames
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    if (
      !spouse &&
      children.length === 0 &&
      grandchildren.length === 0 &&
      siblings.length === 0
    ) {
      alert("Nhập tên con/cháu/anh-chị-em mới hoặc phối ngẫu cần bổ sung");
      return;
    }
    if (spouse && hasSpouseMember) {
      alert("Hồ sơ đã có phối ngẫu. Chỉ có thể thêm con/cháu/anh-chị-em.");
      return;
    }

    const toAdd: {
      role: "spouse" | "child" | "grandchild" | "sibling";
      display_name: string;
    }[] = [];
    if (spouse && !hasSpouseMember) toAdd.push({ role: "spouse", display_name: spouse });
    children.forEach((name) => toAdd.push({ role: "child", display_name: name }));
    grandchildren.forEach((name) => toAdd.push({ role: "grandchild", display_name: name }));
    siblings.forEach((name) => toAdd.push({ role: "sibling", display_name: name }));

    setBusy("append-members");
    try {
      const saved = await api.addCaseMembers(id, toAdd);
      setCaseMembers(saved);
      setAppendChildNames("");
      setAppendGrandchildNames("");
      setAppendSiblingNames("");
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
    setConfirmModal({
      isOpen: true,
      message: `Xóa ${memberRoleLabel(member.role)} "${member.display_name}" khỏi hồ sơ?\n\nChỉ xóa khi nhầm người / hồ sơ test.`,
      onConfirm: async () => {
        setConfirmModal((prev) => ({ ...prev, isOpen: false }));
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
      }
    });
  };

  const exportDs260 = async () => {
    const runExport = async () => {
      setBusy("export-ds260");
      try {
        const memberId = selectedMemberId || undefined;
        const member = caseMembers.find((m) => m.id === memberId);
        const result = await api.exportDs260(
          id,
          Boolean(ds260Validation && !ds260Validation.valid),
          ds260TemplateCode,
          memberId
        );
        const label = member?.display_name || applicant?.display_name || id;
        await api.downloadExportFile(result.id, result.download_url, exportFilenameForMember(label));
        await load();
      } catch (err) {
        alert(err instanceof Error ? err.message : "Xuất DS260 thất bại");
      } finally {
        setBusy("");
      }
    };

    if (ds260Validation && !ds260Validation.valid) {
      setConfirmModal({
        isOpen: true,
        message: `DS260 có ${ds260Validation.error_count} lỗi. Vẫn xuất file nháp?\n\n` +
          ds260Validation.errors.map((e) => `• ${e.message}`).slice(0, 5).join("\n"),
        onConfirm: () => {
          setConfirmModal((prev) => ({ ...prev, isOpen: false }));
          void runExport();
        }
      });
    } else {
      void runExport();
    }
  };

  const exportDs260ForMember = async (member: CaseMember) => {
    const runExport = async () => {
      setBusy(`export-ds260-${member.id}`);
      try {
        const result = await api.exportDs260(
          id,
          Boolean(ds260Validation && !ds260Validation.valid),
          ds260TemplateCode,
          member.id
        );
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

    if (ds260Validation && !ds260Validation.valid) {
      setConfirmModal({
        isOpen: true,
        message: `DS260 có ${ds260Validation.error_count} lỗi. Vẫn xuất file nháp?\n\n` +
          ds260Validation.errors.map((e) => `• ${e.message}`).slice(0, 5).join("\n"),
        onConfirm: () => {
          setConfirmModal((prev) => ({ ...prev, isOpen: false }));
          void runExport();
        }
      });
    } else {
      void runExport();
    }
  };

  const exportDs260Batch = async () => {
    const runExport = async (skipValidation: boolean) => {
      setBusy("export-ds260-batch");
      try {
        const result = await api.exportDs260Batch(id, skipValidation, ds260TemplateCode);
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

    if (ds260Validation && !ds260Validation.valid) {
      setConfirmModal({
        isOpen: true,
        message: "Một số trường chưa hợp lệ. Vẫn xuất tất cả thành viên?",
        onConfirm: () => {
          setConfirmModal((prev) => ({ ...prev, isOpen: false }));
          void runExport(true);
        }
      });
    } else {
      void runExport(false);
    }
  };

  const deleteFormTemplate = async (tpl: FormTemplate) => {
    if (PROTECTED_FORM_TEMPLATES.has(tpl.code)) {
      alert("Không thể xóa template hệ thống mặc định.");
      return;
    }
    setConfirmModal({
      isOpen: true,
      message: `Xóa mẫu form "${tpl.name}" (${tpl.code})?\n\nFile .docx trên server cũng sẽ bị xóa.`,
      onConfirm: async () => {
        setConfirmModal((prev) => ({ ...prev, isOpen: false }));
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
      }
    });
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
    setConfirmModal({
      isOpen: true,
      message: `Xóa vĩnh viễn hồ sơ "${applicant.display_name}"?\n\nToàn bộ dữ liệu trong database (giấy tờ, OCR, DS-260, thành viên gia đình) và file upload sẽ bị xóa. Không thể hoàn tác.`,
      onConfirm: async () => {
        setConfirmModal((prev) => ({ ...prev, isOpen: false }));
        setBusy("delete");
        try {
          await api.deleteApplicant(id, { permanent: true, force: true });
          router.push("/dashboard");
        } catch (err) {
          alert(err instanceof Error ? err.message : "Không thể xóa hồ sơ");
        } finally {
          setBusy("");
        }
      }
    });
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
                <label className="label">Chủ hồ sơ (người đứng đơn chính)</label>
                <input
                  className="input"
                  value={setupPrincipalName}
                  onChange={(e) => setSetupPrincipalName(e.target.value)}
                  placeholder="DANG VAN HUNG hoặc MAI THI HUONG"
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
                <div className="sm:col-span-2">
                  <label className="label">
                    Thêm cháu nội/ngoại (phân cách bằng dấu phẩy)
                  </label>
                  <input
                    className="input"
                    value={appendGrandchildNames}
                    onChange={(e) => setAppendGrandchildNames(e.target.value)}
                    placeholder="DANG GIA BAO, DANG GIA HAN"
                  />
                  <p className="mt-1 text-xs text-slate-500">
                    Cha/mẹ của cháu được lấy từ GKS của cháu và khớp với thành viên
                    &quot;Con&quot; tương ứng (cây gia phả).
                  </p>
                </div>
                <div className="sm:col-span-2">
                  <label className="label">
                    Thêm anh/chị/em được bảo lãnh (phân cách bằng dấu phẩy)
                  </label>
                  <input
                    className="input"
                    value={appendSiblingNames}
                    onChange={(e) => setAppendSiblingNames(e.target.value)}
                    placeholder="DANG VAN MINH, DANG THI LAN"
                  />
                  <p className="mt-1 text-xs text-slate-500">
                    Anh/chị/em là đương đơn đầy đủ (có vợ/chồng, con riêng); nếu GKS riêng
                    thiếu cha/mẹ thì kế thừa cha/mẹ của đương đơn chính.
                  </p>
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
                        onFieldSaved={(updatedForm, savedMemberId) => {
                          if (updatedForm) {
                            if (savedMemberId) {
                              setDs260FormsByMember((prev) => ({ ...prev, [savedMemberId]: updatedForm }));
                              if (savedMemberId === selectedMemberId) {
                                setDs260Form(updatedForm);
                              }
                            } else {
                              setDs260Form(updatedForm);
                            }
                          }
                          // Cập nhật validation & conflict trong background không reload lại toàn trang
                          api.getDs260Validation(id).then(setDs260Validation).catch(() => undefined);
                          api.getDs260Conflicts(id).then(setDs260Conflicts).catch(() => undefined);
                        }}
                        onExport={(member) => {
                          if (member.id === PRINCIPAL_ONLY_ID) void exportDs260();
                          else void exportDs260ForMember(member);
                        }}
                        exportBusy={
                          m.id === PRINCIPAL_ONLY_ID
                            ? busy === "export-ds260"
                            : busy === `export-ds260-${m.id}`
                        }
                        ds260Conflicts={ds260Conflicts}
                        isFamilyCase={caseMembers.length > 1}
                        ds260Validation={m.id === PRINCIPAL_ONLY_ID ? ds260Validation : undefined}
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
              warnings={ds260Validation?.warnings ?? []}
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
            {ds260Validation.errors.length > 0 && (
              <ul className="mt-3 space-y-1 text-sm text-red-800">
                {ds260Validation.errors.map((e, i) => (
                  <li key={`err-${i}`}>• {e.message}</li>
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

        {showConflictModal && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div
              className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm transition-opacity duration-300 ease-out"
              onClick={() => setShowConflictModal(false)}
            />
            <div className="relative z-10 w-full max-w-md transform overflow-hidden rounded-2xl bg-white p-6 shadow-2xl transition-all duration-300 ease-out scale-100 border border-slate-100">
              <div className="flex flex-col items-center text-center">
                <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-amber-50 text-amber-500 shadow-inner ring-4 ring-amber-100/50">
                  <svg
                    className="h-7 w-7"
                    fill="none"
                    viewBox="0 0 24 24"
                    strokeWidth="2"
                    stroke="currentColor"
                    aria-hidden="true"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
                    />
                  </svg>
                </div>

                <h3 className="text-xl font-bold text-slate-900 mb-2">
                  Phát hiện xung đột dữ liệu!
                </h3>
                
                <p className="text-sm text-slate-500 mb-6 leading-relaxed">
                  Hệ thống phát hiện có sự bất nhất hoặc xung đột dữ liệu giữa các giấy tờ đã upload. Vui lòng nhờ nhân viên đối chiếu và chọn giá trị chính xác nhất.
                </p>
              </div>

              <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
                <button
                  type="button"
                  className="w-full sm:w-auto px-5 py-2.5 rounded-xl border border-slate-200 text-sm font-medium text-slate-600 hover:bg-slate-50 hover:text-slate-800 transition duration-200"
                  onClick={() => setShowConflictModal(false)}
                >
                  Đã biết
                </button>
                <button
                  type="button"
                  className="w-full sm:w-auto px-5 py-2.5 rounded-xl bg-gradient-to-r from-amber-500 to-orange-500 text-sm font-semibold text-white hover:from-amber-600 hover:to-orange-600 transition duration-200 shadow-md hover:shadow-lg focus:outline-none focus:ring-2 focus:ring-amber-500 focus:ring-offset-2"
                  onClick={() => {
                    setShowConflictModal(false);
                    const element = document.getElementById("ds260-conflicts-section");
                    if (element) {
                      element.scrollIntoView({ behavior: "smooth", block: "center" });
                    }
                  }}
                >
                  Xử lý ngay
                </button>
              </div>
            </div>
          </div>
        )}

        {hasShownAddressWarningModal && ds260Validation && (
          <AddressWarningModal
            warnings={ds260Validation.warnings}
            onDismiss={() => setHasShownAddressWarningModal(false)}
          />
        )}

        {confirmModal.isOpen && (
          <div className="fixed inset-0 z-[9998] flex items-center justify-center p-4">
            <div
              className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm transition-opacity duration-300 ease-out"
              onClick={() => setConfirmModal((prev) => ({ ...prev, isOpen: false }))}
            />
            <div className="relative z-10 w-full max-w-sm transform overflow-hidden rounded-2xl bg-white p-6 shadow-2xl transition-all duration-300 ease-out scale-100 border border-slate-100 text-center animate-in fade-in zoom-in-95 duration-200">
              <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-amber-50 text-amber-500 shadow-inner ring-4 ring-amber-100/50">
                <svg
                  className="h-7 w-7"
                  fill="none"
                  viewBox="0 0 24 24"
                  strokeWidth="2.5"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M9.879 7.519c1.171-1.025 3.071-1.025 4.242 0 1.172 1.025 1.172 2.687 0 3.712-.203.179-.43.326-.67.442-.745.361-1.45.999-1.45 1.827v.75M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9 5.25h.008v.008H12v-.008z"
                  />
                </svg>
              </div>

              <h3 className="text-lg font-bold text-slate-900 mb-2">
                Xác nhận yêu cầu
              </h3>

              <p className="text-sm text-slate-500 mb-6 leading-relaxed whitespace-pre-line text-center">
                {confirmModal.message}
              </p>

              <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
                <button
                  type="button"
                  className="w-full sm:w-auto px-5 py-2.5 rounded-xl border border-slate-200 text-sm font-medium text-slate-600 hover:bg-slate-50 hover:text-slate-800 transition duration-200"
                  onClick={() => setConfirmModal((prev) => ({ ...prev, isOpen: false }))}
                >
                  Hủy
                </button>
                <button
                  type="button"
                  className="w-full sm:w-auto px-5 py-2.5 rounded-xl bg-gradient-to-r from-amber-500 to-orange-500 text-sm font-semibold text-white hover:from-amber-600 hover:to-orange-600 transition duration-200 shadow-md hover:shadow-lg focus:outline-none"
                  onClick={confirmModal.onConfirm}
                >
                  Xác nhận
                </button>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
