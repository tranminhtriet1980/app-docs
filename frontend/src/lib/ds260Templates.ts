import type { FormTemplate } from "@/lib/api";

export const DS260_DEFAULT_TEMPLATE_CODE = "6_eb3_tt_-___n_ds260_-_h_ng_1";

const NON_DS260_TEMPLATE_CODES = new Set(["ds160_worksheet", "i539_worksheet"]);

/** Mẫu dùng cho xuất DS-260 — code hoặc tên có chứa ds260 (không chỉ prefix). */
export function isDs260FormTemplate(t: FormTemplate): boolean {
  if (NON_DS260_TEMPLATE_CODES.has(t.code)) return false;
  const code = t.code.toLowerCase();
  const name = (t.name || "").toLowerCase();
  return code.includes("ds260") || name.includes("ds260") || name.includes("ds-260");
}

/** Chuẩn hóa mã upload: slug + đảm bảo có ds260 để hiện trong dropdown. */
export function normalizeDs260TemplateCode(raw: string): string {
  let code = raw
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_|_$/g, "");
  if (!code) code = "custom";
  if (!code.includes("ds260")) code = `ds260_${code}`;
  return code;
}

export function listDs260FormTemplates(templates: FormTemplate[]): FormTemplate[] {
  return templates
    .filter(isDs260FormTemplate)
    .filter((t) => t.code !== "ds260_final");
}
