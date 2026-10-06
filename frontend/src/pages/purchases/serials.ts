import type { ConditionGrade } from "@/api/types";
import { CodeField, DeviceCodes, splitCode } from "@/lib/deviceCodes";
import { intStr } from "@/lib/money";

/** 進貨的一台設備:兩個碼 + 逐台的機況(成色、售價、電池、備註;中古機另有自己的成本) */
export interface SerialEntry extends DeviceCodes {
  grade?: ConditionGrade;
  cost?: string;
  price?: string;
  battery?: string;
  note?: string;
}

export type UnitField = "grade" | "cost" | "price" | "battery" | "note";

export const blankEntry = (): SerialEntry => ({ imei: "", sn: "" });

export const GRADE_OPTIONS: { value: ConditionGrade; label: string }[] = [
  { value: "S", label: "S 媲美新機" },
  { value: "A", label: "A 95%新以上" },
  { value: "B", label: "B 85-95%新" },
  { value: "C", label: "C 70-85%新" },
  { value: "D", label: "D 瑕疵 / 需報備" },
];

/** 伺服器 / 草稿裡的一台(可能是舊格式:純字串,或只有 sn)整理成兩格 */
export function normalizeSerialEntry(raw: unknown): SerialEntry {
  if (typeof raw === "string") return splitCode(raw);
  if (raw && typeof raw === "object") {
    const r = raw as Record<string, unknown>;
    // 有 imei 這個鍵 = 兩格都是明講的;沒有 = 舊格式(sn 就是「那個序號」),像 IMEI 就放 IMEI 那一格
    const entry: SerialEntry =
      "imei" in r
        ? { imei: String(r.imei ?? ""), sn: String(r.sn ?? "") }
        : splitCode(String(r.sn ?? ""));
    if (r.grade) entry.grade = String(r.grade) as ConditionGrade;
    if (r.cost !== undefined && r.cost !== null && r.cost !== "")
      entry.cost = intStr(r.cost);
    if (r.price !== undefined && r.price !== null && r.price !== "")
      entry.price = intStr(r.price);
    if (r.battery !== undefined && r.battery !== null && r.battery !== "")
      entry.battery = String(r.battery);
    if (r.note) entry.note = String(r.note);
    return entry;
  }
  return blankEntry();
}

/**
 * 有填碼的設備(IMEI、SN 至少一個);兩格都送出去,後端照寫的放。
 * 只看數量以內的那幾台:數量改小之後,多出來那幾台看不到也刪不掉,不能算進去。
 */
export function filledSerials(entries: SerialEntry[], qty: number): SerialEntry[] {
  return entries
    .slice(0, Math.max(0, qty))
    .map((e) => ({ ...e, imei: (e.imei ?? "").trim(), sn: (e.sn ?? "").trim() }))
    .filter((e) => e.imei || e.sn);
}

export function setCode(
  entries: SerialEntry[],
  idx: number,
  field: CodeField,
  value: string,
): SerialEntry[] {
  const next = [...entries];
  while (next.length <= idx) next.push(blankEntry());
  next[idx] = { ...next[idx], [field]: value };
  return next;
}

export function setUnitField(
  entries: SerialEntry[],
  idx: number,
  field: UnitField,
  value: string,
): SerialEntry[] {
  const next = [...entries];
  while (next.length <= idx) next.push(blankEntry());
  const trimmed = value.trim();
  const updated = { ...next[idx] };
  if (trimmed === "") {
    delete (updated as Record<string, unknown>)[field];
  } else if (field === "grade") {
    updated.grade = trimmed as ConditionGrade;
  } else {
    (updated as Record<string, string>)[field] = trimmed;
  }
  next[idx] = updated;
  return next;
}

/** 把第 fromIdx 台的成色 / 成本 / 售價 / 電池 / 備註套用到它下面每一台 */
export function applyBelow(
  entries: SerialEntry[],
  qty: number,
  fromIdx: number,
): SerialEntry[] {
  const source = entries[fromIdx];
  if (!source) return entries;
  const { grade, cost, price, battery, note } = source;
  const next = entries.map((e, i) =>
    i > fromIdx
      ? {
          ...e,
          ...(grade !== undefined ? { grade } : {}),
          ...(cost !== undefined ? { cost } : {}),
          ...(price !== undefined ? { price } : {}),
          ...(battery !== undefined ? { battery } : {}),
          ...(note !== undefined ? { note } : {}),
        }
      : e,
  );
  while (next.length < qty) next.push(blankEntry());
  return next;
}
