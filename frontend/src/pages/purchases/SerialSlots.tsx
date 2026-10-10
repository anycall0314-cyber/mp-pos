import { useRef, useState } from "react";

import { MoneyInput } from "@/components/MoneyInput";
import { CodeField, looksLikeImei, routeCodes } from "@/lib/deviceCodes";
import { money } from "@/lib/money";
import { problemOf } from "@/lib/serialCheck";

import {
  applyBelow,
  blankEntry,
  GRADE_OPTIONS,
  SerialEntry,
  setCode,
  setUnitField,
  UnitField,
} from "./serials";

interface Props {
  lineKey: string;
  qty: number;
  entries: SerialEntry[];
  /** 這一行的單價(中古機逐台成本留空時用它) */
  unitPrice: string;
  /** 要逐台記成色 / 售價 / 電池 / 備註(中古機、已拆封) */
  tracksUnit: boolean;
  /** 中古機:每一台可以有自己的進貨成本 */
  isSecondhand: boolean;
  /** 每台刷 IMEI 與 SN 兩個碼 */
  pairMode: boolean;
  disabled: boolean;
  /** 有問題的碼 → 為什麼(鍵 = 去掉符號的碼):已經在系統裡 / 這張單裡重複。標在那一格底下,不自動清掉 */
  problems?: Record<string, string>;
  onChange: (entries: SerialEntry[]) => void;
  onRemoveUnit: (idx: number) => void;
  /** 沒有下一格可刷了:把游標還給掃碼框 */
  onDone: () => void;
}

/**
 * 一行進貨明細底下的序號格子:每台一列,IMEI、SN 各一格(可以都填,也可以只填一格)。
 * 平常不用點進來 —— 掃碼框刷到的設備碼會自己放進這裡;這裡是給「刷錯了要改」「用貼的」「補機況」用的。
 * 在格子裡刷 / 貼的碼一樣照種類放到該放的那一格(`routeCodes`),刷錯格不會把原本的碼蓋掉。
 */
export function SerialSlots({
  lineKey,
  qty,
  entries,
  unitPrice,
  tracksUnit,
  isSecondhand,
  pairMode,
  disabled,
  problems,
  onChange,
  onRemoveUnit,
  onDone,
}: Props) {
  const boxRef = useRef<HTMLDivElement>(null);
  // 每一格在游標進去那一刻的內容:刷錯格時用來還原
  const beforeRef = useRef<Record<string, string>>({});
  const [hint, setHint] = useState<string | null>(null);

  // 游標要「當下」就移過去(每一格本來就都在畫面上):條碼槍下一刷可能緊接著來
  const focusSlot = (target: { idx: number; field: CodeField } | null) => {
    const el = target
      ? boxRef.current?.querySelector<HTMLInputElement>(
          `[data-serial-slot="${lineKey}-${target.idx}-${target.field}"]`,
        )
      : null;
    if (el) el.focus();
    else onDone();
  };

  const place = (
    idx: number,
    typed: { field: CodeField; before: string } | null,
    codes: string[],
  ) => {
    // 一次貼上一串(typed 是空的)跟掃碼框一樣:14~16 碼數字放 IMEI 格,誤讀的不佔掉 SN
    const r = routeCodes(
      entries, qty, idx, typed, codes, blankEntry, pairMode, typed === null,
    );
    onChange(r.entries);
    setHint(
      r.refused
        ? `沒放:${r.refused.code}(這一台還缺 ${r.refused.missing === "sn" ? "SN" : "IMEI"})`
        : r.dropped > 0
          ? "數量已滿,多的碼沒放進去"
          : null,
    );
    focusSlot(r.focus);
  };

  const field = (idx: number, name: UnitField, value: string) =>
    onChange(setUnitField(entries, idx, name, value));

  const imeiWarn = entries
    .slice(0, qty)
    .some((e) => (e.imei ?? "").trim() && !looksLikeImei(e.imei));

  return (
    <div className="wb-serials" ref={boxRef}>
      {imeiWarn && <div className="wb-warn">仍可送出:IMEI 檢查碼不對</div>}
      {hint && <div className="wb-warn">{hint}</div>}
      <table className="wb-slot-table">
        <thead>
          <tr>
            <th className="no">台</th>
            <th>IMEI</th>
            <th>SN</th>
            {tracksUnit && <th className="grade">成色</th>}
            {isSecondhand && <th className="money">成本</th>}
            {tracksUnit && <th className="money">售價</th>}
            {tracksUnit && <th className="pct">電池%</th>}
            {tracksUnit && <th>備註</th>}
            <th className="act"></th>
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: Math.max(0, qty) }).map((_, i) => {
            const entry = entries[i] ?? blankEntry();
            return (
              <tr key={i}>
                <td className="no">{i + 1}</td>
                {(["imei", "sn"] as CodeField[]).map((name) => {
                  const slot = `${lineKey}-${i}-${name}`;
                  const bad =
                    name === "imei" &&
                    !!entry.imei.trim() &&
                    !looksLikeImei(entry.imei);
                  // 已經在系統裡 / 這張單裡重複:留著、標出來(存檔會被擋),不替人清掉
                  const problem = problems ? problemOf(entry[name], problems) : "";
                  return (
                    <td key={name}>
                      <input
                        data-serial-slot={slot}
                        aria-invalid={problem ? true : undefined}
                        className={`wb-mono${bad || problem ? " bad" : ""}`}
                        value={entry[name] ?? ""}
                        disabled={disabled}
                        onChange={(e) =>
                          onChange(setCode(entries, i, name, e.target.value))
                        }
                        onFocus={(e) => {
                          beforeRef.current[slot] = entry[name] ?? "";
                          e.target.select();
                        }}
                        onKeyDown={(e) => {
                          if (e.nativeEvent.isComposing) return;
                          if (e.key === "Escape") {
                            onDone();
                            return;
                          }
                          const typed = (entry[name] ?? "").trim();
                          // 條碼槍刷完送的可能是 Enter,也可能是 Tab:有內容時兩個都照同一套分格
                          const isTab = e.key === "Tab" && !e.shiftKey && !!typed;
                          if (e.key !== "Enter" && !isTab) return;
                          e.preventDefault();
                          if (typed) {
                            place(
                              i,
                              { field: name, before: beforeRef.current[slot] ?? "" },
                              [typed],
                            );
                          } else if (name === "imei") {
                            focusSlot({ idx: i, field: "sn" });
                          } else {
                            focusSlot(
                              i + 1 < qty ? { idx: i + 1, field: "imei" } : null,
                            );
                          }
                        }}
                        onPaste={(e) => {
                          const list = e.clipboardData
                            .getData("text")
                            .split(/[\s,;]+/)
                            .map((x) => x.trim())
                            .filter(Boolean);
                          if (list.length > 1) {
                            e.preventDefault();
                            place(i, null, list);
                          }
                        }}
                      />
                      {problem && <div className="slot-problem">{problem}</div>}
                    </td>
                  );
                })}
                {tracksUnit && (
                  <td className="grade">
                    <select
                      value={entry.grade ?? ""}
                      disabled={disabled}
                      title={GRADE_OPTIONS.find((g) => g.value === entry.grade)?.label}
                      onChange={(e) => field(i, "grade", e.target.value)}
                    >
                      <option value="">—</option>
                      {GRADE_OPTIONS.map((g) => (
                        <option key={g.value} value={g.value} title={g.label}>
                          {g.value}
                        </option>
                      ))}
                    </select>
                  </td>
                )}
                {isSecondhand && (
                  <td className="money">
                    <MoneyInput
                      className="num"
                      min={0}
                      value={entry.cost ?? ""}
                      disabled={disabled}
                      placeholder={money(unitPrice)}
                      title="這一台自己的進貨成本;留空 = 用這一行的單價"
                      onChange={(v) => field(i, "cost", v)}
                    />
                  </td>
                )}
                {tracksUnit && (
                  <td className="money">
                    <MoneyInput
                      className="num"
                      min={0}
                      value={entry.price ?? ""}
                      disabled={disabled}
                      title="這一台的售價;留空 = 用商品的售價"
                      onChange={(v) => field(i, "price", v)}
                    />
                  </td>
                )}
                {tracksUnit && (
                  <td className="pct">
                    <input
                      type="number"
                      className="num num-input"
                      min={0}
                      max={100}
                      value={entry.battery ?? ""}
                      disabled={disabled}
                      onChange={(e) => field(i, "battery", e.target.value)}
                    />
                  </td>
                )}
                {tracksUnit && (
                  <td>
                    <input
                      value={entry.note ?? ""}
                      disabled={disabled}
                      placeholder="刮痕位置 / 配件"
                      onChange={(e) => field(i, "note", e.target.value)}
                    />
                  </td>
                )}
                <td className="act">
                  {tracksUnit && i < qty - 1 && (
                    <button
                      type="button"
                      className="wb-link"
                      disabled={disabled}
                      title="把這一台的成色 / 成本 / 售價 / 電池 / 備註套用到下面每一台"
                      onClick={() => onChange(applyBelow(entries, qty, i))}
                    >
                      套到下面
                    </button>
                  )}
                  <button
                    type="button"
                    className="wb-x"
                    title="拿掉這一台"
                    disabled={disabled}
                    onClick={() => onRemoveUnit(i)}
                  >
                    ✕
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
