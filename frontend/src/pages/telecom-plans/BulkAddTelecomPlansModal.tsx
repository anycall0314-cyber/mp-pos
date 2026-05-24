import { useEffect, useMemo, useState } from "react";

import { ApiHttpError } from "@/api/client";
import {
  BulkTelecomPlanCommon,
  BulkTelecomPlanRow,
  useBulkCreateTelecomPlans,
} from "@/api/hooks";
import { searchCarriers } from "@/api/search";
import type { Carrier, TelecomPlanKind } from "@/api/types";
import { Banner } from "@/components/Banner";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { Field } from "@/components/Field";

interface Props {
  open: boolean;
  onClose: () => void;
  onSuccess: (count: number) => void;
}

const KIND_OPTIONS: { value: TelecomPlanKind; label: string }[] = [
  { value: "new", label: "新辦" },
  { value: "renewal", label: "續約" },
  { value: "portin", label: "攜碼" },
];

interface Combo {
  key: string;
  name: string;
  monthly_fee: string;
  contract_months: string;
  commission: string;
  selected: boolean;
}

function splitList(s: string): string[] {
  return s
    .split(/[,,\n]/g)
    .map((x) => x.trim())
    .filter(Boolean);
}

export function BulkAddTelecomPlansModal({ open, onClose, onSuccess }: Props) {
  const [carrier, setCarrier] = useState<number | "">("");
  const [carrierOption, setCarrierOption] =
    useState<ComboOption<Carrier> | null>(null);
  const [kind, setKind] = useState<TelecomPlanKind>("new");

  // 名稱前綴(電信商縮寫或自訂),展開後成為 「{prefix} {月租} {綁約}月 {類型}」
  const [namePrefix, setNamePrefix] = useState("");

  // 軸 1:月租清單
  const [feesText, setFeesText] = useState("");
  // 軸 2:綁約月數清單
  const [monthsText, setMonthsText] = useState("");
  // 批次套用佣金:預覽展開後一鍵把所有勾選列的佣金設為此值
  const [bulkCommission, setBulkCommission] = useState("");

  const [combos, setCombos] = useState<Combo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [lineErrors, setLineErrors] = useState<
    Array<{ line: number; errors: unknown }>
  >([]);

  const bulk = useBulkCreateTelecomPlans();

  const fees = useMemo(() => splitList(feesText), [feesText]);
  const months = useMemo(() => splitList(monthsText), [monthsText]);

  const kindLabel =
    KIND_OPTIONS.find((k) => k.value === kind)?.label ?? kind;

  // 自動展開預覽。佣金預設留空,使用者在預覽表逐格填(或用批次套用)
  const previewCombos = useMemo<Combo[]>(() => {
    if (fees.length === 0 || months.length === 0) return [];
    const result: Combo[] = [];
    for (const fee of fees) {
      for (const m of months) {
        const parts = [
          namePrefix.trim(),
          fee,
          `${m}月`,
          kindLabel,
        ].filter(Boolean);
        const name = parts.join(" ");
        result.push({
          key: name,
          name,
          monthly_fee: fee,
          contract_months: m,
          commission: "",
          selected: true,
        });
      }
    }
    return result;
  }, [namePrefix, fees, months, kindLabel]);

  // 輸入變動時把預覽結果同步到 combos(保留交集的勾選 / 改值)
  useEffect(() => {
    setCombos((prev) => {
      const prevMap = new Map(prev.map((c) => [c.key, c]));
      return previewCombos.map((p) => {
        const existed = prevMap.get(p.key);
        return existed
          ? {
              ...p,
              selected: existed.selected,
              monthly_fee: existed.monthly_fee,
              contract_months: existed.contract_months,
              commission: existed.commission,
              name: existed.name,
            }
          : p;
      });
    });
  }, [previewCombos]);

  function toggleSelect(key: string, sel: boolean) {
    setCombos((prev) =>
      prev.map((c) => (c.key === key ? { ...c, selected: sel } : c)),
    );
  }
  function toggleAll(sel: boolean) {
    setCombos((prev) => prev.map((c) => ({ ...c, selected: sel })));
  }
  function patchField(key: string, patch: Partial<Combo>) {
    setCombos((prev) =>
      prev.map((c) => (c.key === key ? { ...c, ...patch } : c)),
    );
  }

  function reset() {
    setNamePrefix("");
    setFeesText("");
    setMonthsText("");
    setBulkCommission("");
    setCombos([]);
    setError(null);
    setLineErrors([]);
  }

  function applyBulkCommission() {
    const v = bulkCommission.trim();
    if (!v) return;
    setCombos((prev) =>
      prev.map((c) => (c.selected ? { ...c, commission: v } : c)),
    );
  }

  function handleClose() {
    reset();
    onClose();
  }

  // 一鍵套用三家常見電信商前綴(輔助)
  function applyCarrierPrefix(p: "中華" | "台哥大" | "遠傳") {
    setNamePrefix(p);
  }

  async function submit() {
    setError(null);
    setLineErrors([]);
    if (!carrier) {
      setError("請選電信商");
      return;
    }
    const toCreate = combos.filter((c) => c.selected);
    if (toCreate.length === 0) {
      setError("沒有勾選任何方案");
      return;
    }
    const missingComm = toCreate.find((c) => !c.commission.trim());
    if (missingComm) {
      setError(
        `「${missingComm.name}」尚未填佣金;請逐筆填或用「批次填佣金」`,
      );
      return;
    }
    // 一律送整數,避免小數點汙染
    const toIntStr = (s: string) => String(Math.round(Number(s) || 0));
    const items: BulkTelecomPlanRow[] = toCreate.map((c) => ({
      name: c.name,
      monthly_fee: toIntStr(c.monthly_fee),
      contract_months: toIntStr(c.contract_months),
      commission: toIntStr(c.commission),
    }));
    const common: BulkTelecomPlanCommon = {
      carrier: carrier as number,
      kind,
      is_active: true,
    };
    try {
      const res = await bulk.mutateAsync({ common, items });
      onSuccess(res.count);
      reset();
    } catch (e) {
      if (e instanceof ApiHttpError) {
        const body = e.body;
        if (typeof body === "object" && body && "errors" in body) {
          setLineErrors(
            (body as { errors: Array<{ line: number; errors: unknown }> })
              .errors,
          );
          setError("部分方案失敗,請修正後重送");
        } else if (typeof body === "object" && body && "detail" in body) {
          setError(String((body as { detail: unknown }).detail));
        } else {
          setError(`儲存失敗 (${e.status})`);
        }
      } else {
        setError(String(e));
      }
    }
  }

  if (!open) return null;

  const list = combos.length > 0 ? combos : previewCombos;
  const selectedCount = combos.filter((c) => c.selected).length;

  return (
    <div className="modal-overlay" onClick={handleClose}>
      <div
        className="modal-card expander-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="modal-title">方案展開新增</div>

        {error && <Banner kind="error" message={error} />}

        <div className="modal-body">
          <div
            style={{
              display: "flex",
              gap: 6,
              marginBottom: 8,
              alignItems: "center",
            }}
          >
            <span style={{ color: "var(--text-dim)", fontSize: 13 }}>
              前綴快捷:
            </span>
            <button
              type="button"
              className="btn"
              onClick={() => applyCarrierPrefix("中華")}
            >
              中華
            </button>
            <button
              type="button"
              className="btn"
              onClick={() => applyCarrierPrefix("台哥大")}
            >
              台哥大
            </button>
            <button
              type="button"
              className="btn"
              onClick={() => applyCarrierPrefix("遠傳")}
            >
              遠傳
            </button>
          </div>

          <div className="field-row">
            <Field label="電信商" required>
              <ComboBox<Carrier>
                value={carrier}
                selectedOption={carrierOption}
                onChange={(id, opt) => {
                  setCarrier(id);
                  setCarrierOption(opt ?? null);
                }}
                fetchOptions={searchCarriers}
                placeholder="搜尋電信商"
              />
            </Field>
            <Field label="類型" required>
              <select
                value={kind}
                onChange={(e) => setKind(e.target.value as TelecomPlanKind)}
              >
                {KIND_OPTIONS.map((k) => (
                  <option key={k.value} value={k.value}>
                    {k.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="名稱前綴">
              <input
                value={namePrefix}
                onChange={(e) => setNamePrefix(e.target.value)}
                placeholder="例:中華 / 台哥大"
              />
            </Field>
          </div>

          <div className="field-row">
            <Field label="月租(逗號分隔)">
              <input
                value={feesText}
                onChange={(e) => setFeesText(e.target.value)}
                placeholder="例:599, 999, 1399"
              />
            </Field>
            <Field label="綁約月數(逗號分隔)">
              <input
                value={monthsText}
                onChange={(e) => setMonthsText(e.target.value)}
                placeholder="例:24, 30, 36"
              />
            </Field>
          </div>
          <div
            style={{
              fontSize: 12,
              color: "var(--text-dim)",
              marginTop: -4,
              marginBottom: 8,
            }}
          >
            佣金因月租與綁約組合而異,請在下方預覽表逐筆填寫
            (相同數字可用「批次套用」一鍵帶入)
          </div>

          {list.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  marginBottom: 6,
                }}
              >
                <strong style={{ flex: 1 }}>
                  預覽:展開 {list.length} 筆,勾選 {selectedCount} 筆
                </strong>
                <span style={{ fontSize: 12, color: "var(--text-dim)" }}>
                  批次填佣金:
                </span>
                <input
                  type="number"
                  step="1"
                  min="0"
                  value={bulkCommission}
                  onChange={(e) => setBulkCommission(e.target.value)}
                  placeholder="例 8000"
                  style={{ width: 90, textAlign: "right" }}
                />
                <button
                  className="btn"
                  type="button"
                  onClick={applyBulkCommission}
                  disabled={!bulkCommission.trim() || selectedCount === 0}
                  title="把上面數字套用到所有勾選的列"
                >
                  套用
                </button>
                <button
                  className="btn"
                  type="button"
                  onClick={() => toggleAll(true)}
                >
                  全選
                </button>
                <button
                  className="btn"
                  type="button"
                  onClick={() => toggleAll(false)}
                >
                  全不選
                </button>
              </div>
              <div
                style={{
                  maxHeight: 320,
                  overflow: "auto",
                  border: "1px solid var(--border)",
                  borderRadius: 3,
                }}
              >
                <table className="line-table">
                  <thead>
                    <tr>
                      <th style={{ width: 32 }}></th>
                      <th>專案名稱</th>
                      <th className="num" style={{ width: 80 }}>
                        月租
                      </th>
                      <th className="num" style={{ width: 70 }}>
                        綁約
                      </th>
                      <th className="num" style={{ width: 90 }}>
                        佣金
                      </th>
                      <th style={{ width: 80 }}>錯誤</th>
                    </tr>
                  </thead>
                  <tbody>
                    {list.map((c, i) => {
                      const err = lineErrors.find((e) => e.line === i + 1);
                      return (
                        <tr
                          key={c.key}
                          className={err ? "row-void" : undefined}
                        >
                          <td>
                            <input
                              type="checkbox"
                              checked={c.selected}
                              onChange={(e) =>
                                toggleSelect(c.key, e.target.checked)
                              }
                            />
                          </td>
                          <td>
                            <input
                              value={c.name}
                              onChange={(e) =>
                                patchField(c.key, { name: e.target.value })
                              }
                              style={{ width: "100%" }}
                            />
                          </td>
                          <td className="num">
                            <input
                              type="number"
                  step="1"
                  min="0"
                              value={c.monthly_fee}
                              onChange={(e) =>
                                patchField(c.key, {
                                  monthly_fee: e.target.value,
                                })
                              }
                              style={{ width: 70, textAlign: "right" }}
                            />
                          </td>
                          <td className="num">
                            <input
                              type="number"
                  step="1"
                  min="0"
                              value={c.contract_months}
                              onChange={(e) =>
                                patchField(c.key, {
                                  contract_months: e.target.value,
                                })
                              }
                              style={{ width: 60, textAlign: "right" }}
                            />
                          </td>
                          <td className="num">
                            <input
                              type="number"
                  step="1"
                  min="0"
                              value={c.commission}
                              onChange={(e) =>
                                patchField(c.key, {
                                  commission: e.target.value,
                                })
                              }
                              style={{ width: 80, textAlign: "right" }}
                            />
                          </td>
                          <td
                            style={{ color: "#ff7070", fontSize: 12 }}
                          >
                            {err ? JSON.stringify(err.errors) : ""}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>

        <div className="modal-actions">
          <button
            className="btn"
            type="button"
            onClick={handleClose}
            disabled={bulk.isPending}
          >
            取消
          </button>
          <button
            className="btn primary"
            type="button"
            onClick={submit}
            disabled={bulk.isPending || selectedCount === 0}
          >
            {bulk.isPending ? "建立中…" : `建立 ${selectedCount} 筆`}
          </button>
        </div>
      </div>
    </div>
  );
}
