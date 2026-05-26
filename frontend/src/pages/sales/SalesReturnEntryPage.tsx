import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { ApiHttpError } from "@/api/client";
import {
  usePaymentMethods,
  useCreateSalesReturn,
  useReturnableForSO,
  useSalesOrders,
  useSalesReturn,
  useVoidSalesReturn,
} from "@/api/hooks";
import type { ReturnableLine } from "@/api/types";
import { Banner } from "@/components/Banner";
import { Toolbar } from "@/components/Toolbar";

/** 一行的編輯狀態 */
interface RowState {
  selected: boolean;
  qty: number;
  // 序號商品:選擇要退的序號 id
  selectedSerialIds: number[];
}

const TAX_RATE = 0.05;

function calcLineTotal(unitPrice: string, qty: number): number {
  return Math.round(Number(unitPrice) * qty);
}

function calcSubtotal(
  rows: Record<number, RowState>,
  items: ReturnableLine[],
): number {
  let total = 0;
  for (const it of items) {
    const row = rows[it.id];
    if (!row?.selected || row.qty <= 0) continue;
    total += calcLineTotal(it.unit_price, row.qty);
  }
  return total;
}

export function SalesReturnEntryPage() {
  const navigate = useNavigate();
  const params = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const focusMode = searchParams.get("focus") === "1";
  const isNew = !params.id || params.id === "new";
  const srId = isNew ? null : Number(params.id);

  const existing = useSalesReturn(srId);
  const create = useCreateSalesReturn();
  const voidMutation = useVoidSalesReturn();
  const paymentMethodsQ = usePaymentMethods({ activeOnly: true });

  // 新單模式:先選原銷貨單
  const todaySOs = useSalesOrders({ from: "", to: "" });
  const [originalSOId, setOriginalSOId] = useState<number | null>(null);
  useEffect(() => {
    // 檢視模式:從 existing 帶 original_so 出來
    if (!isNew && existing.data) {
      setOriginalSOId(existing.data.original_so);
    }
  }, [isNew, existing.data]);

  const returnable = useReturnableForSO(originalSOId);

  // 退貨明細的編輯狀態:key=item.id (即 original_item id)
  const [rows, setRows] = useState<Record<number, RowState>>({});
  const [paymentMethod, setPaymentMethod] = useState<string>("");
  const [voidInvoice, setVoidInvoice] = useState(true);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  // 切到新單 + 載到 returnable → 重置 rows / paymentMethod
  useEffect(() => {
    if (!isNew || !returnable.data) return;
    const init: Record<number, RowState> = {};
    for (const it of returnable.data.items) {
      init[it.id] = {
        selected: false,
        qty: it.remaining,
        selectedSerialIds: [],
      };
    }
    setRows(init);
    setPaymentMethod(returnable.data.payment_methods[0] ?? "");
    setVoidInvoice(!returnable.data.invoice_voided);
  }, [isNew, returnable.data]);

  const subtotal = useMemo(() => {
    if (!returnable.data) return 0;
    return calcSubtotal(rows, returnable.data.items);
  }, [rows, returnable.data]);

  const totalWithTax = useMemo(() => {
    if (!returnable.data) return 0;
    if (returnable.data.tax_method === "taxable_included") return subtotal;
    if (returnable.data.tax_method === "taxable_excluded")
      return Math.round(subtotal * (1 + TAX_RATE));
    return subtotal;
  }, [subtotal, returnable.data]);

  function toggleRow(itemId: number, checked: boolean) {
    setRows((s) => ({
      ...s,
      [itemId]: { ...s[itemId], selected: checked },
    }));
  }

  function setRowQty(itemId: number, qty: number) {
    setRows((s) => ({
      ...s,
      [itemId]: { ...s[itemId], qty: Math.max(1, qty) },
    }));
  }

  function toggleSerial(itemId: number, serialId: number, checked: boolean) {
    setRows((s) => {
      const cur = s[itemId];
      const next = checked
        ? [...cur.selectedSerialIds, serialId]
        : cur.selectedSerialIds.filter((id) => id !== serialId);
      return {
        ...s,
        [itemId]: { ...cur, selectedSerialIds: next, qty: next.length || cur.qty },
      };
    });
  }

  async function handleSubmit() {
    setError(null);
    if (!originalSOId) {
      setError("請先選原銷貨單");
      return;
    }
    if (!returnable.data) return;
    if (!paymentMethod) {
      setError("請選退款方式");
      return;
    }

    const itemsPayload: {
      original_item: number;
      qty: number;
      serial_ids?: number[];
    }[] = [];

    for (const it of returnable.data.items) {
      const row = rows[it.id];
      if (!row?.selected) continue;
      if (it.product_requires_serial && !it.product_is_virtual) {
        if (row.selectedSerialIds.length === 0) {
          setError(`${it.product_name}:序號商品需勾選要退的序號`);
          return;
        }
        itemsPayload.push({
          original_item: it.id,
          qty: row.selectedSerialIds.length,
          serial_ids: row.selectedSerialIds,
        });
      } else {
        if (row.qty <= 0 || row.qty > it.remaining) {
          setError(
            `${it.product_name}:退貨數量 ${row.qty} 不在合法範圍(1 ~ ${it.remaining})`,
          );
          return;
        }
        itemsPayload.push({
          original_item: it.id,
          qty: row.qty,
        });
      }
    }

    if (itemsPayload.length === 0) {
      setError("請至少勾選一行要退的品項");
      return;
    }

    try {
      const sr = await create.mutateAsync({
        original_so: originalSOId,
        payment_method: paymentMethod,
        void_original_invoice: voidInvoice,
        note,
        items: itemsPayload,
      });
      navigate(`/sales/returns/${sr.id}`);
    } catch (e) {
      if (e instanceof ApiHttpError) {
        const body = e.body;
        if (typeof body === "object" && body && "detail" in body) {
          setError(String((body as { detail: unknown }).detail));
        } else {
          setError(`儲存失敗:${JSON.stringify(body)}`);
        }
      } else {
        setError(String(e));
      }
    }
  }

  async function handleVoid() {
    if (!existing.data) return;
    if (!confirm(`確定要作廢銷退單 ${existing.data.no}?庫存會回扣到 sold 狀態。`)) return;
    try {
      await voidMutation.mutateAsync(existing.data.id);
    } catch (e) {
      if (e instanceof ApiHttpError) {
        setError(String(e.body));
      }
    }
  }

  // ---- 渲染 ----

  if (!isNew && existing.isLoading) {
    return <div className="md-empty">載入中…</div>;
  }
  if (!isNew && existing.isError) {
    return <div className="md-empty">查無此銷退單</div>;
  }

  const sr = existing.data;
  const readonly = !isNew;

  return (
    <div className="page">
      <Toolbar
        title={
          isNew
            ? "新增銷退單"
            : `${sr?.no} (${sr?.is_void ? "已作廢" : "檢視"})`
        }
        actions={
          focusMode ? null : (
          <>
            <button className="btn" onClick={() => navigate("/sales?tab=returns")}>
              ← 回列表
            </button>
            {readonly && sr && !sr.is_void && (
              <button
                className="btn danger"
                onClick={handleVoid}
                disabled={voidMutation.isPending}
              >
                {voidMutation.isPending ? "作廢中…" : "作廢整單"}
              </button>
            )}
            {isNew && (
              <button
                className="btn primary"
                onClick={handleSubmit}
                disabled={create.isPending}
              >
                {create.isPending ? "送出中…" : "送出銷退"}
              </button>
            )}
          </>
          )
        }
      />

      {error && <Banner kind="error" message={error} />}

      {/* 選原銷貨單(只在新單時可改) */}
      <div style={{ padding: 16, display: "flex", gap: 12, flexWrap: "wrap" }}>
        <div>
          <label style={{ display: "block", fontSize: 12, color: "var(--text-dim)" }}>
            原銷貨單 *
          </label>
          {isNew ? (
            <select
              value={originalSOId ?? ""}
              onChange={(e) =>
                setOriginalSOId(
                  e.target.value ? Number(e.target.value) : null,
                )
              }
              style={{ minWidth: 280 }}
            >
              <option value="">— 選擇原銷貨單 —</option>
              {(todaySOs.data ?? [])
                .filter((so) => !so.is_void)
                .map((so) => (
                  <option key={so.id} value={so.id}>
                    {so.no} · {so.doc_date} · {so.customer_name || "(散客)"}
                  </option>
                ))}
            </select>
          ) : (
            <div>
              {sr?.original_so_no} ({sr?.original_so_doc_date})
            </div>
          )}
        </div>

        {returnable.data && (
          <>
            <div>
              <label style={{ display: "block", fontSize: 12, color: "var(--text-dim)" }}>
                客戶
              </label>
              <div>{returnable.data.customer_name || "(散客)"}</div>
            </div>
            <div>
              <label style={{ display: "block", fontSize: 12, color: "var(--text-dim)" }}>
                退回倉
              </label>
              <div>{returnable.data.warehouse_name}</div>
            </div>
            <div>
              <label style={{ display: "block", fontSize: 12, color: "var(--text-dim)" }}>
                退款方式 *
              </label>
              {isNew ? (
                <select
                  value={paymentMethod}
                  onChange={(e) => setPaymentMethod(e.target.value)}
                >
                  {returnable.data.payment_methods.map((m) => {
                    const pm = (paymentMethodsQ.data ?? []).find(
                      (x) => x.code === m,
                    );
                    return (
                      <option key={m} value={m}>
                        {pm?.name ?? m}
                      </option>
                    );
                  })}
                </select>
              ) : (
                <div>{sr?.payment_method}</div>
              )}
            </div>
            <div>
              <label style={{ display: "block", fontSize: 12, color: "var(--text-dim)" }}>
                作廢原發票
              </label>
              {isNew ? (
                <label style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
                  <input
                    type="checkbox"
                    checked={voidInvoice}
                    onChange={(e) => setVoidInvoice(e.target.checked)}
                    disabled={returnable.data.invoice_voided}
                  />
                  {returnable.data.invoice_voided
                    ? "(原發票已標作廢)"
                    : "退貨同時作廢"}
                </label>
              ) : (
                <div>{sr?.void_original_invoice ? "是" : "否"}</div>
              )}
            </div>
            <div style={{ flex: 1 }}>
              <label style={{ display: "block", fontSize: 12, color: "var(--text-dim)" }}>
                備註
              </label>
              {isNew ? (
                <input
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  style={{ width: "100%" }}
                />
              ) : (
                <div>{sr?.note || "—"}</div>
              )}
            </div>
          </>
        )}
      </div>

      {/* 退貨明細 */}
      {returnable.data && (
        <div style={{ padding: "0 16px" }}>
          <h3 className="pc-detail-title">退貨明細</h3>
          <table className="md-table-inner">
            <thead>
              <tr>
                {isNew && <th style={{ width: 40 }}>勾</th>}
                <th>商品</th>
                <th className="num" style={{ width: 80 }}>原數量</th>
                <th className="num" style={{ width: 80 }}>已退</th>
                <th className="num" style={{ width: 80 }}>可退</th>
                <th className="num" style={{ width: 80 }}>退量</th>
                <th className="num" style={{ width: 100 }}>單價</th>
                <th className="num" style={{ width: 110 }}>小計</th>
                <th>序號 (可勾選要退)</th>
              </tr>
            </thead>
            <tbody>
              {(isNew
                ? returnable.data.items
                : (sr?.items ?? []).map((it) => {
                    const origItem = returnable.data!.items.find(
                      (x) => x.id === it.original_item,
                    );
                    return origItem ?? null;
                  }).filter(Boolean) as ReturnableLine[]
              ).map((it) => {
                const row = rows[it.id] ?? {
                  selected: false,
                  qty: it.remaining,
                  selectedSerialIds: [],
                };
                const isSerial =
                  it.product_requires_serial && !it.product_is_virtual;
                // 檢視模式:由 sr.items 找對應的退量、序號
                const srItem = !isNew
                  ? sr?.items.find((x) => x.original_item === it.id)
                  : null;
                const displayQty = isNew
                  ? isSerial
                    ? row.selectedSerialIds.length
                    : row.qty
                  : (srItem?.qty ?? 0);
                const displayLineTotal = isNew
                  ? calcLineTotal(it.unit_price, displayQty)
                  : Math.round(Number(srItem?.amount ?? "0"));
                return (
                  <tr key={it.id}>
                    {isNew && (
                      <td>
                        <input
                          type="checkbox"
                          checked={row.selected}
                          onChange={(e) => toggleRow(it.id, e.target.checked)}
                          disabled={it.remaining <= 0}
                        />
                      </td>
                    )}
                    <td>
                      <div>{it.product_name}</div>
                      <div style={{ fontSize: 11, color: "var(--text-dim)" }}>
                        {it.product_sku}
                      </div>
                    </td>
                    <td className="num">{it.qty}</td>
                    <td className="num">{it.already_returned}</td>
                    <td className="num">{it.remaining}</td>
                    <td className="num">
                      {isNew && !isSerial && row.selected ? (
                        <input
                          type="number"
                          min={1}
                          max={it.remaining}
                          value={row.qty}
                          onChange={(e) =>
                            setRowQty(it.id, Number(e.target.value))
                          }
                          className="num-input"
                          style={{ width: 60 }}
                        />
                      ) : (
                        displayQty
                      )}
                    </td>
                    <td className="num">
                      {Number(it.unit_price).toLocaleString()}
                    </td>
                    <td className="num">{displayLineTotal.toLocaleString()}</td>
                    <td style={{ fontSize: 12 }}>
                      {isSerial ? (
                        isNew ? (
                          <div
                            style={{
                              display: "flex",
                              flexWrap: "wrap",
                              gap: 6,
                            }}
                          >
                            {it.available_serials.map((s) => (
                              <label
                                key={s.id}
                                style={{
                                  display: "inline-flex",
                                  gap: 2,
                                  alignItems: "center",
                                }}
                              >
                                <input
                                  type="checkbox"
                                  checked={row.selectedSerialIds.includes(s.id)}
                                  onChange={(e) =>
                                    toggleSerial(
                                      it.id,
                                      s.id,
                                      e.target.checked,
                                    )
                                  }
                                  disabled={!row.selected}
                                />
                                {s.serial_no}
                              </label>
                            ))}
                            {it.available_serials.length === 0 && (
                              <span style={{ color: "var(--text-dim)" }}>
                                此行無可退序號(全部已退)
                              </span>
                            )}
                          </div>
                        ) : (
                          (srItem?.serials ?? [])
                            .map((s) => s.serial_no)
                            .join(", ")
                        )
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {/* 退款摘要 */}
          {isNew && (
            <div
              style={{
                marginTop: 12,
                display: "flex",
                gap: 24,
                justifyContent: "flex-end",
              }}
            >
              <span>
                預估退款 <strong>${totalWithTax.toLocaleString()}</strong>
              </span>
            </div>
          )}
          {!isNew && sr && (
            <div
              style={{
                marginTop: 12,
                display: "flex",
                gap: 24,
                justifyContent: "flex-end",
              }}
            >
              <span>
                未稅 {Math.round(Number(sr.subtotal)).toLocaleString()}
              </span>
              <span>稅 {Math.round(Number(sr.tax_amount)).toLocaleString()}</span>
              <span>
                退款額 <strong>${Math.round(Number(sr.total)).toLocaleString()}</strong>
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
