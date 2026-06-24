/** Bốn file chuẩn mỗi người: {mã}_1 … _4; file thêm tiếp tục _5, _6, _7 … */

export type PersonFileSlot = {
  seq: number;
  docLabel: string;
  filenamePart: string;
};

export const PERSON_FILE_SLOTS: PersonFileSlot[] = [
  { seq: 1, docLabel: "Giấy khai sinh", filenamePart: "BIRTH CERTIFICATE" },
  { seq: 2, docLabel: "Hộ chiếu", filenamePart: "PASSPORT" },
  { seq: 3, docLabel: "Quyết định ly hôn", filenamePart: "DIVORCE DECREE" },
  { seq: 4, docLabel: "Lý lịch tư pháp", filenamePart: "JUDICIAL CERTIFICATE" },
];

export const CHILD_FILE_SLOTS: PersonFileSlot[] = [
  { seq: 1, docLabel: "Giấy khai sinh con", filenamePart: "BIRTH CERTIFICATE CHILD" },
  { seq: 2, docLabel: "Hộ chiếu", filenamePart: "PASSPORT" },
  { seq: 3, docLabel: "Quyết định ly hôn (nếu có)", filenamePart: "DIVORCE DECREE" },
  { seq: 4, docLabel: "Lý lịch tư pháp", filenamePart: "JUDICIAL CERTIFICATE" },
];

/** File bổ sung (_5, _6, _7…) — tùy từng hồ sơ */
export const EXTRA_FILE_SLOTS: PersonFileSlot[] = [
  { seq: 5, docLabel: "Giấy kết hôn", filenamePart: "MARRIAGE CERTIFICATE" },
  { seq: 6, docLabel: "DS-260 khách khai", filenamePart: "DS260" },
  { seq: 7, docLabel: "Giấy tờ khác", filenamePart: "DOCUMENT" },
];

export function suggestedUploadFilename(
  memberNumber: string,
  seq: number,
  filenamePart: string,
  displayName: string,
): string {
  return `${memberNumber}_${seq} ${filenamePart} - ${displayName}.pdf`;
}

export function slotsForRole(role: "principal" | "spouse" | "child"): PersonFileSlot[] {
  return role === "child" ? CHILD_FILE_SLOTS : PERSON_FILE_SLOTS;
}

export const MEMBER_CODE_LEGEND = [
  { code: "01", role: "Chủ hồ sơ" },
  { code: "02", role: "Vợ / chồng" },
  { code: "03", role: "Con 1" },
  { code: "04", role: "Con 2" },
  { code: "05", role: "Con 3" },
  { code: "06", role: "Con 4" },
] as const;

export type FamilyMemberTemplate = {
  code: string;
  role: "principal" | "spouse" | "child";
  roleLabel: string;
  displayName: string;
  rowTint: string;
  codeTint: string;
};

/** Bảng mẫu đầy đủ — chủ hồ sơ + vợ + 4 con */
export const FAMILY_NAMING_EXAMPLE: FamilyMemberTemplate[] = [
  {
    code: "01",
    role: "principal",
    roleLabel: "Chủ hồ sơ",
    displayName: "DANG VAN HUNG",
    rowTint: "bg-blue-50/40",
    codeTint: "text-blue-800",
  },
  {
    code: "02",
    role: "spouse",
    roleLabel: "Vợ / chồng",
    displayName: "MAI THI HUONG",
    rowTint: "bg-violet-50/40",
    codeTint: "text-violet-800",
  },
  {
    code: "03",
    role: "child",
    roleLabel: "Con 1",
    displayName: "DANG MAI PHUONG THAO",
    rowTint: "bg-emerald-50/40",
    codeTint: "text-emerald-800",
  },
  {
    code: "04",
    role: "child",
    roleLabel: "Con 2",
    displayName: "DANG KHOI NGUYEN",
    rowTint: "bg-amber-50/40",
    codeTint: "text-amber-800",
  },
  {
    code: "05",
    role: "child",
    roleLabel: "Con 3",
    displayName: "TEN CON 3",
    rowTint: "bg-rose-50/40",
    codeTint: "text-rose-800",
  },
  {
    code: "06",
    role: "child",
    roleLabel: "Con 4",
    displayName: "TEN CON 4",
    rowTint: "bg-cyan-50/40",
    codeTint: "text-cyan-800",
  },
];

export type NamingTableRow = {
  code: string;
  roleLabel: string;
  displayName: string;
  seq: number;
  seqLabel: string;
  docLabel: string;
  filename: string;
  rowTint: string;
  codeTint: string;
  isFirstOfMember: boolean;
  memberRowSpan: number;
};

export function buildFullNamingTableRows(
  members: FamilyMemberTemplate[] = FAMILY_NAMING_EXAMPLE,
): NamingTableRow[] {
  const rows: NamingTableRow[] = [];
  for (const member of members) {
    const slots = slotsForRole(member.role);
    slots.forEach((slot, index) => {
      rows.push({
        code: member.code,
        roleLabel: member.roleLabel,
        displayName: member.displayName,
        seq: slot.seq,
        seqLabel: `_${slot.seq}`,
        docLabel: slot.docLabel,
        filename: suggestedUploadFilename(
          member.code,
          slot.seq,
          slot.filenamePart,
          member.displayName,
        ),
        rowTint: member.rowTint,
        codeTint: member.codeTint,
        isFirstOfMember: index === 0,
        memberRowSpan: slots.length,
      });
    });
  }
  return rows;
}

export function buildExtraNamingExamples(
  member: Pick<FamilyMemberTemplate, "code" | "displayName">,
): NamingTableRow[] {
  return EXTRA_FILE_SLOTS.map((slot, index) => ({
    code: member.code,
    roleLabel: "File thêm",
    displayName: member.displayName,
    seq: slot.seq,
    seqLabel: `_${slot.seq}`,
    docLabel: slot.docLabel,
    filename: suggestedUploadFilename(member.code, slot.seq, slot.filenamePart, member.displayName),
    rowTint: "bg-slate-50/80",
    codeTint: "text-slate-700",
    isFirstOfMember: index === 0,
    memberRowSpan: EXTRA_FILE_SLOTS.length,
  }));
}
