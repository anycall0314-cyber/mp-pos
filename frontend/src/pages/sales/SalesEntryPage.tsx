import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { ApiHttpError } from "@/api/client";
import {
  lookupCustomer,
  peekInvoiceNo,
  useCreateSalesOrder,
  useInvoiceTypes,
  usePaymentMethods,
  useSalesOrder,
  useSaveCustomer,
  useSaveSalesPerson,
  useVoidSalesOrder,
} from "@/api/hooks";
import {
  SalesProductHit,
  searchInStockSerials,
  searchProductsForSales,
  searchSalesPersons,
  searchSimCards,
  searchTelecomPlans,
  searchWarehouses,
} from "@/api/search";
import type {
  Customer,
  CustomerKind,
  PaymentMethod,
  Product,
  ProductSerial,
  SalesOrder,
  SalesOrderPayment,
  SimCard,
  TaxMethod,
  TelecomPlan,
} from "@/api/types";
import { Banner } from "@/components/Banner";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { Drawer } from "@/components/Drawer";
import { Checkbox, Field } from "@/components/Field";
import { Toolbar } from "@/components/Toolbar";

/** 把資料庫的 "100.00" / number 統一轉成整數字串(四捨五入,空 / NaN 還原成 "0")。 */
function toIntStr(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === "") return "0";
  const n = Number(v);
  if (!Number.isFinite(n)) return "0";
  return String(Math.round(n));
}

interface Line {
  key: string;
  line_no: number;
  product: number | "";
  productOption: ComboOption<Product> | null;
  qty: number;
  serialChoices: (ComboOption<ProductSerial> | null)[];
  unit_price: string;
  amount: string;
  msisdn: string;
  telecom_plan: number | "";
  telecomPlanOption: ComboOption<TelecomPlan> | null;
  sim_card: number | "";
  simCardOption: ComboOption<SimCard> | null;
  activation_date: string;
  commission: string;
}

function newLine(line_no: number): Line {
  return {
    key: crypto.randomUUID(),
    line_no,
    product: "",
    productOption: null,
    qty: 1,
    serialChoices: [],
    unit_price: "0",
    amount: "0",
    msisdn: "",
    telecom_plan: "",
    telecomPlanOption: null,
    sim_card: "",
    simCardOption: null,
    activation_date: "",
    commission: "0",
  };
}

function pickedSerialIds(line: Line): number[] {
  return line.serialChoices.filter((o): o is ComboOption<ProductSerial> => !!o).map((o) => o.id);
}

interface CheckoutModalProps {
  totalGross: number;
  subtotal: number;
  tax: number;
  itemsCount: number;
  customerLabel: string;
  methods: PaymentMethod[];
  amounts: Record<string, string>;
  notes: Record<string, string>;
  onAmountChange: (code: string, v: string) => void;
  onNoteChange: (code: string, v: string) => void;
  onCancel: () => void;
  onConfirm: () => void;
  isPending: boolean;
  savedSO: SalesOrder | null;
  onDone: () => void;
  onContinue: () => void;
}

/** 銷貨結帳 modal:依系統設定動態列出付款方式,可任意拆分。 */
function CheckoutModal({
  totalGross,
  subtotal,
  tax,
  itemsCount,
  customerLabel,
  methods,
  amounts,
  notes,
  onAmountChange,
  onNoteChange,
  onCancel,
  onConfirm,
  isPending,
  savedSO,
  onDone,
  onContinue,
}: CheckoutModalProps) {
  const paid = methods.reduce(
    (s, m) => s + (Number(amounts[m.code]) || 0),
    0,
  );
  const diff = totalGross - paid;
  const aligned = diff === 0;

  // 成功狀態:顯示單號 + 列印按鈕
  if (savedSO) {
    return (
      <div className="modal-overlay">
        <div
          className="modal-card checkout-modal"
          onClick={(e) => e.stopPropagation()}
          role="dialog"
          aria-modal="true"
        >
          <div className="modal-title" style={{ color: "#80d090" }}>
            結帳完成
          </div>
          <div className="modal-body">
            <div className="modal-row big">
              <span>單號</span>
              <b>{savedSO.no}</b>
            </div>
            <div className="modal-row">
              <span>客戶</span>
              <b>{customerLabel}</b>
            </div>
            <div className="modal-row">
              <span>含稅總額</span>
              <b>{Math.round(Number(savedSO.total)).toLocaleString()}</b>
            </div>
            {savedSO.invoice_no && (
              <div className="modal-row">
                <span>發票號碼</span>
                <b>{savedSO.invoice_no}</b>
              </div>
            )}
            {savedSO.payments && savedSO.payments.length > 0 && (
              <>
                <div className="modal-sep" />
                {savedSO.payments.map((p: SalesOrderPayment) => (
                  <div key={p.id} className="modal-row">
                    <span>{p.method_label}</span>
                    <b>
                      {Math.round(Number(p.amount)).toLocaleString()}
                      {p.note ? `(${p.note})` : ""}
                    </b>
                  </div>
                ))}
              </>
            )}
          </div>
          <div className="modal-actions">
            <button
              className="btn"
              type="button"
              onClick={() =>
                window.open(
                  `/sales/${savedSO.id}/print/receipt`,
                  "_blank",
                )
              }
            >
              列印收據
            </button>
            <button
              className="btn"
              type="button"
              disabled={!savedSO.invoice_form || savedSO.invoice_form === "none"}
              title={
                !savedSO.invoice_form || savedSO.invoice_form === "none"
                  ? "此單未開發票"
                  : "列印發票"
              }
              onClick={() =>
                window.open(
                  `/sales/${savedSO.id}/print/invoice`,
                  "_blank",
                )
              }
            >
              列印發票
            </button>
            <button className="btn" type="button" onClick={onDone}>
              完成(回列表)
            </button>
            <button className="btn primary" type="button" onClick={onContinue}>
              繼續開單
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div
        className="modal-card checkout-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="modal-title">結帳確認</div>
        <div className="modal-body">
          <div className="modal-row">
            <span>客戶</span>
            <b>{customerLabel}</b>
          </div>
          <div className="modal-row">
            <span>明細</span>
            <b>{itemsCount} 行</b>
          </div>
          <div className="modal-sep" />
          <div className="modal-row">
            <span>未稅小計</span>
            <b>{Math.round(subtotal).toLocaleString()}</b>
          </div>
          <div className="modal-row">
            <span>稅額</span>
            <b>{Math.round(tax).toLocaleString()}</b>
          </div>
          <div className="modal-row big">
            <span>應收</span>
            <b>{Math.round(totalGross).toLocaleString()}</b>
          </div>
          <div className="modal-sep" />
          {methods.map((m, i) => (
            <div key={m.code} className="checkout-pay-row">
              <label>
                {m.name}
                <span
                  className="checkout-kind-tag"
                  style={{
                    color:
                      m.kind === "cash"
                        ? "#80d090"
                        : m.kind === "transfer"
                        ? "#80b0d0"
                        : "var(--text-dim)",
                  }}
                >
                  {m.kind_label}
                </span>
              </label>
              <input
                type="number"
                value={amounts[m.code] ?? "0"}
                autoFocus={i === 0}
                onChange={(e) => onAmountChange(m.code, e.target.value)}
              />
            </div>
          ))}
          {methods
            .filter(
              (m) =>
                m.kind !== "cash" && Number(amounts[m.code]) > 0,
            )
            .map((m) => (
              <div key={m.code + "_note"} className="checkout-pay-row">
                <label>{m.name} 備註</label>
                <input
                  value={notes[m.code] ?? ""}
                  onChange={(e) => onNoteChange(m.code, e.target.value)}
                  maxLength={50}
                  placeholder="例:卡號末 4 碼 / 交易序號"
                />
              </div>
            ))}
          <div
            className="checkout-status"
            style={{ color: aligned ? "#80d090" : "#ff7070" }}
          >
            {aligned
              ? `已對齊(共 ${Math.round(paid).toLocaleString()})`
              : diff > 0
              ? `尚需 ${Math.round(diff).toLocaleString()}`
              : `多收 ${Math.round(Math.abs(diff)).toLocaleString()}`}
          </div>
        </div>
        <div className="modal-actions">
          <button
            className="btn"
            type="button"
            onClick={onCancel}
            disabled={isPending}
          >
            取消
          </button>
          <button
            className="btn primary"
            type="button"
            onClick={onConfirm}
            disabled={!aligned || isPending}
          >
            {isPending ? "結帳中…" : "確認結帳"}
          </button>
        </div>
      </div>
    </div>
  );
}

interface SalesSerialAsideProps {
  line: Line | null;
  warehouseId: number | "";
  readonly: boolean;
  containerRef: React.RefObject<HTMLDivElement>;
  onPickSerial: (
    idx: number,
    option: ComboOption<ProductSerial> | null,
  ) => void;
}

function SalesSerialAside({
  line,
  warehouseId,
  readonly,
  containerRef,
  onPickSerial,
}: SalesSerialAsideProps) {
  const product = line?.productOption?.payload;
  const needs = !!product?.requires_serial && !product.is_virtual;

  return (
    <aside className="serial-aside" ref={containerRef}>
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
          <div className="serial-aside-hint">此商品不追蹤序號</div>
        )}
        {line && needs && !warehouseId && (
          <div className="serial-aside-hint">請先選出貨倉</div>
        )}
        {line && needs && warehouseId && (
          <table className="serial-slot-table">
            <thead>
              <tr>
                <th style={{ width: 50 }}>序</th>
                <th>出貨序號</th>
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
                            warehouse: warehouseId as number,
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

const CUSTOMER_KINDS: { value: CustomerKind; label: string }[] = [
  { value: "individual", label: "個人" },
  { value: "peer", label: "同業 / 盤商" },
  { value: "corporate", label: "企業" },
  { value: "other", label: "其他" },
];

const TAX_METHODS: { value: TaxMethod; label: string }[] = [
  { value: "taxable_included", label: "應稅內含" },
  { value: "taxable_excluded", label: "應稅外加" },
  { value: "tax_free", label: "免稅" },
  { value: "zero_tax", label: "零稅" },
];

function calcAmount(line: Line) {
  return Number(line.amount);
}

interface LineRowProps {
  line: Line;
  idx: number;
  readonly: boolean;
  warehouseId: number | "";
  update: (patch: Partial<Line>) => void;
  remove: () => void;
}

interface LineRowExtraProps {
  active: boolean;
  onSelect: () => void;
}

function LineRow({
  line,
  idx,
  readonly,
  warehouseId,
  update,
  remove,
  active,
  onSelect,
}: LineRowProps & LineRowExtraProps) {
  const product = line.productOption?.payload;
  const plan = line.telecomPlanOption?.payload;
  const requiresCard =
    !!plan && (plan.kind === "new" || plan.kind === "portin");
  const allowTelecom = !!product?.allows_telecom_line;
  const allowCommission = !!product?.allows_commission;
  const needsSerial = !!product?.requires_serial && !product?.is_virtual;
  const filledSerials = pickedSerialIds(line).length;

  function onProductPick(
    pid: number | "",
    opt?: ComboOption<SalesProductHit>,
  ) {
    const p = opt?.payload;
    // 選到商品時把建議零售價一次帶到單價與金額(各自獨立,之後互不同步)
    const userTypedAmount =
      Number(line.amount) !== 0 && Number(line.amount) !== Number(line.unit_price);
    // 中古機打/掃 IMEI 命中時,優先帶該支序號的自訂售價
    const msCustom =
      p?.is_secondhand && p?.matched_serial?.custom_unit_price;
    const defaultPrice = toIntStr(
      msCustom && Number(msCustom) > 0 ? msCustom : (p?.list_price ?? "0"),
    );

    // 路徑一:搜尋帶 matched_serial(打 IMEI 命中)→ 立即把該序號掛上
    const autoSerial = p?.matched_serial
      ? ({
          id: p.matched_serial.id,
          label: p.matched_serial.serial_no,
          secondary: p.sku ?? "",
          payload: undefined as unknown as ProductSerial,
        } as ComboOption<ProductSerial>)
      : null;

    const pickedQty = autoSerial ? 1 : line.qty;
    update({
      product: pid,
      productOption: opt ? { ...opt, payload: opt.payload as Product } : null,
      // 通常 IMEI 命中 = 賣 1 隻,把該行 qty 設 1、序號預填;否則清空待挑
      qty: pickedQty,
      serialChoices: autoSerial ? [autoSerial] : [],
      unit_price: p ? defaultPrice : line.unit_price,
      amount:
        p && !userTypedAmount
          ? toIntStr(Number(defaultPrice) * pickedQty)
          : line.amount,
      msisdn: p?.allows_telecom_line ? line.msisdn : "",
      telecom_plan: p?.allows_telecom_line ? line.telecom_plan : "",
      telecomPlanOption: p?.allows_telecom_line ? line.telecomPlanOption : null,
      sim_card: p?.allows_telecom_line ? line.sim_card : "",
      simCardOption: p?.allows_telecom_line ? line.simCardOption : null,
      activation_date: p?.allows_telecom_line ? line.activation_date : "",
      commission: p?.allows_commission ? line.commission : "0",
    });

    // 路徑二:沒打 IMEI,但商品要序號 + 該倉只有 1 隻在庫 → 自動把那隻掛上
    // 條件:選到產品、需要序號、非虛擬、有指定倉、且不是已經透過 IMEI 命中
    if (
      p &&
      pid !== "" &&
      p.requires_serial &&
      !p.is_virtual &&
      warehouseId !== "" &&
      !autoSerial
    ) {
      // 用 query="" + page_size=2 拿這個商品在這個倉的在庫序號:
      // - 0 筆 → 沒貨
      // - 1 筆 → 自動掛上去
      // - 2 筆以上 → 讓使用者自己挑
      searchInStockSerials("", {
        product: pid as number,
        warehouse: warehouseId as number,
      })
        .then((serials) => {
          if (serials.length !== 1) return;
          const only = serials[0];
          // 同步把當下使用者最新的 line 狀態取出再更新;
          // patch 只動 serialChoices(必要時連動中古機售價)
          const patch: Partial<Line> = {
            qty: 1,
            serialChoices: [only],
          };
          if (p.is_secondhand) {
            const cp = only.payload?.custom_unit_price;
            if (cp && Number(cp) > 0) {
              patch.unit_price = toIntStr(cp);
              patch.amount = toIntStr(cp);
            }
          }
          update(patch);
        })
        .catch(() => {
          // 失敗就略過,使用者仍可手動挑
        });
    }
  }

  function onPlanPick(
    pid: number | "",
    opt?: ComboOption<TelecomPlan>,
  ) {
    const newPlan = opt?.payload;
    const newRequiresCard =
      !!newPlan && (newPlan.kind === "new" || newPlan.kind === "portin");
    const keepCard =
      newRequiresCard &&
      line.simCardOption?.payload?.vendor === newPlan?.carrier;
    update({
      telecom_plan: pid,
      telecomPlanOption: opt ?? null,
      commission: newPlan ? toIntStr(newPlan.commission) : line.commission,
      sim_card: keepCard ? line.sim_card : "",
      simCardOption: keepCard ? line.simCardOption : null,
    });
  }

  return (
    <tr
      className={active ? "line-row-active" : undefined}
      onClick={onSelect}
    >
      <td>{idx + 1}</td>
      <td>
        <ComboBox<SalesProductHit>
          value={line.product}
          selectedOption={
            line.productOption as ComboOption<SalesProductHit> | null
          }
          onChange={onProductPick}
          fetchOptions={(q) =>
            searchProductsForSales(q, { warehouseId })
          }
          disabled={readonly || !warehouseId}
          placeholder={
            warehouseId
              ? "搜尋:品名 / 品號 / 條碼 / IMEI"
              : "請先選出貨倉"
          }
        />
      </td>
      <td>
        <input
          type="number"
          className="num-input"
          min={1}
          value={line.qty}
          onChange={(e) => {
            const q = Math.max(1, Number(e.target.value));
            update({
              qty: q,
              amount: toIntStr(q * Number(line.unit_price || 0)),
            });
          }}
          disabled={readonly}
        />
      </td>
      <td className="num">
        {needsSerial ? (
          <span
            className={
              filledSerials === line.qty ? "serial-badge ok" : "serial-badge"
            }
            title="點此列右側面板挑序號"
          >
            {filledSerials}/{line.qty}
          </span>
        ) : (
          <span style={{ color: "var(--text-dim)" }}>—</span>
        )}
      </td>
      <td>
        <input
          type="number"
          className="num-input"
          step="1"
          value={line.unit_price}
          onChange={(e) =>
            update({
              unit_price: e.target.value,
              amount: toIntStr(line.qty * Number(e.target.value || 0)),
            })
          }
          onBlur={(e) =>
            update({
              unit_price: toIntStr(e.target.value),
              amount: toIntStr(line.qty * Number(e.target.value || 0)),
            })
          }
          disabled={readonly}
        />
      </td>
      <td>
        <input
          type="number"
          className="num-input"
          step="1"
          value={line.amount}
          onChange={(e) => update({ amount: e.target.value })}
          onBlur={(e) => update({ amount: toIntStr(e.target.value) })}
          disabled={readonly}
        />
      </td>

      <td className={allowTelecom ? "telecom-cell" : "disabled-cell"}>
        <input
          value={line.msisdn}
          onChange={(e) => update({ msisdn: e.target.value })}
          disabled={readonly || !allowTelecom}
        />
      </td>
      <td className={allowTelecom ? "telecom-cell" : "disabled-cell"}>
        {allowTelecom ? (
          <ComboBox<TelecomPlan>
            value={line.telecom_plan}
            selectedOption={line.telecomPlanOption}
            onChange={onPlanPick}
            fetchOptions={(q) => searchTelecomPlans(q, { activeOnly: true })}
            disabled={readonly}
            placeholder="搜尋方案"
          />
        ) : (
          <span style={{ color: "var(--text-dim)" }}>—</span>
        )}
      </td>
      <td
        className={
          allowTelecom && requiresCard ? "telecom-cell" : "disabled-cell"
        }
      >
        {allowTelecom && requiresCard ? (
          <ComboBox<SimCard>
            value={line.sim_card}
            selectedOption={line.simCardOption}
            onChange={(cid, opt) =>
              update({ sim_card: cid, simCardOption: opt ?? null })
            }
            fetchOptions={(q) =>
              searchSimCards(q, {
                vendor: plan?.carrier,
                inStockOnly: true,
              })
            }
            disabled={readonly}
            placeholder="搜尋卡號"
          />
        ) : (
          <span style={{ color: "var(--text-dim)" }}>—</span>
        )}
      </td>
      <td className={allowCommission ? "telecom-cell" : "disabled-cell"}>
        <input
          type="number"
          className="num-input"
          step="1"
          value={line.commission}
          onChange={(e) => update({ commission: e.target.value })}
          onBlur={(e) => update({ commission: toIntStr(e.target.value) })}
          disabled={readonly || !allowCommission}
        />
      </td>
      <td className="row-actions">
        {!readonly && (
          <button onClick={remove} type="button">
            刪
          </button>
        )}
      </td>
    </tr>
  );
}

const SALES_DRAFT_KEY = "sales-entry-draft";

interface SalesDraft {
  customer: Customer | null;
  memberPhone: string;
  warehouse: number | "";
  warehouseOption: ComboOption<unknown> | null;
  docDate: string;
  taxMethod: TaxMethod;
  buyerTaxId: string;
  invoiceForm: string;
  invoiceNo: string;
  invoiceDate: string;
  salesPerson: number | "";
  salesPersonOption: ComboOption<unknown> | null;
  note: string;
  lines: Line[];
}

function loadSalesDraft(): SalesDraft | null {
  try {
    const raw = sessionStorage.getItem(SALES_DRAFT_KEY);
    return raw ? (JSON.parse(raw) as SalesDraft) : null;
  } catch {
    return null;
  }
}

export function SalesEntryPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const isNew = id === "new";
  const soId = isNew ? null : Number(id);

  const existing = useSalesOrder(soId);
  const createMutation = useCreateSalesOrder();
  const voidMutation = useVoidSalesOrder();
  const saveCustomer = useSaveCustomer();
  const saveSalesPerson = useSaveSalesPerson();
  const invoiceTypesQuery = useInvoiceTypes({ activeOnly: true });
  const invoiceTypes = invoiceTypesQuery.data ?? [];
  const defaultInvoiceCode =
    invoiceTypes.find((t) => t.is_default)?.code ?? invoiceTypes[0]?.code ?? "";

  // 新單模式才啟用草稿;切到其他分頁回來不會掉
  const draft = useRef<SalesDraft | null>(
    isNew ? loadSalesDraft() : null,
  ).current;

  // 會員(用電話查):customer = null 代表散客
  const [customer, setCustomer] = useState<Customer | null>(
    draft?.customer ?? null,
  );
  const [memberPhone, setMemberPhone] = useState(draft?.memberPhone ?? "");
  const [memberStatus, setMemberStatus] = useState<
    "idle" | "checking" | "found" | "not_found"
  >(draft?.customer ? "found" : "idle");
  const [showCreateMember, setShowCreateMember] = useState(false);
  const [newMember, setNewMember] = useState<{
    name: string;
    tax_id: string;
    kind: CustomerKind;
    is_member: boolean;
  }>({
    name: "",
    tax_id: "",
    kind: "individual",
    is_member: false,
  });
  const [warehouse, setWarehouse] = useState<number | "">(
    draft?.warehouse ?? "",
  );
  const [warehouseOption, setWarehouseOption] =
    useState<ComboOption<unknown> | null>(draft?.warehouseOption ?? null);
  const [docDate, setDocDate] = useState(
    () => draft?.docDate ?? new Date().toISOString().slice(0, 10),
  );
  const [taxMethod, setTaxMethod] = useState<TaxMethod>(
    draft?.taxMethod ?? "taxable_included",
  );
  const [buyerTaxId, setBuyerTaxId] = useState(draft?.buyerTaxId ?? "");
  const [invoiceForm, setInvoiceForm] = useState<string>(
    draft?.invoiceForm ?? "",
  );
  const [invoiceNo, setInvoiceNo] = useState(draft?.invoiceNo ?? "");
  const [invoiceDate, setInvoiceDate] = useState(draft?.invoiceDate ?? "");
  // 新單時:依發票類型 peek 下一張要開的號碼;送單時後端會原子地取走它
  const [previewInvoiceNo, setPreviewInvoiceNo] = useState<string | null>(null);
  const [salesPerson, setSalesPerson] = useState<number | "">(
    draft?.salesPerson ?? "",
  );
  const [salesPersonOption, setSalesPersonOption] =
    useState<ComboOption<unknown> | null>(draft?.salesPersonOption ?? null);
  const [showCreateSalesPerson, setShowCreateSalesPerson] = useState(false);
  const [newSalesPerson, setNewSalesPerson] = useState({ code: "", name: "" });
  const [note, setNote] = useState(draft?.note ?? "");
  const [lines, setLines] = useState<Line[]>(() => {
    if (draft?.lines && draft.lines.length > 0) {
      // 草稿可能來自舊版本,單價 / 金額還是 "0.00" 格式,進來時統一轉整數
      return draft.lines.map((l) => ({
        ...l,
        unit_price: toIntStr(l.unit_price),
        amount: toIntStr(l.amount),
        commission: toIntStr(l.commission),
      }));
    }
    return [newLine(1)];
  });
  const [selectedLineKey, setSelectedLineKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showConfirm, setShowConfirm] = useState(false);

  // 掃碼快速結帳
  const [scanCode, setScanCode] = useState("");
  const [scanMsg, setScanMsg] = useState<{ ok: boolean; text: string } | null>(
    null,
  );
  const [scanning, setScanning] = useState(false);
  const scanRef = useRef<HTMLInputElement | null>(null);
  useEffect(() => {
    if (!readonly) scanRef.current?.focus();
    // 僅在新單載入時自動聚焦掃描框
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // payAmounts / payNotes 都以 PaymentMethod.code 為 key
  const [payAmounts, setPayAmounts] = useState<Record<string, string>>({});
  const [payNotes, setPayNotes] = useState<Record<string, string>>({});
  // 結帳成功後保留 SO 資料在 modal 內展示,讓使用者直接列印
  const [savedSO, setSavedSO] = useState<SalesOrder | null>(null);

  const paymentMethodsQuery = usePaymentMethods({ activeOnly: true });
  const paymentMethods = paymentMethodsQuery.data ?? [];
  const serialPanelRef = useRef<HTMLDivElement>(null);

  const isTaxable =
    taxMethod === "taxable_included" || taxMethod === "taxable_excluded";

  const readonly = !isNew;

  // 新單載入發票類型主檔後自動帶預設
  useEffect(() => {
    if (isNew && !invoiceForm && defaultInvoiceCode) {
      setInvoiceForm(defaultInvoiceCode);
      if (defaultInvoiceCode === "none") setTaxMethod("tax_free");
    }
  }, [isNew, invoiceForm, defaultInvoiceCode]);

  const noInvoice = invoiceForm === "" || invoiceForm === "none";

  // 新單時把表單狀態 debounce 寫進 sessionStorage,跨分頁不掉
  useEffect(() => {
    if (!isNew) return;
    const snapshot: SalesDraft = {
      customer,
      memberPhone,
      warehouse,
      warehouseOption,
      docDate,
      taxMethod,
      buyerTaxId,
      invoiceForm,
      invoiceNo,
      invoiceDate,
      salesPerson,
      salesPersonOption,
      note,
      lines,
    };
    const handle = setTimeout(() => {
      try {
        sessionStorage.setItem(SALES_DRAFT_KEY, JSON.stringify(snapshot));
      } catch {}
    }, 250);
    return () => clearTimeout(handle);
  }, [
    isNew,
    customer,
    memberPhone,
    warehouse,
    warehouseOption,
    docDate,
    taxMethod,
    buyerTaxId,
    invoiceForm,
    invoiceNo,
    invoiceDate,
    salesPerson,
    salesPersonOption,
    note,
    lines,
  ]);

  function clearDraft() {
    sessionStorage.removeItem(SALES_DRAFT_KEY);
  }

  function discardDraft() {
    if (!confirm("確定清空目前已填寫的內容?")) return;
    clearDraft();
    setCustomer(null);
    setMemberPhone("");
    setMemberStatus("idle");
    setWarehouse("");
    setWarehouseOption(null);
    setDocDate(new Date().toISOString().slice(0, 10));
    setTaxMethod("taxable_included");
    setBuyerTaxId("");
    setInvoiceForm(defaultInvoiceCode);
    setInvoiceNo("");
    setInvoiceDate("");
    setSalesPerson("");
    setSalesPersonOption(null);
    setNote("");
    setLines([newLine(1)]);
    setSelectedLineKey(null);
  }

  // 連續開單:結帳完成後重置成新單,但「保留」出貨倉與業務員,只清會員與明細
  function continueNewSale() {
    clearDraft();
    setSavedSO(null);
    setShowConfirm(false);
    // 清:會員 / 明細 / 付款 / 發票號 / 買受人統編 / 備註
    setCustomer(null);
    setMemberPhone("");
    setMemberStatus("idle");
    setLines([newLine(1)]);
    setSelectedLineKey(null);
    setPayAmounts({});
    setPayNotes({});
    setBuyerTaxId("");
    setInvoiceNo("");
    setInvoiceDate("");
    setNote("");
    setDocDate(new Date().toISOString().slice(0, 10));
    // 保留:warehouse / warehouseOption / salesPerson / salesPersonOption /
    //       taxMethod / invoiceForm(沿用方便連續結帳)
  }

  // 新單時用 peek 預覽下一張發票號碼;切換發票類型時 re-peek
  useEffect(() => {
    if (!isNew) return;
    if (noInvoice) {
      setPreviewInvoiceNo(null);
      return;
    }
    let cancelled = false;
    peekInvoiceNo(invoiceForm).then((no) => {
      if (!cancelled) setPreviewInvoiceNo(no);
    });
    return () => {
      cancelled = true;
    };
  }, [isNew, invoiceForm, noInvoice]);

  useEffect(() => {
    if (existing.data && !isNew) {
      const d = existing.data;
      if (d.customer) {
        setCustomer({
          id: d.customer,
          phone: d.customer_phone ?? "",
          name: d.customer_name ?? "",
          kind: "individual",
          kind_label: "個人",
          is_member: false,
          tax_id: "",
          address: "",
          note: "",
          is_active: true,
        });
        setMemberPhone(d.customer_phone ?? "");
        setMemberStatus("found");
      }
      setWarehouse(d.warehouse);
      setWarehouseOption({
        id: d.warehouse,
        label: d.warehouse_name,
        secondary: d.warehouse_code,
      });
      setDocDate(d.doc_date);
      setTaxMethod(d.tax_method);
      setBuyerTaxId(d.buyer_tax_id);
      setInvoiceForm(d.invoice_form ?? "");
      setInvoiceNo(d.invoice_no ?? "");
      setInvoiceDate(d.invoice_date ?? "");
      setSalesPerson(d.sales_person ?? "");
      if (d.sales_person) {
        setSalesPersonOption({
          id: d.sales_person,
          label: d.sales_person_name ?? "",
          secondary: d.sales_person_code ?? "",
        });
      }
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
            // 用既有 SO item 的 flags 拼回 Product 形狀
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
              allows_telecom_line: it.product_allows_telecom_line,
              allows_commission: it.product_allows_commission,
              is_virtual: it.product_is_virtual,
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
          unit_price: toIntStr(it.unit_price),
          amount: toIntStr(it.amount),
          msisdn: it.msisdn,
          telecom_plan: it.telecom_plan ?? "",
          telecomPlanOption: it.telecom_plan
            ? {
                id: it.telecom_plan,
                label: it.telecom_plan_display,
                secondary: it.telecom_plan_code,
              }
            : null,
          sim_card: it.sim_card ?? "",
          simCardOption: it.sim_card
            ? {
                id: it.sim_card,
                label: it.sim_card_no,
                secondary: "",
              }
            : null,
          activation_date: it.activation_date ?? "",
          commission: toIntStr(it.commission),
        })),
      );
    }
  }, [existing.data, isNew]);

  async function handleMemberLookup() {
    const phone = memberPhone.trim();
    if (!phone) {
      setCustomer(null);
      setMemberStatus("idle");
      return;
    }
    setMemberStatus("checking");
    const c = await lookupCustomer(phone);
    if (c) {
      setCustomer(c);
      setMemberStatus("found");
      if (isTaxable && c.tax_id && !buyerTaxId) {
        setBuyerTaxId(c.tax_id);
      }
    } else {
      setCustomer(null);
      setMemberStatus("not_found");
    }
  }

  async function handleCreateSalesPerson() {
    if (!newSalesPerson.code.trim() || !newSalesPerson.name.trim()) return;
    try {
      const created = await saveSalesPerson.mutateAsync({
        code: newSalesPerson.code.trim(),
        name: newSalesPerson.name.trim(),
      });
      setSalesPerson(created.id);
      setSalesPersonOption({
        id: created.id,
        label: created.name,
        secondary: created.code,
      });
      setShowCreateSalesPerson(false);
      setNewSalesPerson({ code: "", name: "" });
    } catch (e) {
      if (e instanceof ApiHttpError) {
        setError(`新增業務員失敗:${JSON.stringify(e.body)}`);
      }
    }
  }

  async function handleCreateMember() {
    const phone = memberPhone.trim();
    if (!phone || !newMember.name.trim()) return;
    try {
      const created = await saveCustomer.mutateAsync({
        phone,
        name: newMember.name.trim(),
        kind: newMember.kind,
        is_member: newMember.is_member,
        tax_id: newMember.tax_id || undefined,
      });
      setCustomer(created);
      setMemberStatus("found");
      setShowCreateMember(false);
      setNewMember({
        name: "",
        tax_id: "",
        kind: "individual",
        is_member: false,
      });
    } catch (e) {
      if (e instanceof ApiHttpError) {
        const body = e.body;
        setError(`新增客戶失敗:${JSON.stringify(body)}`);
      }
    }
  }

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

  function serialOptionFrom(s: {
    id: number;
    serial_no: string;
    sku?: string;
  }): ComboOption<ProductSerial> {
    return {
      id: s.id,
      label: s.serial_no,
      secondary: s.sku ?? "",
      payload: undefined as unknown as ProductSerial,
    };
  }

  // 把掃到的商品/序號加進明細;有空白行(未選商品)就用它,否則新增一行
  function applyScannedProduct(p: SalesProductHit) {
    const isSerial = !!p.requires_serial && !p.is_virtual;
    const ms = p.matched_serial ?? null;
    const productOption: ComboOption<Product> = {
      id: p.id,
      label: p.name,
      secondary: [p.sku, p.category_name].filter(Boolean).join(" / "),
      payload: p as Product,
    };
    const price = toIntStr(p.list_price ?? "0");

    setLines((ls) => {
      const existingIdx = ls.findIndex((l) => l.product === p.id);

      if (isSerial && ms) {
        // 防重複:此序號已在單上
        if (ls.some((l) => l.serialChoices.some((s) => s?.id === ms.id))) {
          return ls;
        }
        const opt = serialOptionFrom({ id: ms.id, serial_no: ms.serial_no });
        // 中古機:優先用該支序號的自訂售價
        const serialPrice =
          p.is_secondhand && ms.custom_unit_price && Number(ms.custom_unit_price) > 0
            ? toIntStr(ms.custom_unit_price)
            : price;
        if (existingIdx >= 0) {
          return ls.map((l, i) =>
            i === existingIdx
              ? {
                  ...l,
                  qty: l.qty + 1,
                  serialChoices: [...l.serialChoices, opt],
                  // 中古機一機一價:單價沿用第一支(同型號自訂價通常一致),
                  // 金額依數量重算
                  amount: toIntStr((l.qty + 1) * Number(l.unit_price || 0)),
                }
              : l,
          );
        }
        const fresh = newLine(ls.length + 1);
        fresh.product = p.id;
        fresh.productOption = productOption;
        fresh.qty = 1;
        fresh.serialChoices = [opt];
        fresh.unit_price = serialPrice;
        fresh.amount = serialPrice;
        return replaceEmptyOrAppend(ls, fresh);
      }

      if (!isSerial) {
        // 配件:同商品累加數量
        if (existingIdx >= 0) {
          return ls.map((l, i) =>
            i === existingIdx
              ? {
                  ...l,
                  qty: l.qty + 1,
                  amount: toIntStr((l.qty + 1) * Number(l.unit_price || 0)),
                }
              : l,
          );
        }
        const fresh = newLine(ls.length + 1);
        fresh.product = p.id;
        fresh.productOption = productOption;
        fresh.qty = 1;
        fresh.unit_price = price;
        fresh.amount = price;
        return replaceEmptyOrAppend(ls, fresh);
      }

      // 序號商品但掃到的是型號(沒有 matched_serial):加一行待補序號
      const fresh = newLine(ls.length + 1);
      fresh.product = p.id;
      fresh.productOption = productOption;
      fresh.qty = 1;
      fresh.unit_price = price;
      fresh.amount = price;
      return replaceEmptyOrAppend(ls, fresh);
    });
  }

  function replaceEmptyOrAppend(ls: Line[], fresh: Line): Line[] {
    const emptyIdx = ls.findIndex((l) => l.product === "");
    if (emptyIdx >= 0) {
      const copy = [...ls];
      fresh.line_no = ls[emptyIdx].line_no;
      copy[emptyIdx] = fresh;
      return copy;
    }
    return [...ls, fresh];
  }

  async function handleScan(raw: string) {
    const code = raw.trim();
    if (!code) return;
    if (!warehouse) {
      setScanMsg({ ok: false, text: "請先選出貨倉再掃碼" });
      return;
    }
    setScanning(true);
    try {
      const results = await searchProductsForSales(code, {
        warehouseId: warehouse,
      });
      if (results.length === 0) {
        setScanMsg({ ok: false, text: `查無:${code}` });
        return;
      }
      // 優先:IMEI 完全命中 → 條碼/品號完全命中 → 第一筆
      const best =
        results.find((r) => r.payload?.matched_serial?.serial_no === code) ??
        results.find(
          (r) => r.payload?.barcode === code || r.payload?.sku === code,
        ) ??
        results[0];
      const p = best.payload as SalesProductHit;
      const isSerial = !!p.requires_serial && !p.is_virtual;

      if (
        isSerial &&
        p.matched_serial &&
        lines.some((l) =>
          l.serialChoices.some((s) => s?.id === p.matched_serial!.id),
        )
      ) {
        setScanMsg({
          ok: false,
          text: `序號 ${p.matched_serial.serial_no} 已在單上`,
        });
        return;
      }

      applyScannedProduct(p);
      if (isSerial && !p.matched_serial) {
        setScanMsg({ ok: true, text: `已加入 ${p.name}(請補序號)` });
      } else if (isSerial && p.matched_serial) {
        setScanMsg({
          ok: true,
          text: `已加入 ${p.name} · IMEI ${p.matched_serial.serial_no}`,
        });
      } else {
        setScanMsg({ ok: true, text: `已加入 ${p.name}` });
      }
    } catch (e) {
      setScanMsg({ ok: false, text: "掃碼查詢失敗,請重試" });
    } finally {
      setScanning(false);
      setScanCode("");
      // 回到掃描框等下一槍
      scanRef.current?.focus();
    }
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
        const patch: Partial<Line> = { serialChoices: next };
        // 中古機:挑到序號就把該序號的自定售價帶入單價(只在第 0 格觸發,避免亂蓋)
        const product = l.productOption?.payload;
        if (product?.is_secondhand && idx === 0 && option) {
          const cp = option.payload?.custom_unit_price;
          if (cp && Number(cp) > 0) {
            patch.unit_price = String(cp);
            patch.amount = toIntStr(Number(cp) * l.qty);
          }
        }
        return { ...l, ...patch };
      }),
    );
  }

  const subtotalRaw = lines.reduce((s, l) => s + (calcAmount(l) || 0), 0);
  const [estSubtotal, estTax, estTotal] = (() => {
    const raw = subtotalRaw;
    if (taxMethod === "taxable_included") {
      const sub = raw / 1.05;
      return [sub, raw - sub, raw];
    }
    if (taxMethod === "taxable_excluded") {
      return [raw, raw * 0.05, raw * 1.05];
    }
    return [raw, 0, raw];
  })();

  // 預估毛利 = sum(未稅 amount - cost + commission)
  const estGrossMargin = lines.reduce((sum, l) => {
    const p = l.productOption?.payload;
    if (!p) return sum;
    const lineAmount = Number(l.amount) || 0;
    const lineCost = p.is_virtual ? 0 : Number(p.weighted_avg_cost) || 0;
    const lineComm = Number(l.commission) || 0;
    const netAmount =
      taxMethod === "taxable_included" ? lineAmount / 1.05 : lineAmount;
    return sum + netAmount - lineCost + lineComm;
  }, 0);

  function validate(): string | null {
    if (!warehouse) return "請選出貨倉";
    if (lines.length === 0) return "至少一筆明細";
    const seen = new Set<number>();
    for (const l of lines) {
      if (!l.product) return `第 ${l.line_no} 行未選商品`;
      if (l.qty <= 0) return `第 ${l.line_no} 行數量需 > 0`;
      const product = l.productOption?.payload;
      if (product?.requires_serial && !product.is_virtual) {
        const picked = pickedSerialIds(l);
        if (picked.length !== l.qty) {
          return `第 ${l.line_no} 行需 ${l.qty} 個序號,目前選了 ${picked.length}`;
        }
        for (const sid of picked) {
          if (seen.has(sid)) return `序號 #${sid} 在整單內出現多次`;
          seen.add(sid);
        }
      }
    }
    return null;
  }

  function openConfirm() {
    setError(null);
    const err = validate();
    if (err) {
      setError(err);
      return;
    }
    if (paymentMethods.length === 0) {
      setError("尚未設定任何啟用中的付款方式,請至系統設定新增");
      return;
    }
    // 預設:把整筆金額放在「預設」方法,其他為 0
    const total = Math.round(estTotal);
    const defaultMethod =
      paymentMethods.find((m) => m.is_default) ?? paymentMethods[0];
    const amounts: Record<string, string> = {};
    const notes: Record<string, string> = {};
    for (const m of paymentMethods) {
      amounts[m.code] = m.code === defaultMethod.code ? String(total) : "0";
      notes[m.code] = "";
    }
    setPayAmounts(amounts);
    setPayNotes(notes);
    setShowConfirm(true);
  }

  async function doSave() {
    setError(null);
    const target = Math.round(estTotal);
    const paid = Object.values(payAmounts).reduce(
      (s, v) => s + (Number(v) || 0),
      0,
    );
    if (paid !== target) {
      setError(`付款金額 ${paid} 與含稅總額 ${target} 不一致`);
      return;
    }
    const payments: Array<{ method: string; amount: string; note?: string }> = [];
    for (const m of paymentMethods) {
      const amt = Number(payAmounts[m.code]) || 0;
      if (amt === 0) continue;
      payments.push({
        method: m.code,
        amount: String(amt),
        note: payNotes[m.code] || "",
      });
    }
    try {
      const created = await createMutation.mutateAsync({
        customer: customer ? customer.id : null,
        warehouse: warehouse as number,
        doc_date: docDate,
        tax_method: taxMethod,
        buyer_tax_id: isTaxable ? buyerTaxId : "",
        invoice_form: invoiceForm,
        invoice_no: invoiceNo,
        invoice_date: invoiceDate || null,
        sales_person: salesPerson === "" ? null : (salesPerson as number),
        note,
        items: lines.map((l, idx) => ({
          line_no: idx + 1,
          product: l.product as number,
          qty: l.qty,
          unit_price: l.unit_price,
          amount: l.amount,
          serial_ids: pickedSerialIds(l),
          msisdn: l.msisdn,
          telecom_plan:
            l.telecom_plan === "" ? null : (l.telecom_plan as number),
          sim_card: l.sim_card === "" ? null : (l.sim_card as number),
          // 上線日預設 = 單據日期;之後會有獨立分頁修改實際上線時間
          activation_date:
            l.activation_date ||
            (l.telecom_plan !== "" ? docDate : null),
          commission: l.commission || "0",
        })),
        payments,
      } as Parameters<typeof createMutation.mutateAsync>[0]);
      clearDraft();
      // 結帳成功:不關 modal,改顯示成功狀態 + 列印按鈕
      setSavedSO(created);
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
    if (!confirm(`確定要作廢銷貨單 ${existing.data.no}?序號會退回在庫,SIM 卡也會退回在庫。`)) {
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
    ? "新增銷貨單"
    : `${existing.data?.no} ${isVoid ? "(已作廢)" : "(檢視)"}`;

  return (
    <div className="page entry-layout">
      <Toolbar
        title={title}
        actions={
          <>
            <button className="btn" onClick={() => navigate("/sales")}>
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
                {createMutation.isPending ? "儲存中…" : "結帳"}
              </button>
            )}
            {!isNew && existing.data && (
              <>
                <button
                  className="btn"
                  type="button"
                  onClick={() =>
                    window.open(
                      `/sales/${existing.data!.id}/print/receipt`,
                      "_blank",
                    )
                  }
                >
                  列印收據
                </button>
                <button
                  className="btn"
                  type="button"
                  disabled={!existing.data.invoice_form}
                  title={
                    !existing.data.invoice_form
                      ? "未指定發票類型"
                      : "列印發票"
                  }
                  onClick={() =>
                    window.open(
                      `/sales/${existing.data!.id}/print/invoice`,
                      "_blank",
                    )
                  }
                >
                  列印發票
                </button>
              </>
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
            <Field label="客戶 (電話)">
              <div style={{ display: "flex", gap: 6 }}>
                <input
                  type="tel"
                  value={memberPhone}
                  onChange={(e) => {
                    setMemberPhone(e.target.value);
                    setMemberStatus("idle");
                    if (customer) setCustomer(null);
                  }}
                  onBlur={handleMemberLookup}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      handleMemberLookup();
                    }
                  }}
                  disabled={readonly}
                  style={{ flex: 1 }}
                />
                {memberStatus === "checking" && (
                  <span
                    className="member-tag"
                    style={{ color: "var(--text-dim)" }}
                  >
                    查詢中…
                  </span>
                )}
                {memberStatus === "found" && customer && (
                  <span className="member-tag" style={{ color: "#80d090" }}>
                    ✓ {customer.name} ({customer.kind_label}
                    {customer.is_member ? " / 會員" : ""})
                  </span>
                )}
                {memberStatus === "not_found" && !readonly && (
                  <button
                    type="button"
                    className="btn"
                    onClick={() => setShowCreateMember(true)}
                  >
                    未登錄,新增
                  </button>
                )}
              </div>
            </Field>
            <Field label="出貨倉" required>
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
            <Field label="業務員">
              <div style={{ display: "flex", gap: 6 }}>
                <div style={{ flex: 1 }}>
                  <ComboBox
                    value={salesPerson}
                    selectedOption={salesPersonOption}
                    onChange={(id, opt) => {
                      setSalesPerson(id);
                      setSalesPersonOption(opt ?? null);
                    }}
                    fetchOptions={searchSalesPersons}
                    disabled={readonly}
                    placeholder="搜尋業務員"
                  />
                </div>
                {!readonly && (
                  <button
                    type="button"
                    className="btn"
                    onClick={() => setShowCreateSalesPerson(true)}
                  >
                    +
                  </button>
                )}
              </div>
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
            {isTaxable ? (
              <Field label="統一編號">
                <input
                  value={buyerTaxId}
                  onChange={(e) => setBuyerTaxId(e.target.value)}
                  disabled={readonly}
                  maxLength={10}
                />
              </Field>
            ) : (
              <div />
            )}
          </div>
          <div className="field-row-3">
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
            <Field label="發票號碼(自動取號)">
              <input
                value={isNew ? previewInvoiceNo ?? "" : invoiceNo}
                disabled
                placeholder={
                  noInvoice
                    ? ""
                    : previewInvoiceNo
                    ? ""
                    : "尚無可用字軌,請至系統設定新增"
                }
              />
            </Field>
            <Field label="發票日期">
              <input
                type="date"
                value={invoiceDate}
                onChange={(e) => setInvoiceDate(e.target.value)}
                disabled={readonly || noInvoice || isNew}
              />
            </Field>
          </div>
          <div className="field-row">
            <Field label="備註">
              <input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                disabled={readonly}
              />
            </Field>
          </div>
        </div>

        {!readonly && (
          <div className="scan-bar">
            <input
              ref={scanRef}
              className="scan-input"
              value={scanCode}
              onChange={(e) => setScanCode(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  handleScan(scanCode);
                }
              }}
              placeholder={
                warehouse
                  ? "掃描商品條碼 / IMEI(掃完自動加入,可連續掃)"
                  : "請先選出貨倉,再用掃描槍掃碼"
              }
              disabled={scanning}
            />
            {scanMsg && (
              <span
                className="scan-msg"
                style={{ color: scanMsg.ok ? "#80d090" : "#ff7070" }}
              >
                {scanMsg.text}
              </span>
            )}
          </div>
        )}

        <table className="line-table">
          <thead>
            <tr>
              <th style={{ width: 40 }}>#</th>
              <th style={{ width: 240 }}>商品</th>
              <th style={{ width: 60 }} className="num">
                數量
              </th>
              <th style={{ width: 90 }} className="num">
                序號
              </th>
              <th style={{ width: 100 }} className="num">
                單價
              </th>
              <th style={{ width: 110 }} className="num">
                金額
              </th>
              <th style={{ width: 130 }}>門號</th>
              <th style={{ width: 140 }}>促銷方案</th>
              <th style={{ width: 140 }}>卡號</th>
              <th style={{ width: 90 }} className="num">
                佣金
              </th>
              <th style={{ width: 50 }}></th>
            </tr>
          </thead>
          <tbody>
            {lines.map((l, idx) => (
              <LineRow
                key={l.key}
                line={l}
                idx={idx}
                readonly={readonly}
                warehouseId={warehouse}
                update={(p) => updateLine(l.key, p)}
                remove={() => removeLine(l.key)}
                active={l.key === selectedLineKey}
                onSelect={() => setSelectedLineKey(l.key)}
              />
            ))}
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
       <SalesSerialAside
         line={lines.find((l) => l.key === selectedLineKey) ?? null}
         warehouseId={warehouse}
         readonly={readonly}
         containerRef={serialPanelRef}
         onPickSerial={(idx, opt) =>
           selectedLineKey &&
           updateSerialChoice(selectedLineKey, idx, opt)
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
          <span
            style={{
              color: estGrossMargin >= 0 ? "#80d090" : "#ff7070",
            }}
          >
            預估毛利<b>{Math.round(estGrossMargin).toLocaleString()}</b>
          </span>
        </div>
      </div>

      {showConfirm && (
        <CheckoutModal
          totalGross={Math.round(estTotal)}
          subtotal={Math.round(estSubtotal)}
          tax={Math.round(estTax)}
          itemsCount={lines.length}
          customerLabel={
            customer
              ? `${customer.phone} ${customer.name ?? ""}`
              : "(散客)"
          }
          methods={paymentMethods}
          amounts={payAmounts}
          notes={payNotes}
          onAmountChange={(code, v) =>
            setPayAmounts((s) => ({ ...s, [code]: v }))
          }
          onNoteChange={(code, v) =>
            setPayNotes((s) => ({ ...s, [code]: v }))
          }
          onCancel={() => setShowConfirm(false)}
          onConfirm={doSave}
          isPending={createMutation.isPending}
          savedSO={savedSO}
          onDone={() => {
            setSavedSO(null);
            setShowConfirm(false);
            navigate("/sales");
          }}
          onContinue={continueNewSale}
        />
      )}

      <Drawer
        open={showCreateMember}
        title={`新增客戶 (${memberPhone})`}
        onClose={() => setShowCreateMember(false)}
        width={420}
        footer={
          <>
            <button
              className="btn"
              type="button"
              onClick={() => setShowCreateMember(false)}
            >
              取消
            </button>
            <button
              className="btn primary"
              type="button"
              onClick={handleCreateMember}
              disabled={saveCustomer.isPending || !newMember.name.trim()}
            >
              {saveCustomer.isPending ? "儲存中…" : "建立並使用"}
            </button>
          </>
        }
      >
        <Field label="電話">
          <input value={memberPhone} disabled />
        </Field>
        <Field label="姓名 / 名稱" required>
          <input
            value={newMember.name}
            autoFocus
            onChange={(e) =>
              setNewMember((s) => ({ ...s, name: e.target.value }))
            }
          />
        </Field>
        <Field label="客戶類別">
          <select
            value={newMember.kind}
            onChange={(e) =>
              setNewMember((s) => ({
                ...s,
                kind: e.target.value as CustomerKind,
              }))
            }
          >
            {CUSTOMER_KINDS.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="統一編號">
          <input
            value={newMember.tax_id}
            onChange={(e) =>
              setNewMember((s) => ({ ...s, tax_id: e.target.value }))
            }
          />
        </Field>
        <Checkbox
          checked={newMember.is_member}
          onChange={(v) => setNewMember((s) => ({ ...s, is_member: v }))}
          label="設為會員"
        />
      </Drawer>

      <Drawer
        open={showCreateSalesPerson}
        title="新增業務員"
        onClose={() => setShowCreateSalesPerson(false)}
        width={420}
        footer={
          <>
            <button
              className="btn"
              type="button"
              onClick={() => setShowCreateSalesPerson(false)}
            >
              取消
            </button>
            <button
              className="btn primary"
              type="button"
              onClick={handleCreateSalesPerson}
              disabled={
                saveSalesPerson.isPending ||
                !newSalesPerson.code.trim() ||
                !newSalesPerson.name.trim()
              }
            >
              {saveSalesPerson.isPending ? "儲存中…" : "建立並使用"}
            </button>
          </>
        }
      >
        <Field label="業務員代號" required>
          <input
            value={newSalesPerson.code}
            autoFocus
            onChange={(e) =>
              setNewSalesPerson((s) => ({
                ...s,
                code: e.target.value.toUpperCase(),
              }))
            }
            maxLength={20}
          />
        </Field>
        <Field label="姓名" required>
          <input
            value={newSalesPerson.name}
            onChange={(e) =>
              setNewSalesPerson((s) => ({ ...s, name: e.target.value }))
            }
          />
        </Field>
      </Drawer>
    </div>
  );
}
