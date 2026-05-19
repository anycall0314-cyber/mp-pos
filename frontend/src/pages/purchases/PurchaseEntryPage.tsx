import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { ApiHttpError } from "@/api/client";
import {
  useCreatePurchaseOrder,
  useInvoiceTypes,
  usePurchaseOrder,
  useVoidPurchaseOrder,
} from "@/api/hooks";
import {
  searchProducts,
  searchPurchaseOrderCategories,
  searchSuppliers,
  searchWarehouses,
} from "@/api/search";
import type { InvoiceForm, Product, TaxMethod } from "@/api/types";
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
  billed_qty: number;
  unit_price: string;
  serial_numbers: string[];
}

function newLine(line_no: number): Line {
  return {
    key: crypto.randomUUID(),
    line_no,
    product: "",
    productOption: null,
    qty: 1,
    billed_qty: 1,
    unit_price: "0",
    serial_numbers: [],
  };
}

function filledSerials(line: Line): string[] {
  return line.serial_numbers.map((s) => (s ?? "").trim()).filter(Boolean);
}

function calcAmount(line: Line) {
  return Number(line.billed_qty) * Number(line.unit_price);
}

interface SerialAsideProps {
  line: Line | null;
  readonly: boolean;
  containerRef: React.RefObject<HTMLDivElement>;
  onUpdateSerial: (idx: number, value: string) => void;
  onPasteSerials: (startIdx: number, list: string[]) => void;
}

function SerialAside({
  line,
  readonly,
  containerRef,
  onUpdateSerial,
  onPasteSerials,
}: SerialAsideProps) {
  const product = line?.productOption?.payload;
  const needs = !!product?.requires_serial;

  return (
    <aside className="serial-aside" ref={containerRef}>
      <div className="serial-aside-header">
        <span className="serial-aside-title">序號維護</span>
        {line && (
          <span className="serial-aside-sub">
            {product?.name ?? "(未選商品)"}
          </span>
        )}
      </div>
      <div className="serial-aside-body">
        {!line && (
          <div className="serial-aside-hint">點選左側明細列以維護序號</div>
        )}
        {line && !product && (
          <div className="serial-aside-hint">此列尚未選擇商品</div>
        )}
        {line && product && !needs && (
          <div className="serial-aside-hint">此商品不追蹤序號</div>
        )}
        {line && needs && (
          <table className="serial-slot-table">
            <thead>
              <tr>
                <th style={{ width: 50 }}>序</th>
                <th>IMEI / 序號</th>
              </tr>
            </thead>
            <tbody>
              {Array.from({ length: line.qty }).map((_, i) => {
                const value = line.serial_numbers[i] ?? "";
                return (
                  <tr key={i}>
                    <td className="serial-slot-no">
                      {(i + 1).toString().padStart(4, "0")}
                    </td>
                    <td>
                      <input
                        data-serial-slot={`${line.key}-${i}`}
                        value={value}
                        disabled={readonly}
                        onChange={(e) => onUpdateSerial(i, e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.preventDefault();
                            const next = containerRef.current?.querySelector(
                              `[data-serial-slot="${line.key}-${i + 1}"]`,
                            );
                            if (next)
                              (next as HTMLInputElement).focus();
                          }
                        }}
                        onPaste={(e) => {
                          const text = e.clipboardData.getData("text");
                          const list = text
                            .split(/[\s,;]+/)
                            .map((s) => s.trim())
                            .filter(Boolean);
                          if (list.length > 1) {
                            e.preventDefault();
                            onPasteSerials(i, list);
                          }
                        }}
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

const TAX_METHODS: { value: TaxMethod; label: string }[] = [
  { value: "taxable_included", label: "應稅內含" },
  { value: "taxable_excluded", label: "應稅外加" },
  { value: "tax_free", label: "免稅" },
  { value: "zero_tax", label: "零稅" },
];

const DRAFT_KEY = "purchase-entry-draft";

interface PurchaseDraft {
  supplier: number | "";
  supplierOption: ComboOption<unknown> | null;
  warehouse: number | "";
  warehouseOption: ComboOption<unknown> | null;
  category: number | "";
  categoryOption: ComboOption<unknown> | null;
  docDate: string;
  taxMethod: TaxMethod;
  invoiceForm: InvoiceForm;
  invoiceNo: string;
  invoiceDate: string;
  note: string;
  lines: Line[];
}

function loadDraft(): PurchaseDraft | null {
  try {
    const raw = sessionStorage.getItem(DRAFT_KEY);
    return raw ? (JSON.parse(raw) as PurchaseDraft) : null;
  } catch {
    return null;
  }
}


export function PurchaseEntryPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const isNew = id === "new";
  const poId = isNew ? null : Number(id);

  // 草稿:只在新增模式才會啟用;切到別頁回來不會丟資料,save 成功後清空
  const draft = useRef<PurchaseDraft | null>(isNew ? loadDraft() : null).current;

  const existing = usePurchaseOrder(poId);
  const createMutation = useCreatePurchaseOrder();
  const voidMutation = useVoidPurchaseOrder();
  const invoiceTypesQuery = useInvoiceTypes({ activeOnly: true });
  const invoiceTypes = invoiceTypesQuery.data ?? [];
  const defaultInvoiceCode =
    invoiceTypes.find((t) => t.is_default)?.code ?? invoiceTypes[0]?.code ?? "";

  const [supplier, setSupplier] = useState<number | "">(draft?.supplier ?? "");
  const [supplierOption, setSupplierOption] =
    useState<ComboOption<unknown> | null>(draft?.supplierOption ?? null);
  const [warehouse, setWarehouse] = useState<number | "">(draft?.warehouse ?? "");
  const [warehouseOption, setWarehouseOption] =
    useState<ComboOption<unknown> | null>(draft?.warehouseOption ?? null);
  const [category, setCategory] = useState<number | "">(draft?.category ?? "");
  const [categoryOption, setCategoryOption] =
    useState<ComboOption<unknown> | null>(draft?.categoryOption ?? null);
  const [docDate, setDocDate] = useState(
    () => draft?.docDate ?? new Date().toISOString().slice(0, 10),
  );
  const [taxMethod, setTaxMethod] = useState<TaxMethod>(
    draft?.taxMethod ?? "taxable_included",
  );
  const [invoiceForm, setInvoiceForm] = useState<InvoiceForm>(
    draft?.invoiceForm ?? "",
  );
  const [invoiceNo, setInvoiceNo] = useState(draft?.invoiceNo ?? "");
  const [invoiceDate, setInvoiceDate] = useState(draft?.invoiceDate ?? "");
  const [note, setNote] = useState(draft?.note ?? "");
  const [lines, setLines] = useState<Line[]>(() => {
    if (draft?.lines && draft.lines.length > 0) return draft.lines;
    return [newLine(1)];
  });
  const [selectedLineKey, setSelectedLineKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showConfirm, setShowConfirm] = useState(false);
  const serialPanelRef = useRef<HTMLDivElement>(null);

  // 檢視已建立的單據時整頁唯讀
  const readonly = !isNew;

  // 新單載入發票類型主檔後自動帶預設
  useEffect(() => {
    if (isNew && !invoiceForm && defaultInvoiceCode) {
      setInvoiceForm(defaultInvoiceCode);
      if (defaultInvoiceCode === "none") setTaxMethod("tax_free");
    }
  }, [isNew, invoiceForm, defaultInvoiceCode]);

  const noInvoice = invoiceForm === "" || invoiceForm === "none";

  // 新單時把所有表單欄位 debounce 寫進 sessionStorage,切到其他分頁回來不會掉
  useEffect(() => {
    if (!isNew) return;
    const snapshot: PurchaseDraft = {
      supplier,
      supplierOption,
      warehouse,
      warehouseOption,
      category,
      categoryOption,
      docDate,
      taxMethod,
      invoiceForm,
      invoiceNo,
      invoiceDate,
      note,
      lines,
    };
    const handle = setTimeout(() => {
      try {
        sessionStorage.setItem(DRAFT_KEY, JSON.stringify(snapshot));
      } catch {
        // quota / serialization 失敗就略過
      }
    }, 250);
    return () => clearTimeout(handle);
  }, [
    isNew,
    supplier,
    supplierOption,
    warehouse,
    warehouseOption,
    category,
    categoryOption,
    docDate,
    taxMethod,
    invoiceForm,
    invoiceNo,
    invoiceDate,
    note,
    lines,
  ]);

  function clearDraft() {
    sessionStorage.removeItem(DRAFT_KEY);
  }

  function discardDraft() {
    if (!confirm("確定清空目前已填寫的內容?")) return;
    clearDraft();
    setSupplier("");
    setSupplierOption(null);
    setWarehouse("");
    setWarehouseOption(null);
    setCategory("");
    setCategoryOption(null);
    setDocDate(new Date().toISOString().slice(0, 10));
    setTaxMethod("taxable_included");
    setInvoiceForm(defaultInvoiceCode);
    setInvoiceNo("");
    setInvoiceDate("");
    setNote("");
    setLines([newLine(1)]);
    setSelectedLineKey(null);
  }

  useEffect(() => {
    if (existing.data && !isNew) {
      const d = existing.data;
      setSupplier(d.supplier);
      setSupplierOption({
        id: d.supplier,
        label: d.supplier_name,
        secondary: d.supplier_code,
      });
      setWarehouse(d.warehouse);
      setWarehouseOption({
        id: d.warehouse,
        label: d.warehouse_name,
        secondary: d.warehouse_code,
      });
      setDocDate(d.doc_date);
      if (d.category) {
        setCategory(d.category);
        setCategoryOption({
          id: d.category,
          label: d.category_name ?? "",
          secondary: d.category_code ?? "",
        });
      }
      setTaxMethod(d.tax_method);
      setInvoiceForm(d.invoice_form);
      setInvoiceNo(d.invoice_no);
      setInvoiceDate(d.invoice_date ?? "");
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
          },
          qty: it.qty,
          billed_qty: it.billed_qty,
          unit_price: it.unit_price,
          serial_numbers: it.serial_numbers,
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
  function updateSerialAt(lineKey: string, idx: number, value: string) {
    setLines((ls) =>
      ls.map((l) => {
        if (l.key !== lineKey) return l;
        const next = [...l.serial_numbers];
        // 確保長度足夠
        while (next.length <= idx) next.push("");
        next[idx] = value;
        return { ...l, serial_numbers: next };
      }),
    );
  }
  function pasteSerialsAt(lineKey: string, startIdx: number, list: string[]) {
    setLines((ls) =>
      ls.map((l) => {
        if (l.key !== lineKey) return l;
        const next = [...l.serial_numbers];
        list.forEach((s, i) => {
          const pos = startIdx + i;
          if (pos < l.qty) {
            while (next.length <= pos) next.push("");
            next[pos] = s;
          }
        });
        return { ...l, serial_numbers: next };
      }),
    );
  }

  const grossSum = lines.reduce((s, l) => s + (calcAmount(l) || 0), 0);
  const [estSubtotal, estTax, estTotal] = (() => {
    if (taxMethod === "taxable_included") {
      const sub = grossSum / 1.05;
      return [sub, grossSum - sub, grossSum];
    }
    if (taxMethod === "taxable_excluded") {
      return [grossSum, grossSum * 0.05, grossSum * 1.05];
    }
    return [grossSum, 0, grossSum];
  })();

  function validate(): string | null {
    if (!supplier) return "請選供應商";
    if (!warehouse) return "請選入庫倉";
    if (lines.length === 0) return "至少一筆明細";
    const seen = new Set<string>();
    for (const l of lines) {
      if (!l.product) return `第 ${l.line_no} 行未選商品`;
      if (l.qty <= 0) return `第 ${l.line_no} 行數量需 > 0`;
      const serials = filledSerials(l);
      const product = l.productOption?.payload;
      if (product?.requires_serial) {
        if (serials.length !== l.qty) {
          return `第 ${l.line_no} 行序號(${serials.length})不符數量(${l.qty})`;
        }
        for (const s of serials) {
          if (seen.has(s)) return `序號重複:${s}`;
          seen.add(s);
        }
      }
    }
    return null;
  }

  // 點「儲存」先做欄位檢查 → 通過就跳確認 modal;確認 modal 才呼叫 API
  function openConfirm() {
    setError(null);
    const err = validate();
    if (err) {
      setError(err);
      return;
    }
    setShowConfirm(true);
  }

  async function doSave() {
    setError(null);
    try {
      await createMutation.mutateAsync({
        supplier: supplier as number,
        warehouse: warehouse as number,
        doc_date: docDate,
        category: category === "" ? null : (category as number),
        tax_method: taxMethod,
        invoice_form: invoiceForm,
        invoice_no: invoiceNo,
        invoice_date: invoiceDate || null,
        note,
        items: lines.map((l, idx) => ({
          line_no: idx + 1,
          product: l.product as number,
          qty: Number(l.qty),
          billed_qty: Number(l.billed_qty || l.qty),
          unit_price: l.unit_price,
          serial_numbers: filledSerials(l),
        })),
      } as Parameters<typeof createMutation.mutateAsync>[0]);
      clearDraft();
      setShowConfirm(false);
      navigate("/purchases");
    } catch (e) {
      setShowConfirm(false);
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
    if (!confirm(`確定要作廢進貨單 ${existing.data.no}?此操作會把序號標為作廢、回補加權平均成本。`)) {
      return;
    }
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
    ? "新增進貨單"
    : `${existing.data?.no} ${isVoid ? "(已作廢)" : "(檢視)"}`;

  return (
    <div className="page entry-layout">
      <Toolbar
        title={title}
        actions={
          <>
            <button className="btn" onClick={() => navigate("/purchases")}>
              ← 回列表
            </button>
            {isNew && (
              <button className="btn" type="button" onClick={discardDraft}>
                清空草稿
              </button>
            )}
            {isNew && (
              <button
                className="btn primary"
                onClick={openConfirm}
                disabled={createMutation.isPending}
              >
                {createMutation.isPending ? "儲存中…" : "儲存"}
              </button>
            )}
            {!isNew && existing.data && !isVoid && (
              <button
                className="btn"
                type="button"
                onClick={() =>
                  window.open(
                    `/purchases/${existing.data!.id}/print/labels`,
                    "_blank",
                  )
                }
              >
                列印標籤
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
            <Field label="供應商" required>
              <ComboBox
                value={supplier}
                selectedOption={supplierOption}
                onChange={(id, opt) => {
                  setSupplier(id);
                  setSupplierOption(opt ?? null);
                }}
                fetchOptions={searchSuppliers}
                disabled={readonly}
                placeholder="搜尋供應商(代碼/名稱/統編)"
              />
            </Field>
            <Field label="入庫倉" required>
              <ComboBox
                value={warehouse}
                selectedOption={warehouseOption}
                onChange={(id, opt) => {
                  setWarehouse(id);
                  setWarehouseOption(opt ?? null);
                }}
                fetchOptions={searchWarehouses}
                disabled={readonly}
                placeholder="搜尋倉庫"
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
            <Field label="進貨單別">
              <ComboBox
                value={category}
                selectedOption={categoryOption}
                onChange={(id, opt) => {
                  setCategory(id);
                  setCategoryOption(opt ?? null);
                }}
                fetchOptions={searchPurchaseOrderCategories}
                disabled={readonly}
                placeholder="搜尋單別(代碼/名稱)"
              />
            </Field>
            <Field label="課稅別">
              <select
                value={taxMethod}
                onChange={(e) => setTaxMethod(e.target.value as TaxMethod)}
                disabled={readonly}
              >
                {TAX_METHODS.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="發票類型">
              <select
                value={invoiceForm}
                onChange={(e) => {
                  const v = e.target.value;
                  setInvoiceForm(v);
                  // 免用統一發票 → 課稅別連動到免稅
                  if (v === "none") setTaxMethod("tax_free");
                }}
                disabled={readonly}
              >
                <option value="">— 未指定 —</option>
                {invoiceTypes.map((f) => (
                  <option key={f.code} value={f.code}>
                    {f.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <div className="field-row-3">
            <Field label="發票號碼">
              <input
                value={invoiceNo}
                onChange={(e) => setInvoiceNo(e.target.value.toUpperCase())}
                disabled={readonly || noInvoice}
                maxLength={20}
                placeholder="例:AB12345678"
              />
            </Field>
            <Field label="發票日期">
              <input
                type="date"
                value={invoiceDate}
                onChange={(e) => setInvoiceDate(e.target.value)}
                disabled={readonly || noInvoice}
              />
            </Field>
            <Field label="備註">
              <input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                disabled={readonly}
              />
            </Field>
          </div>
        </div>

        <table className="line-table">
          <thead>
            <tr>
              <th style={{ width: 40 }}>#</th>
              <th style={{ width: 280 }}>商品</th>
              <th style={{ width: 70 }} className="num">
                進貨數量
              </th>
              <th style={{ width: 70 }} className="num">
                計價數量
              </th>
              <th style={{ width: 100 }} className="num">
                單價
              </th>
              <th style={{ width: 110 }} className="num">
                金額
              </th>
              <th style={{ width: 90 }} className="num">
                序號
              </th>
              <th style={{ width: 110 }} className="num">
                未稅單價
              </th>
              <th style={{ width: 50 }}></th>
            </tr>
          </thead>
          <tbody>
            {lines.map((l, idx) => {
              const item = existing.data?.items.find(
                (it) => String(it.id) === l.key,
              );
              const product = l.productOption?.payload ?? undefined;
              const filled = filledSerials(l).length;
              const needsSerial = !!product?.requires_serial;
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
                        const p = opt?.payload;
                        const patch: Partial<Line> = {
                          product: pid,
                          productOption: opt ?? null,
                        };
                        // 選到商品有上一次進價就帶入;沒有的話留原值不動
                        const lastPrice = p?.last_purchase_price;
                        if (lastPrice && Number(lastPrice) > 0) {
                          patch.unit_price = String(lastPrice);
                        }
                        updateLine(l.key, patch);
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
                      onChange={(e) => {
                        const q = Number(e.target.value);
                        const patch: Partial<Line> = { qty: q };
                        // 若使用者沒改過計價數量(=舊 qty),跟著同步
                        if (l.billed_qty === l.qty || !l.billed_qty) {
                          patch.billed_qty = q;
                        }
                        updateLine(l.key, patch);
                      }}
                      disabled={readonly}
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      className="num-input"
                      min={0}
                      max={l.qty}
                      value={l.billed_qty}
                      onChange={(e) =>
                        updateLine(l.key, {
                          billed_qty: Number(e.target.value),
                        })
                      }
                      disabled={readonly}
                      title="進貨數量含贈品;計價數量只算要付錢的"
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      className="num-input"
                      step="1"
                      value={l.unit_price}
                      onChange={(e) =>
                        updateLine(l.key, { unit_price: e.target.value })
                      }
                      disabled={readonly}
                    />
                  </td>
                  <td className="num">{calcAmount(l).toLocaleString()}</td>
                  <td className="num">
                    {needsSerial ? (
                      <span
                        className={
                          filled === l.qty
                            ? "serial-badge ok"
                            : "serial-badge"
                        }
                        title="點此列右側面板填序號"
                      >
                        {filled}/{l.qty}
                      </span>
                    ) : (
                      <span style={{ color: "var(--text-dim)" }}>—</span>
                    )}
                  </td>
                  <td className="num">
                    {item ? Number(item.unit_landed_cost).toLocaleString() : "—"}
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
         readonly={readonly}
         containerRef={serialPanelRef}
         onUpdateSerial={(idx, v) =>
           selectedLineKey && updateSerialAt(selectedLineKey, idx, v)
         }
         onPasteSerials={(idx, list) =>
           selectedLineKey && pasteSerialsAt(selectedLineKey, idx, list)
         }
       />
      </div>

      <div className="entry-footer">
        <div className="entry-summary">
          <span>
            未稅小計<b>{Math.round(estSubtotal).toLocaleString()}</b>
          </span>
          <span>
            稅額<b>{Math.round(estTax).toLocaleString()}</b>
          </span>
          <span>
            含稅總額<b>{Math.round(estTotal).toLocaleString()}</b>
          </span>
        </div>
      </div>

      {showConfirm && (
        <div
          className="modal-overlay"
          onClick={() => setShowConfirm(false)}
        >
          <div
            className="modal-card"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
          >
            <div className="modal-title">確認儲存進貨單?</div>
            <div className="modal-body">
              <div className="modal-row">
                <span>供應商</span>
                <b>{supplierOption?.label ?? "—"}</b>
              </div>
              <div className="modal-row">
                <span>入庫倉</span>
                <b>{warehouseOption?.label ?? "—"}</b>
              </div>
              <div className="modal-row">
                <span>單據日期</span>
                <b>{docDate}</b>
              </div>
              <div className="modal-sep" />
              <div className="modal-row">
                <span>明細行數</span>
                <b>{lines.length} 行</b>
              </div>
              <div className="modal-row">
                <span>總進貨數量</span>
                <b>
                  {lines.reduce((s, l) => s + Number(l.qty || 0), 0)} 件
                </b>
              </div>
              <div className="modal-row">
                <span>總計價數量</span>
                <b>
                  {lines.reduce(
                    (s, l) => s + Number(l.billed_qty || l.qty || 0),
                    0,
                  )}{" "}
                  件
                </b>
              </div>
              <div className="modal-sep" />
              <div className="modal-row">
                <span>未稅小計</span>
                <b>{Math.round(estSubtotal).toLocaleString()}</b>
              </div>
              <div className="modal-row">
                <span>稅額</span>
                <b>{Math.round(estTax).toLocaleString()}</b>
              </div>
              <div className="modal-row big">
                <span>含稅總額</span>
                <b>{Math.round(estTotal).toLocaleString()}</b>
              </div>
            </div>
            <div className="modal-actions">
              <button
                className="btn"
                type="button"
                onClick={() => setShowConfirm(false)}
                disabled={createMutation.isPending}
              >
                取消
              </button>
              <button
                className="btn primary"
                type="button"
                onClick={doSave}
                disabled={createMutation.isPending}
                autoFocus
              >
                {createMutation.isPending ? "儲存中…" : "確認儲存"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
