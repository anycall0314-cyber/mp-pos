import { useEffect, useMemo, useRef, useState } from "react";

import { resolveProducts, searchProductsForPurchase } from "@/api/search";
import type { Product } from "@/api/types";
import { Banner } from "@/components/Banner";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { pickActiveProduct } from "@/pages/products/pickActiveProduct";

/**
 * 解析後尚未經過商品比對的原始一行
 */
interface RawRow {
  raw: string; // 使用者貼進來的原文,用於提示
  rawProductText: string;
  qty: number;
  unit_price: string;
  serials: string[];
}

/**
 * 經過比對後、可編輯的一行
 */
export interface MatchedRow {
  key: string;
  rawProductText: string;
  productOption: ComboOption<Product> | null;
  qty: number;
  unit_price: string;
  serials: string[];
  selected: boolean;
  /** exact=可靠識別或人工指定;fuzzy=只有一筆夠像,待人確認;ambiguous=好幾筆都像 */
  matchStatus: "exact" | "fuzzy" | "ambiguous" | "none";
}

/**
 * 回傳給父頁的最終結果(只有勾選 + 有商品的列)
 */
export interface BatchPasteResult {
  product: Product;
  qty: number;
  unit_price: string;
  serial_numbers: string[];
}

interface Props {
  open: boolean;
  onClose: () => void;
  onConfirm: (rows: BatchPasteResult[]) => void;
  /** "regular":比對排除中古機;"secondhand-vendor":只比對中古機 */
  mode?: "regular" | "secondhand-vendor";
}

/** 切割「商品 數量 單價 序號」一行(支援 Tab、多個空白、逗號) */
function parseLine(line: string): RawRow | null {
  const t = line.trim();
  if (!t) return null;
  // 優先用 Tab,再用 ; 等切;最後 fallback 多空白
  let parts: string[];
  if (t.includes("\t")) {
    parts = t.split("\t");
  } else if (t.split(/\s{2,}/).length >= 2) {
    parts = t.split(/\s{2,}/);
  } else {
    parts = t.split(/[, ]+/);
  }
  parts = parts.map((p) => p.trim());

  // 至少要有商品 + 數量
  if (parts.length < 2) return null;

  // 最後一個欄位若含分號或多個 IMEI 樣式的字串 → 視為序號;否則第 4 欄
  let productText = parts[0];
  let qty = Number(parts[1] ?? "1");
  let unit_price = parts[2] ?? "0";
  let serialsText = parts.slice(3).join(" ");

  if (!Number.isFinite(qty) || qty < 1) qty = 1;

  const serials = serialsText
    .split(/[;、，,\s]+/)
    .map((s) => s.trim())
    .filter(Boolean);

  return {
    raw: t,
    rawProductText: productText,
    qty,
    unit_price: String(unit_price),
    serials,
  };
}

function makeKey(): string {
  return crypto.randomUUID();
}

/**
 * 一行品名 / 品號 / 條碼 → 既有商品。
 *
 * 只有可靠識別(條碼 / 品號 / 已確認的叫法)才算「確定」;品名一字不差也只是
 * 候選 —— 後端刻意不把它當成可靠識別,前端不能自己升級。
 * 特徵相似的只預填、不預先勾選,要人看過才會進進貨單;好幾筆都像就不預填。
 * 舊版會直接取搜尋結果第一筆並勾選,搜尋放寬之後那樣會把貨入到別款上。
 */
async function matchOne(
  query: string,
  mode: "regular" | "secondhand-vendor",
): Promise<{ product: Product | null; status: MatchedRow["matchStatus"] }> {
  const q = query.trim();
  if (!q) return { product: null, status: "none" };

  const found = await resolveProducts(q, {
    secondhand: mode === "secondhand-vendor",
    limit: 10,
  });
  // 已停用的不預填(要先由管理員恢復)
  const usable = found.candidates.filter((c) => c.selectable);
  if (found.status === "existing" && usable.length === 1) {
    return { product: usable[0].product, status: "exact" };
  }
  const close = usable.filter((c) => c.level === "exact" || c.level === "covers");
  if (close.length === 1) return { product: close[0].product, status: "fuzzy" };
  return { product: null, status: close.length > 1 ? "ambiguous" : "none" };
}

// 下載 CSV 範例(Excel 可直接開啟編輯)
function downloadSampleCsv(mode: "regular" | "secondhand-vendor") {
  // 一般進貨 vs 中古收購,欄位不同
  const rows =
    mode === "secondhand-vendor"
      ? [
          ["商品", "數量", "單價", "序號(分號分隔)", "成色", "售價", "電池%", "備註"],
          ["iPhone 14 Pro 256G 黑色", "1", "25000", "356121234567890", "A", "32000", "92", ""],
          ["iPhone 13 128G 白色", "1", "12000", "356121234567891", "B", "16800", "85", "輕微擦痕"],
        ]
      : [
          ["商品", "數量", "單價", "序號(分號分隔,沒序號可留空)"],
          ["iPhone 16 PRO 256G 金色", "3", "32000", "356121234567890; 356121234567891; 356121234567892"],
          ["iPhone 16 PRO 256G 紫色", "2", "32000", "356121234567893; 356121234567894"],
          ["保護貼-iPhone 16 Pro", "50", "80", ""],
          ["PH-000023", "1", "29000", "356121234567000"],
        ];

  // BOM + CSV(逗號分隔,Excel 直接打開不會亂碼)
  const escape = (s: string) =>
    /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  const csv =
    "﻿" + rows.map((r) => r.map(escape).join(",")).join("\r\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download =
    mode === "secondhand-vendor"
      ? "批次貼上範例_中古機.csv"
      : "批次貼上範例.csv";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function PurchaseBatchPasteModal({
  open,
  onClose,
  onConfirm,
  mode = "regular",
}: Props) {
  const [rawText, setRawText] = useState("");
  const [matching, setMatching] = useState(false);
  const [rows, setRows] = useState<MatchedRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [hasParsed, setHasParsed] = useState(false);

  useEffect(() => {
    if (!open) {
      setRawText("");
      setRows([]);
      setError(null);
      setHasParsed(false);
    }
  }, [open]);

  async function runMatch() {
    setError(null);
    const parsed = rawText
      .split(/\r?\n/)
      .map(parseLine)
      .filter((x): x is RawRow => x !== null);

    if (parsed.length === 0) {
      setError("貼入的內容無法解析,請至少填「商品 數量」");
      return;
    }
    setMatching(true);
    try {
      // 平行查詢:用商品文字查 /products/?search=...
      const matched = await Promise.all(
        parsed.map(async (r) => {
          const { product, status } = await matchOne(r.rawProductText, mode);
          const option: ComboOption<Product> | null = product
            ? {
                id: product.id,
                label: product.name,
                secondary: [product.sku, product.category_name]
                  .filter(Boolean)
                  .join(" / "),
                payload: product,
              }
            : null;
          return {
            key: makeKey(),
            rawProductText: r.rawProductText,
            productOption: option,
            qty: r.qty,
            unit_price: r.unit_price,
            serials: r.serials,
            // 只有確定的才預先勾選;待確認的要人自己勾
            selected: status === "exact",
            matchStatus: status,
          } as MatchedRow;
        }),
      );
      setRows(matched);
      setHasParsed(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "比對失敗");
    } finally {
      setMatching(false);
    }
  }

  // 每一列「第幾次選商品」,用來丟掉過期的非同步回應
  const pickSeq = useRef<Record<string, number>>({});

  function patchRow(key: string, patch: Partial<MatchedRow>) {
    setRows((prev) => prev.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  }

  function removeRow(key: string) {
    setRows((prev) => prev.filter((r) => r.key !== key));
  }

  function addBlankRow() {
    setRows((prev) => [
      ...prev,
      {
        key: makeKey(),
        rawProductText: "",
        productOption: null,
        qty: 1,
        unit_price: "0",
        serials: [],
        selected: true,
        matchStatus: "none",
      },
    ]);
  }

  function toggleAll(sel: boolean) {
    setRows((prev) =>
      // 全選不帶「待確認」的列:那些要一筆一筆看過
      prev.map((r) =>
        r.productOption && r.matchStatus !== "fuzzy"
          ? { ...r, selected: sel }
          : r,
      ),
    );
  }

  const summary = useMemo(() => {
    const total = rows.length;
    const matched = rows.filter((r) => r.productOption).length;
    const selected = rows.filter(
      (r) => r.selected && r.productOption,
    ).length;
    return { total, matched, selected };
  }, [rows]);

  function confirm() {
    const final: BatchPasteResult[] = rows
      .filter((r) => r.selected && r.productOption)
      .map((r) => ({
        product: r.productOption!.payload!,
        qty: r.qty,
        unit_price: r.unit_price,
        serial_numbers: r.serials,
      }));
    if (final.length === 0) {
      setError("沒有勾選任何有效列");
      return;
    }
    // 這裡一個序號就是一台。有貼序號、但個數跟數量不一樣時不能帶回去:
    // 多的會被藏起來、少的會變成缺序號,而且一台的 IMEI 與 SN 會被拆成兩台。
    // 完全沒貼序號是可以的(只帶商品與數量,序號回主畫面再刷;沒刷齊存檔時會擋)。
    const bad = final.find(
      (r) =>
        r.product.requires_serial &&
        r.serial_numbers.length > 0 &&
        r.serial_numbers.length !== r.qty,
    );
    if (bad) {
      setError(
        `「${bad.product.name}」序號 ${bad.serial_numbers.length} 個、數量 ${bad.qty}:一個序號算一台`,
      );
      return;
    }
    onConfirm(final);
  }

  if (!open) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-card batch-paste-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="modal-title">
          {mode === "secondhand-vendor"
            ? "批次貼上中古機明細"
            : "批次貼上明細"}
        </div>

        {error && <Banner kind="error" message={error} />}

        <div className="modal-body">
          {!hasParsed && (
            <>
              <div
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 8,
                  marginBottom: 8,
                }}
              >
                <div style={{ fontSize: 15, color: "var(--text-dim)", flex: 1 }}>
                  從 Excel 複製貼入,商品可用品名、品號或條碼,系統會自動比對,模糊符合會給你下拉再選。
                </div>
                <button
                  type="button"
                  className="btn"
                  style={{ flexShrink: 0, fontSize: 14, whiteSpace: "nowrap" }}
                  onClick={() => downloadSampleCsv(mode)}
                  title="下載 CSV 範例,可用 Excel 打開編輯"
                >
                  下載範例
                </button>
              </div>
              <textarea
                value={rawText}
                onChange={(e) => setRawText(e.target.value)}
                rows={12}
                placeholder={`例:
iPhone 16 PRO 256G 金色\t3\t32000\t356121234567890; 356121234567891; 356121234567892
iPhone 16 PRO 256G 紫色\t2\t32000\t356121234567893; 356121234567894
保護貼-iPhone 16 Pro\t50\t80
PH-000023\t1\t29000\t356121234567000`}
                style={{
                  width: "100%",
                  fontFamily:
                    "ui-monospace, 'SFMono-Regular', Menlo, monospace",
                  fontSize: 15,
                  background: "var(--panel)",
                  color: "var(--text)",
                  border: "1px solid var(--border)",
                  borderRadius: 3,
                  padding: 8,
                }}
              />
            </>
          )}

          {hasParsed && (
            <>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  marginBottom: 8,
                  fontSize: 15,
                }}
              >
                <strong style={{ flex: 1 }}>
                  共 {summary.total} 列,系統比對到 {summary.matched} 個商品,
                  已勾選 {summary.selected} 列
                </strong>
                <button
                  type="button"
                  className="btn"
                  onClick={() => toggleAll(true)}
                  style={{ marginRight: 6 }}
                >
                  全選
                </button>
                <button
                  type="button"
                  className="btn"
                  onClick={() => toggleAll(false)}
                  style={{ marginRight: 6 }}
                >
                  全不選
                </button>
                <button
                  type="button"
                  className="btn"
                  onClick={() => {
                    setHasParsed(false);
                    setRows([]);
                  }}
                >
                  重貼
                </button>
              </div>

              <div
                style={{
                  maxHeight: 380,
                  overflow: "auto",
                  border: "1px solid var(--border)",
                  borderRadius: 3,
                }}
              >
                <table className="line-table">
                  <thead>
                    <tr>
                      <th style={{ width: 32 }}></th>
                      <th>商品(可改)</th>
                      <th style={{ width: 60 }} className="num">
                        數量
                      </th>
                      <th style={{ width: 90 }} className="num">
                        單價
                      </th>
                      <th>序號(逗號 / 分號 / 換行皆可)</th>
                      <th style={{ width: 28 }}></th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => {
                      const statusBadge =
                        r.matchStatus === "exact"
                          ? null
                          : r.matchStatus === "fuzzy"
                          ? (
                              <span
                                style={{
                                  fontSize: 13,
                                  color: "#f0c050",
                                  marginLeft: 4,
                                }}
                              >
                                待確認
                              </span>
                            )
                          : r.matchStatus === "ambiguous"
                          ? (
                              <span
                                style={{
                                  fontSize: 13,
                                  color: "#f0c050",
                                  marginLeft: 4,
                                }}
                              >
                                多筆相似
                              </span>
                            )
                          : (
                              <span
                                style={{
                                  fontSize: 13,
                                  color: "#ff7070",
                                  marginLeft: 4,
                                }}
                              >
                                找不到
                              </span>
                            );
                      return (
                        <tr key={r.key}>
                          <td>
                            <input
                              type="checkbox"
                              checked={r.selected}
                              disabled={!r.productOption}
                              onChange={(e) =>
                                patchRow(r.key, { selected: e.target.checked })
                              }
                            />
                          </td>
                          <td>
                            <div
                              style={{
                                display: "flex",
                                alignItems: "center",
                                gap: 4,
                              }}
                            >
                              <div style={{ flex: 1, minWidth: 200 }}>
                                <ComboBox<Product>
                                  value={r.productOption?.id ?? ""}
                                  selectedOption={r.productOption}
                                  onChange={async (_id, opt) => {
                                    let p = opt?.payload;
                                    // 恢復停用商品要等伺服器回應;這期間如果又選了
                                    // 別的,舊的回應回來時不能把新的選擇蓋掉
                                    const seq = (pickSeq.current[r.key] ?? 0) + 1;
                                    pickSeq.current[r.key] = seq;
                                    if (p) {
                                      try {
                                        const usable = await pickActiveProduct(p);
                                        if (pickSeq.current[r.key] !== seq) return;
                                        if (!usable) return;
                                        p = usable;
                                      } catch (e) {
                                        setError(
                                          e instanceof Error
                                            ? e.message
                                            : "恢復失敗",
                                        );
                                        return;
                                      }
                                    }
                                    patchRow(r.key, {
                                      productOption: opt
                                        ? { ...opt, payload: p }
                                        : null,
                                      selected: !!opt,
                                      matchStatus: opt ? "exact" : "none",
                                    });
                                  }}
                                  fetchOptions={(q) =>
                                    searchProductsForPurchase(
                                      q || r.rawProductText,
                                      {
                                        secondhand:
                                          mode === "secondhand-vendor",
                                      },
                                    )
                                  }
                                  placeholder={
                                    r.rawProductText
                                      ? `原文:${r.rawProductText}`
                                      : "搜尋商品"
                                  }
                                />
                              </div>
                              {statusBadge}
                            </div>
                            {r.rawProductText && r.productOption && (
                              <div
                                style={{
                                  fontSize: 13,
                                  color: "var(--text-dim)",
                                }}
                              >
                                原文:{r.rawProductText}
                              </div>
                            )}
                          </td>
                          <td>
                            <input
                              type="number"
                              step="1"
                              className="num-input"
                              value={r.qty}
                              onChange={(e) =>
                                patchRow(r.key, {
                                  qty: Math.max(1, Number(e.target.value) || 1),
                                })
                              }
                            />
                          </td>
                          <td>
                            <input
                              type="number"
                              step="1"
                              className="num-input"
                              value={r.unit_price}
                              onChange={(e) =>
                                patchRow(r.key, { unit_price: e.target.value })
                              }
                            />
                          </td>
                          <td>
                            <textarea
                              value={r.serials.join("\n")}
                              onChange={(e) =>
                                patchRow(r.key, {
                                  serials: e.target.value
                                    .split(/[;、，,\s]+/)
                                    .map((s) => s.trim())
                                    .filter(Boolean),
                                })
                              }
                              rows={Math.max(1, Math.min(r.serials.length, 4))}
                              placeholder={
                                r.productOption?.payload?.requires_serial
                                  ? "每行一個 IMEI / 序號"
                                  : "配件可留空"
                              }
                              style={{
                                width: "100%",
                                fontFamily:
                                  "ui-monospace, monospace",
                                fontSize: 14,
                              }}
                            />
                          </td>
                          <td>
                            <button
                              type="button"
                              className="btn"
                              style={{ fontSize: 13, padding: "2px 6px" }}
                              onClick={() => removeRow(r.key)}
                              title="刪除這列"
                            >
                              刪除
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <div style={{ marginTop: 8 }}>
                <button type="button" className="btn" onClick={addBlankRow}>
                  + 新增空白列
                </button>
              </div>
            </>
          )}
        </div>

        <div className="modal-actions">
          <button className="btn" type="button" onClick={onClose}>
            取消
          </button>
          {!hasParsed && (
            <button
              className="btn primary"
              type="button"
              onClick={runMatch}
              disabled={matching || !rawText.trim()}
            >
              {matching ? "比對中…" : "預覽 / 比對"}
            </button>
          )}
          {hasParsed && (
            <button
              className="btn primary"
              type="button"
              onClick={confirm}
              disabled={summary.selected === 0}
            >
              加入 {summary.selected} 筆到進貨單
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
