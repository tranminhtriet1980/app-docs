/** DS-260 mục A — toàn bộ trường lấy từ file PASSPORT (VN + quốc tế). */

export type PassportFieldDef = {
  key: string;
  label: string;
  aliases?: string[];
};

/** 1) PERSONAL INFORMATION — từ PASSPORT */
export const DS260_PASSPORT_PERSONAL_FIELDS: PassportFieldDef[] = [
  { key: "full_name", label: "Full Name / Họ và tên", aliases: ["name"] },
  { key: "family_name", label: "Surname / Họ", aliases: ["surname", "last_name"] },
  { key: "given_names", label: "Given Names / Tên", aliases: ["given_name", "first_name"] },
  { key: "date_of_birth", label: "Date of Birth / Ngày sinh", aliases: ["dob", "birth_date"] },
  {
    key: "place_of_birth",
    label: "Place of Birth / Nơi sinh",
    aliases: ["birth_place", "birth_city", "city_of_birth"],
  },
  { key: "birth_city", label: "City of Birth / Thành phố sinh", aliases: ["city_of_birth"] },
  {
    key: "birth_state",
    label: "State/Province of Birth / Tỉnh sinh (copy từ place_of_birth)",
    aliases: ["state_of_birth"],
  },
  {
    key: "birth_country",
    label: "Country of Birth / Quốc gia sinh (derive từ place_of_birth, không dùng nationality)",
    aliases: ["country_of_birth"],
  },
  { key: "gender", label: "Sex / Giới tính", aliases: ["sex"] },
  { key: "nationality", label: "Nationality / Quốc tịch", aliases: ["country_of_nationality"] },
  { key: "id_card_number", label: "ID Card N° / Số CMND-CCCD", aliases: ["national_id", "cmnd", "cccd"] },
];

/** 2) PASSPORT / TRAVEL DOCUMENT */
export const DS260_PASSPORT_TRAVEL_FIELDS: PassportFieldDef[] = [
  { key: "passport_type", label: "Type / Loại (P)", aliases: ["document_type", "type"] },
  { key: "country_code", label: "Code / Mã quốc gia (VNM)", aliases: ["passport_country_code"] },
  {
    key: "passport_number",
    label: "Passport N° / Số hộ chiếu",
    aliases: ["passport_no", "passport_id", "document_number"],
  },
  { key: "issue_date", label: "Date of Issue / Ngày cấp", aliases: ["passport_issue_date", "date_of_issue"] },
  {
    key: "expiration_date",
    label: "Date of Expiry / Có giá trị đến",
    aliases: ["expiry_date", "passport_expiry_date", "date_of_expiry"],
  },
  {
    key: "place_of_issue",
    label: "Place of Issue / Nơi cấp",
    aliases: ["issuing_authority", "authority", "passport_place_of_issue"],
  },
  {
    key: "issuing_country",
    label: "Country of Issuance / Quốc gia cấp",
    aliases: ["passport_issuing_country", "country_of_issue"],
  },
];

const ALL_KEYS = new Set(
  [...DS260_PASSPORT_PERSONAL_FIELDS, ...DS260_PASSPORT_TRAVEL_FIELDS].flatMap((f) => [
    f.key,
    ...(f.aliases || []),
  ])
);

export function resolvePassportFieldValue(
  rec: { form_data: Record<string, string>; raw_data: Record<string, string> },
  def: PassportFieldDef
): string {
  if (rec.form_data[def.key]?.trim()) return rec.form_data[def.key].trim();
  for (const k of [def.key, ...(def.aliases || [])]) {
    const v = rec.raw_data[k];
    if (v?.trim()) return v.trim();
  }
  return "";
}

export function extraPassportRawFields(rec: {
  form_data: Record<string, string>;
  raw_data: Record<string, string>;
}): [string, string][] {
  const out: [string, string][] = [];
  for (const [k, v] of Object.entries(rec.raw_data)) {
    if (!v?.trim() || ALL_KEYS.has(k)) continue;
    if (rec.form_data[k]?.trim()) continue;
    out.push([k, v.trim()]);
  }
  return out.sort(([a], [b]) => a.localeCompare(b));
}
