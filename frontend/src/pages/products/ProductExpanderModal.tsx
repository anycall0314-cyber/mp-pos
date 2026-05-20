import { useEffect, useMemo, useState } from "react";

import {
  BulkProductRow,
  useBulkCreateProducts,
} from "@/api/hooks";
import { searchCategories } from "@/api/search";
import type { Category } from "@/api/types";
import { Banner } from "@/components/Banner";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { Checkbox, Field } from "@/components/Field";

interface Props {
  open: boolean;
  onClose: () => void;
  onSuccess: (count: number) => void;
}

interface Combo {
  key: string;
  name: string;
  spec: string;
  list_price: string;
  selected: boolean;
}

function splitList(s: string): string[] {
  // 支援 中英文逗號 / 換行 / 空白逗號 一起分割
  return s
    .split(/[,，\n]/g)
    .map((x) => x.trim())
    .filter(Boolean);
}

export function ProductExpanderModal({ open, onClose, onSuccess }: Props) {
  const [model, setModel] = useState("");
  const [category, setCategory] = useState<number | "">("");
  const [categoryOpt, setCategoryOpt] = useState<ComboOption<Category> | null>(
    null,
  );

  // 兩個變化軸 — 標籤可自訂,例如:
  //   手機:容量 / 顏色
  //   配件:功能 / 顏色  或  規格 / 樣式
  const [axis1Label, setAxis1Label] = useState("容量");
  const [axis2Label, setAxis2Label] = useState("顏色");
  const [axis1Text, setAxis1Text] = useState("");
  const [axis2Text, setAxis2Text] = useState("");
  const [pricesText, setPricesText] = useState("");

  // 屬性(預設手機常見組合)
  const [requiresSerial, setRequiresSerial] = useState(true);
  const [allowsTelecomLine, setAllowsTelecomLine] = useState(false);
  const [allowsCommission, setAllowsCommission] = useState(false);

  const [combos, setCombos] = useState<Combo[]>([]);
  const [error, setError] = useState<string | null>(null);

  const mutation = useBulkCreateProducts();

  const axis1Values = useMemo(() => splitList(axis1Text), [axis1Text]);
  const axis2Values = useMemo(() => splitList(axis2Text), [axis2Text]);
  const prices = useMemo(() => splitList(pricesText), [pricesText]);

  // 自動展開預覽
  const previewCombos = useMemo<Combo[]>(() => {
    const m = model.trim();
    if (!m) return [];

    // 建構 (軸1 值, 售價) 配對;沒填軸1 就用單一虛擬項
    const slot1: { val: string; price: string }[] =
      axis1Values.length === 0
        ? [{ val: "", price: prices[0] ?? "0" }]
        : axis1Values.map((v, i) => ({
            val: v,
            // 值多過價時,後面的沿用最後一個價;若完全沒給,用 0
            price: prices[i] ?? prices[prices.length - 1] ?? "0",
          }));

    const slot2 = axis2Values.length === 0 ? [""] : axis2Values;

    const result: Combo[] = [];
    for (const s1 of slot1) {
      for (const s2 of slot2) {
        const parts = [m, s1.val, s2].filter(Boolean);
        const name = parts.join(" ");
        result.push({
          key: name,
          name,
          spec: [s1.val, s2].filter(Boolean).join(" / "),
          list_price: s1.price,
          selected: true,
        });
      }
    }
    return result;
  }, [model, axis1Values, axis2Values, prices]);

  // 表單輸入變動時,自動把預覽結果同步到 combos(保留交集的勾選 / 改價)
  useEffect(() => {
    setCombos((prev) => {
      const prevMap = new Map(prev.map((c) => [c.key, c]));
      return previewCombos.map((p) => {
        const existed = prevMap.get(p.key);
        return existed
          ? { ...p, selected: existed.selected, list_price: existed.list_price }
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

  function patchPrice(key: string, v: string) {
    setCombos((prev) =>
      prev.map((c) => (c.key === key ? { ...c, list_price: v } : c)),
    );
  }

  function reset() {
    setModel("");
    setCategory("");
    setCategoryOpt(null);
    setAxis1Label("容量");
    setAxis2Label("顏色");
    setAxis1Text("");
    setAxis2Text("");
    setPricesText("");
    setRequiresSerial(true);
    setAllowsTelecomLine(false);
    setAllowsCommission(false);
    setCombos([]);
    setError(null);
  }

  // 情境快捷:一鍵套用預設軸標籤與屬性
  function applyPreset(preset: "phone" | "accessory") {
    if (preset === "phone") {
      setAxis1Label("容量");
      setAxis2Label("顏色");
      setRequiresSerial(true);
    } else {
      setAxis1Label("功能");
      setAxis2Label("顏色");
      setRequiresSerial(false);
    }
  }

  async function handleCreate() {
    setError(null);
    if (!category) {
      setError("請選類別");
      return;
    }
    const toCreate = combos.filter((c) => c.selected);
    if (toCreate.length === 0) {
      setError("沒有勾選任何商品");
      return;
    }
    const items: BulkProductRow[] = toCreate.map((c) => ({
      name: c.name,
      spec: c.spec,
      list_price: c.list_price || "0",
    }));
    try {
      const res = await mutation.mutateAsync({
        common: {
          category: Number(category),
          requires_serial: requiresSerial,
          allows_telecom_line: allowsTelecomLine,
          allows_commission: allowsCommission,
          is_active: true,
        },
        items,
      });
      onSuccess(res.count);
      reset();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "建立失敗");
    }
  }

  if (!open) return null;

  const selectedCount = combos.filter((c) => c.selected).length;
  const list = combos.length > 0 ? combos : previewCombos;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-card expander-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="modal-title">型號展開新增</div>

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
            <span style={{ color: "var(--text-dim)", fontSize: 12 }}>
              情境快捷:
            </span>
            <button
              type="button"
              className="btn"
              onClick={() => applyPreset("phone")}
            >
              手機(容量 × 顏色)
            </button>
            <button
              type="button"
              className="btn"
              onClick={() => applyPreset("accessory")}
            >
              配件(功能 × 顏色)
            </button>
            <span style={{ color: "var(--text-dim)", fontSize: 11 }}>
              或自己改下方軸標籤
            </span>
          </div>

          <Field label="型號名稱" required>
            <input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="例:iPhone 16 PRO / iPhone 18 手機殼"
            />
          </Field>

          <Field label="類別" required>
            <ComboBox<Category>
              value={category}
              selectedOption={categoryOpt}
              onChange={(id, opt) => {
                setCategory(id);
                setCategoryOpt(opt ?? null);
              }}
              fetchOptions={searchCategories}
              placeholder="搜尋類別(代碼/名稱)"
            />
          </Field>

          <div className="field-row">
            <Field label="軸 1 標籤">
              <input
                value={axis1Label}
                onChange={(e) => setAxis1Label(e.target.value)}
                placeholder="容量 / 功能 / 規格"
              />
            </Field>
            <Field label={`${axis1Label || "軸 1"} 值(逗號分隔,可留空)`}>
              <input
                value={axis1Text}
                onChange={(e) => setAxis1Text(e.target.value)}
                placeholder="例:256G, 512G / 一般版, 防摔版, MagSafe"
              />
            </Field>
            <Field label={`售價(對應${axis1Label || "軸 1"},可留空)`}>
              <input
                value={pricesText}
                onChange={(e) => setPricesText(e.target.value)}
                placeholder="例:290, 590, 890"
              />
            </Field>
          </div>

          <div className="field-row">
            <Field label="軸 2 標籤">
              <input
                value={axis2Label}
                onChange={(e) => setAxis2Label(e.target.value)}
                placeholder="顏色 / 樣式 / 大小"
              />
            </Field>
            <Field label={`${axis2Label || "軸 2"} 值(逗號分隔,可留空)`}>
              <input
                value={axis2Text}
                onChange={(e) => setAxis2Text(e.target.value)}
                placeholder="例:金, 紫, 黑, 白 / 透明, 霧面"
              />
            </Field>
          </div>

          <div className="fieldset">
            <legend>屬性(套用到所有展開商品)</legend>
            <Checkbox
              checked={requiresSerial}
              onChange={setRequiresSerial}
              label="需追蹤序號(手機/平板=勾)"
            />
            <Checkbox
              checked={allowsTelecomLine}
              onChange={setAllowsTelecomLine}
              label="可綁門號合約"
            />
            <Checkbox
              checked={allowsCommission}
              onChange={setAllowsCommission}
              label="可有業務員佣金"
            />
          </div>

          {list.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  marginBottom: 6,
                }}
              >
                <strong style={{ flex: 1 }}>
                  預覽:展開 {list.length} 筆,勾選 {selectedCount} 筆
                </strong>
                <button
                  className="btn"
                  type="button"
                  onClick={() => toggleAll(true)}
                  style={{ marginRight: 6 }}
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
                      <th>品名</th>
                      <th style={{ width: 120 }}>規格</th>
                      <th className="num" style={{ width: 100 }}>
                        售價
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {list.map((c) => (
                      <tr key={c.key}>
                        <td>
                          <input
                            type="checkbox"
                            checked={c.selected}
                            onChange={(e) =>
                              toggleSelect(c.key, e.target.checked)
                            }
                          />
                        </td>
                        <td>{c.name}</td>
                        <td style={{ color: "var(--text-dim)", fontSize: 11 }}>
                          {c.spec || "—"}
                        </td>
                        <td className="num">
                          <input
                            type="number"
                            step="1"
                            value={c.list_price}
                            onChange={(e) =>
                              patchPrice(c.key, e.target.value)
                            }
                            style={{ width: 80, textAlign: "right" }}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>

        <div className="modal-actions">
          <button className="btn" type="button" onClick={onClose}>
            取消
          </button>
          <button
            className="btn primary"
            type="button"
            onClick={handleCreate}
            disabled={mutation.isPending || selectedCount === 0}
          >
            {mutation.isPending
              ? "建立中…"
              : `建立 ${selectedCount} 筆`}
          </button>
        </div>
      </div>
    </div>
  );
}
