import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { ApiHttpError } from "@/api/client";
import {
  useCreateTransferOrder,
  useTransferOrder,
  useVoidTransferOrder,
} from "@/api/hooks";
import {
  searchInStockSerials,
  searchProducts,
  searchWarehouses,
} from "@/api/search";
import type { Product, ProductSerial, Warehouse } from "@/api/types";
import { Banner } from "@/components/Banner";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { Field } from "@/components/Field";
import { Toolbar } from "@/components/Toolbar";

interface Line {
  key: string;
  line_no: number;
  product: number | "";
  productOption: ComboOption<Product> | null;
  qty: number;
  serialChoices: (ComboOption<ProductSerial> | null)[];
  note: string;
}

function newLine(line_no: number): Line {
  return {
    key: crypto.randomUUID(),
    line_no,
    product: "",
    productOption: null,
    qty: 1,
    serialChoices: [],
    note: "",
  };
}

interface SerialAsideProps {
  line: Line | null;
  fromWarehouseId: number | "";
  readonly: boolean;
  onPickSerial: (
    idx: number,
    option: ComboOption<ProductSerial> | null,
  ) => void;
}

function SerialAside({
  line,
  fromWarehouseId,
  readonly,
  onPickSerial,
}: SerialAsideProps) {
  const product = line?.productOption?.payload;
  const needs = !!product?.requires_serial && !product.is_virtual;

  return (
    <aside className="serial-aside">
      <div className="serial-aside-header">
        <span className="serial-aside-title">出貨序號</span>
        {line && (
          <span className="serial-aside-sub">
            {product?.name ?? "(未選商品)"}
          </span>
        )}
      </div>
      <div className="serial-aside-body">
        {!line && (
          <div className="serial-aside-hint">點選左側明細列以挑序號</div>
        )}
        {line && !product && (
          <div className="serial-aside-hint">此列尚未選擇商品</div>
        )}
        {line && product && !needs && (
          <div className="serial-aside-hint">
            此商品不追蹤序號(配件按數量出庫)
          </div>
        )}
        {line && needs && !fromWarehouseId && (
          <div className="serial-aside-hint">請先選來源倉</div>
        )}
        {line && needs && fromWarehouseId && (
          <table className="serial-slot-table">
            <thead>
              <tr>
                <th style={{ width: 50 }}>序</th>
                <th>序號</th>
              </tr>
            </thead>
            <tbody>
              {Array.from({ length: line.qty }).map((_, i) => {
                const opt = line.serialChoices[i] ?? null;
                return (
                  <tr key={i}>
                    <td className="serial-slot-no">
                      {(i + 1).toString().padStart(4, "0")}
                    </td>
                    <td>
                      <ComboBox<ProductSerial>
                        value={opt?.id ?? ""}
                        selectedOption={opt}
                        onChange={(_id, picked) =>
                          onPickSerial(i, picked ?? null)
                        }
                        fetchOptions={(q) =>
                          searchInStockSerials(q, {
                            product: line.product as number,
                            warehouse: fromWarehouseId as number,
                          })
                        }
                        disabled={readonly}
                        placeholder="搜尋在庫序號"
                        emptyHint="查無在庫序號"
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </aside>
  );
}

export function TransferEntryPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const isNew = id === "new";
  const toId = isNew ? null : Number(id);

  const existing = useTransferOrder(toId);
  const createMutation = useCreateTransferOrder();
  const voidMutation = useVoidTransferOrder();

  const [fromWarehouse, setFromWarehouse] = useState<number | "">("");
  const [fromWarehouseOption, setFromWarehouseOption] =
    useState<ComboOption<Warehouse> | null>(null);
  const [toWarehouse, setToWarehouse] = useState<number | "">("");
  const [toWarehouseOption, setToWarehouseOption] =
    useState<ComboOption<Warehouse> | null>(null);
  const [docDate, setDocDate] = useState(
    () => new Date().toISOString().slice(0, 10),
  );
  const [note, setNote] = useState("");
  const [lines, setLines] = useState<Line[]>([newLine(1)]);
  const [selectedLineKey, setSelectedLineKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const initialized = useRef(false);

  const readonly = !isNew;

  useEffect(() => {
    if (existing.data && !isNew && !initialized.current) {
      initialized.current = true;
      const d = existing.data;
      setFromWarehouse(d.from_warehouse);
      setFromWarehouseOption({
        id: d.from_warehouse,
        label: d.from_warehouse_name,
        secondary: d.from_warehouse_code,
      });
      setToWarehouse(d.to_warehouse);
      setToWarehouseOption({
        id: d.to_warehouse,
        label: d.to_warehouse_name,
        secondary: d.to_warehouse_code,
      });
      setDocDate(d.doc_date);
      setNote(d.note);
      setLines(
        d.items.map((it) => ({
          key: String(it.id),
          line_no: it.line_no,
          product: it.product,
          productOption: {
            id: it.product,
            label: it.product_name,
            secondary: it.product_sku,
            payload: {
              id: it.product,
              sku: it.product_sku,
              name: it.product_name,
              spec: "",
              barcode: "",
              category: 0,
              category_code: "",
              category_name: "",
              weighted_avg_cost: "0",
              list_price: "0",
              last_purchase_price: null,
              requires_serial: it.product_requires_serial,
              allows_telecom_line: false,
              allows_commission: false,
              is_virtual: false,
              is_secondhand: false,
              counts_cash: true,
              counts_margin: true,
              is_active: true,
              stock_qty: 0,
              created_at: "",
              updated_at: "",
            },
          },
          qty: it.qty,
          serialChoices: (it.serials ?? []).map((s) => ({
            id: s.serial,
            label: s.serial_no,
            secondary: it.product_name,
          })),
          note: it.note,
        })),
      );
    }
  }, [existing.data, isNew]);

  function updateLine(key: string, patch: Partial<Line>) {
    setLines((ls) => ls.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  }
  function removeLine(key: string) {
    setLines((ls) => {
      const next = ls.filter((l) => l.key !== key);
      if (selectedLineKey === key) {
        setSelectedLineKey(next[0]?.key ?? null);
      }
      return next.length > 0 ? next : [newLine(1)];
    });
  }
  function addLine() {
    const fresh = newLine(lines.length + 1);
    setLines((ls) => [...ls, fresh]);
    setSelectedLineKey(fresh.key);
  }
  function updateSerialChoice(
    lineKey: string,
    idx: number,
    option: ComboOption<ProductSerial> | null,
  ) {
    setLines((ls) =>
      ls.map((l) => {
        if (l.key !== lineKey) return l;
        const next = [...l.serialChoices];
        while (next.length <= idx) next.push(null);
        next[idx] = option;
        return { ...l, serialChoices: next };
      }),
    );
  }

  function validate(): string | null {
    if (!fromWarehouse) return "請選來源倉";
    if (!toWarehouse) return "請選目的倉";
    if (fromWarehouse === toWarehouse) return "來源倉與目的倉不可相同";
    if (lines.length === 0) return "至少一筆明細";
    const seen = new Set<number>();
    for (const l of lines) {
      if (!l.product) return `第 ${l.line_no} 行未選商品`;
      if (l.qty <= 0) return `第 ${l.line_no} 行數量需 > 0`;
      const product = l.productOption?.payload;
      if (product?.requires_serial) {
        const picked = l.serialChoices.filter(Boolean) as ComboOption<ProductSerial>[];
        if (picked.length !== l.qty) {
          return `第 ${l.line_no} 行序號(${picked.length})不符數量(${l.qty})`;
        }
        for (const p of picked) {
          if (seen.has(p.id)) return `序號重複:${p.label}`;
          seen.add(p.id);
        }
      }
    }
    return null;
  }

  async function doSave() {
    setError(null);
    const err = validate();
    if (err) {
      setError(err);
      return;
    }
    try {
      const result = await createMutation.mutateAsync({
        from_warehouse: fromWarehouse as number,
        to_warehouse: toWarehouse as number,
        doc_date: docDate,
        note,
        items: lines.map((l, idx) => ({
          line_no: idx + 1,
          product: l.product as number,
          qty: Number(l.qty),
          note: l.note,
          serial_ids: l.serialChoices
            .filter(Boolean)
            .map((s) => s!.id),
        })),
      } as Parameters<typeof createMutation.mutateAsync>[0]);
      navigate(`/transfers/${result.id}`);
    } catch (e) {
      if (e instanceof ApiHttpError) {
        const body = e.body;
        if (typeof body === "object" && body && "detail" in body) {
          setError(String((body as { detail: unknown }).detail));
        } else {
          setError(`儲存失敗 (${e.status}): ${JSON.stringify(body)}`);
        }
      } else {
        setError(String(e));
      }
    }
  }

  async function handleVoid() {
    if (!existing.data) return;
    if (
      !confirm(
        `確定要作廢調撥單 ${existing.data.no}?系統會把已調出的序號 / 庫存退回來源倉。`,
      )
    )
      return;
    setError(null);
    try {
      await voidMutation.mutateAsync(existing.data.id);
    } catch (e) {
      if (e instanceof ApiHttpError) {
        const body = e.body;
        if (typeof body === "object" && body && "detail" in body) {
          setError(String((body as { detail: unknown }).detail));
        } else {
          setError(`作廢失敗 (${e.status}): ${JSON.stringify(body)}`);
        }
      } else {
        setError(String(e));
      }
    }
  }

  if (!isNew && existing.isLoading) {
    return <div className="md-empty">載入中…</div>;
  }

  const isVoid = existing.data?.is_void ?? false;
  const title = isNew
    ? "新增調撥單"
    : `${existing.data?.no} ${isVoid ? "(已作廢)" : "(檢視)"}`;

  return (
    <div className="page entry-layout">
      <Toolbar
        title={title}
        actions={
          <>
            <button className="btn" onClick={() => navigate("/transfers")}>
              ← 回列表
            </button>
            {isNew && (
              <button
                className="btn primary"
                onClick={doSave}
                disabled={createMutation.isPending}
              >
                {createMutation.isPending ? "儲存中…" : "儲存"}
              </button>
            )}
            {!isNew && !isVoid && (
              <button
                className="btn danger"
                onClick={handleVoid}
                disabled={voidMutation.isPending}
              >
                {voidMutation.isPending ? "作廢中…" : "作廢整單"}
              </button>
            )}
          </>
        }
      />

      <div className="entry-body-split">
        <div className="entry-body">
          {error && <Banner kind="error" message={error} />}

          <div className="entry-header" style={{ marginBottom: 12 }}>
            <div className="field-row-3">
              <Field label="來源倉" required>
                <ComboBox<Warehouse>
                  value={fromWarehouse}
                  selectedOption={fromWarehouseOption}
                  onChange={(id, opt) => {
                    setFromWarehouse(id);
                    setFromWarehouseOption(opt ?? null);
                  }}
                  fetchOptions={searchWarehouses}
                  disabled={readonly}
                  placeholder="搜尋來源倉"
                />
              </Field>
              <Field label="目的倉" required>
                <ComboBox<Warehouse>
                  value={toWarehouse}
                  selectedOption={toWarehouseOption}
                  onChange={(id, opt) => {
                    setToWarehouse(id);
                    setToWarehouseOption(opt ?? null);
                  }}
                  fetchOptions={searchWarehouses}
                  disabled={readonly}
                  placeholder="搜尋目的倉"
                />
              </Field>
              <Field label="單據日期" required>
                <input
                  type="date"
                  value={docDate}
                  onChange={(e) => setDocDate(e.target.value)}
                  disabled={readonly}
                />
              </Field>
            </div>
            <div className="field-row-3">
              <Field label="備註">
                <input
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  disabled={readonly}
                  maxLength={200}
                />
              </Field>
            </div>
          </div>

          <table className="line-table">
            <thead>
              <tr>
                <th style={{ width: 40 }}>#</th>
                <th style={{ width: 280 }}>商品</th>
                <th style={{ width: 80 }} className="num">
                  數量
                </th>
                <th style={{ width: 80 }} className="num">
                  序號
                </th>
                <th>備註</th>
                <th style={{ width: 50 }}></th>
              </tr>
            </thead>
            <tbody>
              {lines.map((l, idx) => {
                const product = l.productOption?.payload;
                const needsSerial = !!product?.requires_serial;
                const filled = l.serialChoices.filter(Boolean).length;
                const isActive = l.key === selectedLineKey;
                return (
                  <tr
                    key={l.key}
                    className={isActive ? "line-row-active" : undefined}
                    onClick={() => setSelectedLineKey(l.key)}
                  >
                    <td>{idx + 1}</td>
                    <td>
                      <ComboBox<Product>
                        value={l.product}
                        selectedOption={l.productOption}
                        onChange={(pid, opt) => {
                          updateLine(l.key, {
                            product: pid,
                            productOption: opt ?? null,
                            serialChoices: [],
                          });
                        }}
                        fetchOptions={(q) =>
                          searchProducts(q, { activeOnly: true })
                        }
                        disabled={readonly}
                        placeholder="搜尋商品"
                      />
                    </td>
                    <td>
                      <input
                        type="number"
                        className="num-input"
                        min={1}
                        value={l.qty}
                        onChange={(e) =>
                          updateLine(l.key, { qty: Number(e.target.value) })
                        }
                        disabled={readonly}
                      />
                    </td>
                    <td className="num">
                      {needsSerial ? (
                        <span
                          className={
                            filled === l.qty
                              ? "serial-badge ok"
                              : "serial-badge"
                          }
                          title="點此列右側面板挑選序號"
                        >
                          {filled}/{l.qty}
                        </span>
                      ) : (
                        <span style={{ color: "var(--text-dim)" }}>—</span>
                      )}
                    </td>
                    <td>
                      <input
                        value={l.note}
                        onChange={(e) =>
                          updateLine(l.key, { note: e.target.value })
                        }
                        disabled={readonly}
                      />
                    </td>
                    <td className="row-actions">
                      {!readonly && (
                        <button onClick={() => removeLine(l.key)} type="button">
                          刪
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {!readonly && (
            <button
              className="btn"
              onClick={addLine}
              type="button"
              style={{ marginTop: 8 }}
            >
              + 新增明細
            </button>
          )}
        </div>
        <SerialAside
          line={lines.find((l) => l.key === selectedLineKey) ?? null}
          fromWarehouseId={fromWarehouse}
          readonly={readonly}
          onPickSerial={(idx, opt) =>
            selectedLineKey &&
            updateSerialChoice(selectedLineKey, idx, opt)
          }
        />
      </div>
    </div>
  );
}
