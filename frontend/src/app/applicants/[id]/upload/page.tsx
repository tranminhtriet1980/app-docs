"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import StatusBadge from "@/components/StatusBadge";
import { api, Applicant, CaseMember, Document, DocumentTypeGuide, getToken } from "@/lib/api";
import { memberColorByNumber } from "@/lib/memberColors";
import {
  buildExtraNamingExamples,
  buildFullNamingTableRows,
  FAMILY_NAMING_EXAMPLE,
  slotsForRole,
  suggestedUploadFilename,
} from "@/lib/memberFileNaming";

function memberRoleShort(role: CaseMember["role"]) {
  if (role === "principal") return "Chủ hồ sơ";
  if (role === "spouse") return "Phối ngẫu";
  return "Con";
}

export default function UploadPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [email, setEmail] = useState("");
  const [applicant, setApplicant] = useState<Applicant | null>(null);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [deletingId, setDeletingId] = useState<string>("");
  const [reprocessingAll, setReprocessingAll] = useState(false);
  const [docTypes, setDocTypes] = useState<DocumentTypeGuide[]>([]);
  const [deletingApplicant, setDeletingApplicant] = useState(false);
  const [caseMembers, setCaseMembers] = useState<CaseMember[]>([]);

  const fullNamingRows = useMemo(() => buildFullNamingTableRows(), []);
  const extraNamingRows = useMemo(
    () => buildExtraNamingExamples(FAMILY_NAMING_EXAMPLE[0]),
    [],
  );

  const sortedDocuments = useMemo(() => {
    const fileSeq = (doc: Document) => {
      const label = doc.member_file_label || "";
      const tail = label.includes("_") ? label.split("_")[1] : "";
      const n = parseInt(tail, 10);
      return Number.isFinite(n) ? n : 99;
    };
    const memberSeq = (doc: Document) => {
      const n = parseInt(doc.member_number || "99", 10);
      return Number.isFinite(n) ? n : 99;
    };
    return [...documents].sort((a, b) => {
      const ma = memberSeq(a);
      const mb = memberSeq(b);
      if (ma !== mb) return ma - mb;
      const fa = fileSeq(a);
      const fb = fileSeq(b);
      if (fa !== fb) return fa - fb;
      return a.original_filename.localeCompare(b.original_filename);
    });
  }, [documents]);

  const load = useCallback(async () => {
    const [user, app, docs, members] = await Promise.all([
      api.me(),
      api.getApplicant(id),
      api.listDocuments(id),
      api.listCaseMembers(id).catch(() => [] as CaseMember[]),
    ]);
    setEmail(user.email);
    setApplicant(app);
    setDocuments(docs);
    setCaseMembers(members);
  }, [id]);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    load().catch(() => router.replace("/dashboard"));
    api.listDocumentTypes().then(setDocTypes).catch(() => undefined);
    const timer = setInterval(() => {
      load().catch(() => undefined);
    }, 4000);
    return () => clearInterval(timer);
  }, [load, router]);

  const uploadFiles = async (files: FileList | File[]) => {
    const list = Array.from(files);
    if (!list.length) return;
    setUploading(true);
    try {
      if (list.length > 1) {
        const uploaded = await api.uploadDocumentsBatch(id, list);
        if (!uploaded.length) {
          throw new Error("Không file nào được chấp nhận. Dùng PDF, Word, Excel, ảnh hoặc TXT (tối đa 20MB/file).");
        }
      } else {
        await api.uploadDocument(id, list[0]);
      }
      await load();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Upload thất bại");
    } finally {
      setUploading(false);
    }
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files);
  };

  const deleteDocument = async (doc: Document) => {
    const ok = window.confirm(`Xóa tài liệu "${doc.original_filename}"?`);
    if (!ok) return;
    setDeletingId(doc.id);
    try {
      await api.deleteDocument(id, doc.id);
      await load();
    } finally {
      setDeletingId("");
    }
  };

  const reprocessAll = async () => {
    if (!documents.length) return;
    const ok = window.confirm(
      "Chạy lại OCR cho toàn bộ tài liệu? Quá trình này có thể mất vài phút."
    );
    if (!ok) return;
    setReprocessingAll(true);
    try {
      await api.reprocessAllDocuments(id);
      await load();
    } finally {
      setReprocessingAll(false);
    }
  };

  const deleteApplicant = async () => {
    if (!applicant) return;
    const ok = window.confirm(
      `Xóa vĩnh viễn hồ sơ "${applicant.display_name}"?\n\nToàn bộ dữ liệu trong database (giấy tờ, OCR, DS-260, thành viên gia đình) và file upload sẽ bị xóa. Không thể hoàn tác.`
    );
    if (!ok) return;
    setDeletingApplicant(true);
    try {
      await api.deleteApplicant(id, { permanent: true, force: true });
      router.push("/dashboard");
    } catch (err) {
      alert(err instanceof Error ? err.message : "Không thể xóa hồ sơ");
    } finally {
      setDeletingApplicant(false);
    }
  };

  return (
    <div>
      <main className="mx-auto max-w-6xl">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <Link href="/dashboard" className="text-sm text-accent hover:underline">
              ← Quay lại
            </Link>
            <h1 className="mt-2 text-2xl font-bold">Upload Dashboard</h1>
            {applicant && (
              <p className="text-slate-500">
                {applicant.display_name} · <StatusBadge status={applicant.status} />
              </p>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            <Link href={`/applicants/${id}/review`} className="btn-primary">
              Review hồ sơ →
            </Link>
            <button
              type="button"
              className="btn-secondary text-red-700 hover:border-red-200 hover:bg-red-50"
              disabled={deletingApplicant}
              onClick={deleteApplicant}
            >
              {deletingApplicant ? "Đang xóa…" : "Xóa hồ sơ"}
            </button>
          </div>
        </div>

        <div
          className={`card mb-8 border-2 border-dashed p-10 text-center transition ${
            dragOver ? "border-accent bg-blue-50" : "border-slate-300"
          }`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
        >
          <p className="mb-2 font-medium">Kéo thả giấy tờ vào đây</p>
          <p className="mb-1 text-sm text-slate-500">
            PDF, Word, Excel, ảnh, TXT — upload hàng loạt, tối đa 20MB/file
          </p>
          {applicant?.is_family_bundle && (
            <p className="mb-4 text-sm text-brand-700">
              Bộ hồ sơ gia đình — đặt tên: <code className="rounded bg-white px-1">01_1</code> chủ hồ sơ,{" "}
              <code className="rounded bg-white px-1">02_1</code> vợ/chồng,{" "}
              <code className="rounded bg-white px-1">03_1</code>…<code className="rounded bg-white px-1">06_4</code>{" "}
              các con (xem bảng mapping bên dưới).
            </p>
          )}
          <input
            ref={inputRef}
            type="file"
            multiple
            className="hidden"
            accept=".pdf,.jpg,.jpeg,.png,.webp,.doc,.docx,.xlsx,.xls,.txt"
            onChange={(e) => e.target.files && uploadFiles(e.target.files)}
          />
          <div className="flex flex-wrap items-center justify-center gap-3">
            <button type="button" className="btn-primary" disabled={uploading} onClick={() => inputRef.current?.click()}>
              {uploading ? "Đang upload..." : "Chọn file"}
            </button>
            <button
              type="button"
              className="btn-secondary"
              disabled={reprocessingAll || documents.length === 0}
              onClick={reprocessAll}
            >
              {reprocessingAll ? "Đang reprocess..." : "Reprocess all PDFs"}
            </button>
          </div>
        </div>

        {caseMembers.length > 0 && (
          <div className="card mb-6 border-brand-200 bg-brand-50/40">
            <h2 className="mb-3 font-semibold text-brand-950">Danh sách người trong hồ sơ (số dùng khi đặt tên file)</h2>
            <div className="flex flex-wrap gap-2">
              {caseMembers.map((m) => {
                const colors = memberColorByNumber(m.member_number);
                return (
                <div
                  key={m.id}
                  className={`rounded-lg border px-3 py-2 text-sm shadow-sm ${colors.cardBorder} ${colors.cardBg}`}
                >
                  <span
                    className={`mr-2 inline-flex h-7 min-w-[2rem] items-center justify-center rounded-md px-2 font-bold text-white ${colors.badge}`}
                  >
                    {m.member_number || "—"}
                  </span>
                  <span className="font-medium text-slate-900">{m.display_name}</span>
                  <span className="ml-2 text-xs text-slate-500">({memberRoleShort(m.role)})</span>
                  <p className="mt-2 text-xs text-slate-600">
                    {slotsForRole(m.role).map((slot) => (
                      <span key={slot.seq} className="mr-2 inline-block">
                        <code className="rounded bg-white/90 px-1 font-mono text-[11px]">
                          {suggestedUploadFilename(
                            m.member_number || "01",
                            slot.seq,
                            slot.filenamePart,
                            m.display_name,
                          )}
                        </code>
                      </span>
                    ))}
                  </p>
                </div>
              );
              })}
            </div>
            <p className="mt-3 text-xs text-slate-600">
              Mỗi người một màu. <strong>4 file chuẩn</strong>{" "}
              <code>_1</code> GKS · <code>_2</code> HC · <code>_3</code> ly hôn · <code>_4</code> lý lịch — file
              thêm tiếp tục <code>_5</code>, <code>_6</code>, <code>_7</code>…
              Mã người: <strong>01</strong> chủ hồ sơ, <strong>02</strong> vợ/chồng, <strong>03–06</strong> con 1–4.
            </p>
          </div>
        )}

        {docTypes.length > 0 && (
          <>
            <div className="card mb-6 border-brand-200 bg-brand-50/40 text-sm">
              <h2 className="mb-2 font-semibold text-brand-950">
                Bảng mapping đặt tên file — chủ hồ sơ · vợ/chồng · con 1–4
              </h2>
              <p className="mb-3 text-brand-900/90">
                Upload <strong>một lần</strong> cho cả gia đình. Mỗi người mã <strong>01</strong>–<strong>06</strong>,
                mỗi file <strong>_1</strong> đến <strong>_4</strong> (chuẩn), tiếp tục <strong>_5</strong>,{" "}
                <strong>_6</strong>… nếu có thêm giấy.
              </p>
              <div className="mb-4 overflow-x-auto rounded-lg border border-brand-200 bg-white">
                <table className="w-full min-w-[800px] text-left text-xs">
                  <thead>
                    <tr className="border-b border-brand-200 bg-brand-50 text-brand-900">
                      <th className="py-2 pl-3 pr-3">Mã</th>
                      <th className="py-2 pr-3">Người</th>
                      <th className="py-2 pr-3">Họ tên (ví dụ)</th>
                      <th className="py-2 pr-3">STT</th>
                      <th className="py-2 pr-3">Loại giấy</th>
                      <th className="py-2 pr-3">Tên file gợi ý</th>
                    </tr>
                  </thead>
                  <tbody className="font-mono text-brand-950">
                    {fullNamingRows.map((row) => (
                      <tr key={`${row.code}-${row.seq}`} className={`border-b border-brand-100 ${row.rowTint}`}>
                        {row.isFirstOfMember ? (
                          <>
                            <td
                              className={`py-2 pl-3 pr-3 font-sans font-bold ${row.codeTint}`}
                              rowSpan={row.memberRowSpan}
                            >
                              {row.code}
                            </td>
                            <td
                              className="py-2 pr-3 font-sans font-medium"
                              rowSpan={row.memberRowSpan}
                            >
                              {row.roleLabel}
                            </td>
                            <td
                              className="py-2 pr-3 font-sans text-slate-700"
                              rowSpan={row.memberRowSpan}
                            >
                              {row.displayName}
                            </td>
                          </>
                        ) : null}
                        <td className="py-2 pr-3 font-sans">{row.seqLabel}</td>
                        <td className="py-2 pr-3 font-sans">{row.docLabel}</td>
                        <td className="py-2 pr-3">{row.filename}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="mb-4 overflow-x-auto rounded-lg border border-slate-200 bg-white">
                <h3 className="border-b border-slate-200 bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-800">
                  File bổ sung (ví dụ chủ hồ sơ — _5, _6, _7…)
                </h3>
                <table className="w-full min-w-[800px] text-left text-xs">
                  <thead>
                    <tr className="border-b text-slate-600">
                      <th className="py-2 pl-3 pr-3">Mã</th>
                      <th className="py-2 pr-3">STT</th>
                      <th className="py-2 pr-3">Loại giấy</th>
                      <th className="py-2 pr-3">Tên file gợi ý</th>
                    </tr>
                  </thead>
                  <tbody className="font-mono text-slate-800">
                    {extraNamingRows.map((row) => (
                      <tr key={`extra-${row.seq}`} className="border-b border-slate-100 bg-slate-50/80">
                        <td className="py-2 pl-3 pr-3 font-sans font-bold text-blue-800">01</td>
                        <td className="py-2 pr-3 font-sans">{row.seqLabel}</td>
                        <td className="py-2 pr-3 font-sans">{row.docLabel}</td>
                        <td className="py-2 pr-3">{row.filename}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {caseMembers.length > 0 && (
                <div className="mb-4 overflow-x-auto rounded-lg border border-slate-200 bg-white">
                  <h3 className="border-b border-slate-200 bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-800">
                    Gợi ý theo hồ sơ hiện tại
                  </h3>
                  <table className="w-full min-w-[720px] text-left text-xs">
                    <thead>
                      <tr className="border-b text-slate-600">
                        <th className="py-2 pl-3 pr-3">Mã</th>
                        <th className="py-2 pr-3">Vai trò</th>
                        <th className="py-2 pr-3">Họ tên</th>
                        <th className="py-2 pr-3">STT</th>
                        <th className="py-2 pr-3">Loại giấy</th>
                        <th className="py-2 pr-3">Tên file gợi ý</th>
                      </tr>
                    </thead>
                    <tbody>
                      {caseMembers.flatMap((m) => {
                        const colors = memberColorByNumber(m.member_number);
                        return slotsForRole(m.role).map((slot) => (
                          <tr key={`${m.id}-${slot.seq}`} className={`border-b border-slate-100 ${colors.cardBg}`}>
                            <td className="py-2 pl-3 pr-3">
                              <span
                                className={`inline-flex rounded px-1.5 py-0.5 text-[11px] font-bold text-white ${colors.badge}`}
                              >
                                {m.member_number}_{slot.seq}
                              </span>
                            </td>
                            <td className="py-2 pr-3 font-sans">{memberRoleShort(m.role)}</td>
                            <td className="py-2 pr-3 font-sans font-medium">{m.display_name}</td>
                            <td className="py-2 pr-3 font-sans">_{slot.seq}</td>
                            <td className="py-2 pr-3 font-sans">{slot.docLabel}</td>
                            <td className="py-2 pr-3 font-mono text-[11px]">
                              {suggestedUploadFilename(
                                m.member_number || "01",
                                slot.seq,
                                slot.filenamePart,
                                m.display_name,
                              )}
                            </td>
                          </tr>
                        ));
                      })}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="text-xs text-brand-800">
                <strong>Giấy khai sinh con:</strong> dùng <code className="rounded bg-white px-1">BIRTH CERTIFICATE CHILD</code>{" "}
                (có từ <strong>child</strong>), không dùng <code className="rounded bg-white px-1">BIRTH CERTIFICATE</code> của
                người lớn. File chung (giấy kết hôn) có thể không cần prefix hoặc gán cho chủ hồ sơ.
              </p>
              <p className="mt-2 text-xs text-brand-800">
                Sau upload →{" "}
                <Link href={`/applicants/${id}/review`} className="font-medium underline">
                  Review
                </Link>{" "}
                → xuất <strong>DS-260</strong> riêng từng người.
              </p>
            </div>

            <div className="card mb-6 text-sm">
              <h2 className="mb-2 font-semibold">Luồng 1 — Tên file mẫu chuẩn (Data test)</h2>
              <p className="mb-3 text-slate-600">
                OCR vào bảng <strong>Luồng 1</strong> trên Review — dùng làm nguồn chính điền DS-260.
              </p>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b text-slate-500">
                      <th className="py-1 pr-3">Loại</th>
                      <th className="py-1 pr-3">Tên file chuẩn</th>
                      <th className="py-1">Form</th>
                    </tr>
                  </thead>
                  <tbody>
                    {docTypes
                      .filter((t) =>
                        ["passport", "birth_certificate", "judicial_certificate", "marriage_certificate"].includes(
                          t.code
                        )
                      )
                      .map((t) => (
                        <tr key={t.code} className="border-b border-slate-100">
                          <td className="py-2 pr-3 font-medium">{t.display_name}</td>
                          <td className="py-2 pr-3">{t.standard_filename}.pdf</td>
                          <td className="py-2 text-slate-600">{t.form_section}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="card mb-6 border-amber-200 bg-amber-50/40 text-sm">
              <h2 className="mb-2 font-semibold text-amber-950">
                Nguồn đối chiếu DS-260 — Khách hàng upload
              </h2>
              <p className="mb-3 text-amber-900/90">
                Upload bản khách tự khai / scan để đối chiếu với Luồng 1. Mỗi file = 1 record trong{" "}
                <strong>Bảng đối chiếu</strong> trên Review. Hệ thống tự phát hiện xung đột — bạn chọn
                giá trị đúng trước khi xuất DS-260.
              </p>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-amber-200 text-amber-900">
                      <th className="py-1 pr-3">Loại</th>
                      <th className="py-1 pr-3">Tên file đối chiếu (_new)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {docTypes
                      .filter((t) =>
                        ["passport", "birth_certificate", "judicial_certificate", "marriage_certificate"].includes(
                          t.code
                        )
                      )
                      .map((t) => (
                        <tr key={`ref-${t.code}`} className="border-b border-amber-100">
                          <td className="py-2 pr-3 font-medium">{t.display_name}</td>
                          <td className="py-2 pr-3 font-mono text-amber-900">{t.exception_filename}.pdf</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="card mb-6 border-emerald-200 bg-emerald-50/40 text-sm">
              <h2 className="mb-2 font-semibold text-emerald-950">
                DS-260 khách khai — Toàn bộ worksheet (Personal, Passport, Gia đình, mục 3–5)
              </h2>
              <p className="mb-3 text-emerald-900/90">
                Upload bản DS-260 khách điền sẵn (toàn bộ form ImmiPath). Hệ thống OCR tất cả mục
                và điền vào form xuất — bổ sung chỗ Luồng 1 còn thiếu.
              </p>
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-emerald-200 text-emerald-900">
                    <th className="py-1 pr-3">Loại</th>
                    <th className="py-1 pr-3">Tên file gợi ý</th>
                  </tr>
                </thead>
                <tbody>
                  {docTypes
                    .filter((t) => t.code === "ds260_customer_form")
                    .map((t) => (
                      <tr key="ds260-customer" className="border-b border-emerald-100">
                        <td className="py-2 pr-3 font-medium">{t.display_name}</td>
                        <td className="py-2 pr-3 font-mono text-emerald-900">
                          ds260.pdf · {t.exception_filename}.pdf
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>

            <div className="card mb-6 text-sm">
              <h2 className="mb-2 font-semibold">Các loại giấy tờ khác</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b text-slate-500">
                      <th className="py-1 pr-3">Loại</th>
                      <th className="py-1 pr-3">Tên file chuẩn</th>
                      <th className="py-1 pr-3">File _new</th>
                      <th className="py-1">Form</th>
                    </tr>
                  </thead>
                  <tbody>
                    {docTypes
                      .filter(
                        (t) =>
                          ![
                            "passport",
                            "birth_certificate",
                            "judicial_certificate",
                            "marriage_certificate",
                            "ds260_customer_form",
                          ].includes(t.code)
                      )
                      .map((t) => (
                        <tr key={t.code} className="border-b border-slate-100">
                          <td className="py-2 pr-3 font-medium">{t.display_name}</td>
                          <td className="py-2 pr-3">{t.standard_filename}.pdf</td>
                          <td className="py-2 pr-3 text-amber-800">{t.exception_filename}.pdf</td>
                          <td className="py-2 text-slate-600">{t.form_section}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}

        {documents.some((d) => d.error_message?.includes("quota")) && (
          <div className="card mb-4 border-amber-200 bg-amber-50 text-sm text-amber-900">
            <strong>OpenAI hết quota.</strong> File vẫn được xử lý ở chế độ demo (từ tên file).
            Nạp credits tại{" "}
            <a
              href="https://platform.openai.com/account/billing"
              target="_blank"
              rel="noreferrer"
              className="underline"
            >
              platform.openai.com/billing
            </a>{" "}
            rồi upload lại để OCR thật.
          </div>
        )}

        <div className="card">
          <h2 className="mb-4 font-semibold">Tài liệu đã upload ({documents.length})</h2>
          {documents.length === 0 ? (
            <p className="text-sm text-slate-500">Chưa có tài liệu.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b text-slate-500">
                    <th className="py-2 pr-4">Mã file</th>
                    <th className="py-2 pr-4">File</th>
                    <th className="py-2 pr-4">Loại</th>
                    <th className="py-2 pr-4">Trạng thái</th>
                    <th className="py-2">Confidence</th>
                    <th className="py-2 text-right">Thao tác</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedDocuments.map((doc) => {
                    const colors = memberColorByNumber(doc.member_number);
                    return (
                    <tr
                      key={doc.id}
                      className={`border-b border-slate-100 border-l-4 ${doc.member_number ? colors.rowBorder : "border-l-transparent"}`}
                    >
                      <td className="py-3 pr-4 whitespace-nowrap">
                        {doc.member_number ? (
                          <span className="inline-flex items-center gap-1.5 text-sm">
                            <span
                              className={`inline-flex h-6 min-w-[1.75rem] items-center justify-center rounded px-1.5 text-xs font-bold text-white ${colors.badge}`}
                            >
                              {doc.member_file_label || doc.member_number}
                            </span>
                            <span className="max-w-[8rem] truncate text-slate-600" title={doc.member_display_name || ""}>
                              {doc.member_display_name}
                            </span>
                          </span>
                        ) : (
                          <span className="text-xs text-slate-400">—</span>
                        )}
                      </td>
                      <td className="py-3 pr-4 font-medium">
                        {doc.original_filename}
                        {doc.duplicate_warning && (
                          <span className="ml-2 text-xs text-amber-700">⚠ Trùng file</span>
                        )}
                      </td>
                      <td className="py-3 pr-4">
                        {doc.document_type || "—"}
                        {doc.is_exception && (
                          <span className="ml-2 text-xs text-amber-700">ngoại lệ</span>
                        )}
                      </td>
                      <td className="py-3 pr-4">
                        <StatusBadge status={doc.status} />
                        {doc.error_message && (
                          <p
                            className={`mt-1 text-xs ${
                              doc.status === "extracted" ? "text-amber-700" : "text-red-500"
                            }`}
                          >
                            {doc.error_message}
                          </p>
                        )}
                      </td>
                      <td className="py-3">
                        {doc.classification_confidence != null
                          ? `${Math.round(doc.classification_confidence * 100)}%`
                          : "—"}
                      </td>
                      <td className="py-3 text-right">
                        <button
                          type="button"
                          className="btn-secondary text-xs text-red-700"
                          disabled={deletingId === doc.id}
                          onClick={() => deleteDocument(doc)}
                        >
                          {deletingId === doc.id ? "Đang xóa..." : "Xóa"}
                        </button>
                      </td>
                    </tr>
                  );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
