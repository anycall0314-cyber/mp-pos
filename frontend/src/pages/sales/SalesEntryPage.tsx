import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { ApiHttpError } from "@/api/client";
import {
  lookupMemberLastPrice,
  peekInvoiceNo,
  useCreateSalesOrder,
  useInvoiceTypes,
  usePaymentMethods,
  useSalesOrder,
  useSaveCustomer,
  useSaveMember,
  useVoidSalesOrder,
} from "@/api/hooks";
import {
  SalesProductHit,
  searchCustomers,
  searchInStockSerials,
  searchMembers,
  findDevicesByCode,
  searchProductsForSales,
  searchSalesPersons,
  searchSimCards,
  searchTelecomPlans,
  searchWarehouses,
} from "@/api/search";
import type {
  Customer,
  CustomerKind,
  Member,
  PaymentMethod,
  Product,
  ProductSerial,
  SalesOrder,
  SalesOrderPayment,
  SimCard,
  TaxMethod,
  TelecomPlan,
} from "@/api/types";
import {
  useDefaultHandledBy,
  useDefaultWarehouse,
} from "@/auth/AuthContext";
import { Banner } from "@/components/Banner";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { Drawer } from "@/components/Drawer";
import { Field } from "@/components/Field";
import { Toolbar } from "@/components/Toolbar";
import { codesLabel } from "@/lib/deviceCodes";
import { MoneyInput } from "@/components/MoneyInput";
import {
  intStr,
  lineTotal,
  money,
  roundInt,
  splitTax,
  splitUntaxedByLine,
} from "@/lib/money";

/** 把資料庫的 "100.00" / number 統一轉成整數字串(四捨五入,空 / NaN 還原成 "0")。 */
function toIntStr(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === "") return "0";
  const n = Number(v);
  if (!Number.isFinite(n)) return "0";
  return intStr(n);
}

/** 逐台定價:該台有核定售價就用它,回傳整數字串;否則 null(由呼叫端決定 fallback)。
 *
 * 閘門看 `tracks_unit_condition` 而不是 `is_secondhand` —— 已拆封機也會逐台
 * 記售價,只看中古機旗標會讓已拆封機存了 16000 卻仍帶商品定價 20000。
 * 舊商品沒有這個欄位時退回中古機旗標,行為不變。
 */
/** 這個商品是不是「逐台定價」(已拆封 / 中古)。舊資料退回中古機旗標。 */
function tracksUnitCondition(
  product: Pick<Product, "is_secondhand" | "tracks_unit_condition"> | undefined | null,
): boolean {
  if (!product) return false;
  return product.tracks_unit_condition ?? product.is_secondhand ?? false;
}

function unitCustomPrice(
  product: Pick<Product, "is_secondhand" | "tracks_unit_condition"> | undefined | null,
  serial: { custom_unit_price?: string | null } | undefined | null,
): string | null {
  if (!product || !serial) return null;
  if (!tracksUnitCondition(product)) return null;
  const cp = serial.custom_unit_price;
  if (cp === null || cp === undefined || !(Number(cp) > 0)) return null;
  return toIntStr(cp);
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
  // 續約預設不出卡號欄,客戶要換卡時店員按「+ 加卡號」展開;非續約方案此旗標被忽略
  card_override?: boolean;
  // 該會員上次買此商品的價格(不含贈品 0 元列);提醒用,不影響送單
  lastPriceHint?: {
    price: string;
    date: string;
    no: string;
  } | null;
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
    (s, m) => s + roundInt(amounts[m.code]),
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
          <div className="modal-title" style={{ color: "var(--success-text-soft)" }}>
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
              <b>{money(savedSO.total)}</b>
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
                      {money(p.amount)}
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
            <b>{money(subtotal)}</b>
          </div>
          <div className="modal-row">
            <span>稅額</span>
            <b>{money(tax)}</b>
          </div>
          <div className="modal-row big">
            <span>應收</span>
            <b>{money(totalGross)}</b>
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
                        ? "var(--success-text-soft)"
                        : m.kind === "transfer"
                        ? "#80b0d0"
                        : "var(--text-dim)",
                  }}
                >
                  {m.kind_label}
                </span>
              </label>
              <MoneyInput
                value={amounts[m.code] ?? "0"}
                autoFocus={i === 0}
                onChange={(v) => onAmountChange(m.code, v)}
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
            style={{ color: aligned ? "var(--success-text-soft)" : "var(--danger-text)" }}
          >
            {aligned
              ? `已對齊(共 ${money(paid)})`
              : diff > 0
              ? `尚需 ${money(diff)}`
              : `多收 ${money(Math.abs(diff))}`}
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

// 「新增客戶」dialog 限定的類別:不含個人(會員專用),避免誤把個人當作生意歸屬
const BUSINESS_KINDS: { value: CustomerKind; label: string }[] = [
  { value: "peer", label: "同業 / 盤商" },
  { value: "corporate", label: "企業" },
  { value: "other", label: "其他" },
];

const TAX_METHODS: { value: TaxMethod; label: string }[] = [
  { value: "taxable_included", label: "應稅內含" },
  { value: "taxable_excluded", label: "應稅外加" },
  { value: "untaxed", label: "未稅" },
];

/**
 * 這一行的金額。開單時一律 數量 × 單價(單價先收成整數元):金額格、頁尾試算、預設付款、送出的明細
 * 全部用這一個數字,不要各算各的(以前頁尾讀 `line.amount`、送出用 數量 × 單價,換商品或單價帶小數時兩邊會不一樣,
 * 預設付款對不上、單存不進去)。看已經存好的單(`saved`)用存下來的金額:舊單可能是折讓,不等於數量 × 單價。
 */
function lineAmount(line: Line, saved = false): number {
  return saved ? roundInt(line.amount) : lineTotal(line.qty, line.unit_price);
}

interface LineRowProps {
  line: Line;
  idx: number;
  readonly: boolean;
  warehouseId: number | "";
  memberId: number | null;
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
  memberId,
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
  // 逐台定價(已拆封 / 中古):一列一台。同列多台會用第一台的單價乘數量,
  // 兩台 16000 / 18000 只會收 32000。
  const perUnitPriced = tracksUnitCondition(product);

  function onProductPick(
    pid: number | "",
    opt?: ComboOption<SalesProductHit>,
  ) {
    const p = opt?.payload;
    // 選到商品時把建議零售價帶到單價,金額跟著重算
    // 打 / 掃 IMEI 命中時,優先帶該台的核定售價
    const msCustom = unitCustomPrice(p, p?.matched_serial);
    // 零件倉商品被選到:自動帶 external_sale_price(對外售價)
    const isPartsExternal =
      p?.warehouse_type === "parts" && p?.is_externally_sellable;
    const defaultPrice = toIntStr(
      isPartsExternal && Number(p?.external_sale_price ?? 0) > 0
        ? (p?.external_sale_price ?? "0")
        : (msCustom ?? p?.list_price ?? "0"),
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

    const pickedQty =
      autoSerial || tracksUnitCondition(p) ? 1 : line.qty;
    update({
      product: pid,
      productOption: opt ? { ...opt, payload: opt.payload as Product } : null,
      // 通常 IMEI 命中 = 賣 1 隻,把該行 qty 設 1、序號預填;否則清空待挑
      qty: pickedQty,
      serialChoices: autoSerial ? [autoSerial] : [],
      unit_price: p ? defaultPrice : line.unit_price,
      amount: p ? toIntStr(Number(defaultPrice) * pickedQty) : line.amount,
      msisdn: p?.allows_telecom_line ? line.msisdn : "",
      telecom_plan: p?.allows_telecom_line ? line.telecom_plan : "",
      telecomPlanOption: p?.allows_telecom_line ? line.telecomPlanOption : null,
      sim_card: p?.allows_telecom_line ? line.sim_card : "",
      simCardOption: p?.allows_telecom_line ? line.simCardOption : null,
      activation_date: p?.allows_telecom_line ? line.activation_date : "",
      commission: p?.allows_commission ? line.commission : "0",
      lastPriceHint: null,
    });

    // 路徑三:會員 + 商品都有 → 查該會員過往「真實成交價」(跳過 0 元贈品)
    if (p && pid !== "" && memberId) {
      lookupMemberLastPrice(memberId, pid as number)
        .then((last) => {
          if (!last) return;
          const hint = {
            price: toIntStr(last.unit_price),
            date: last.doc_date,
            no: last.sales_order_no,
          };
          // 逐台定價的商品:價格來自這一台的核定售價,不是同型號另一台的
          // 歷史成交價。這個查詢是非同步回來的,不擋住就會把剛帶好的
          // 單台售價蓋掉(也會跟「唯一在庫自動選機」互相競賽)。
          if (tracksUnitCondition(p)) {
            update({ lastPriceHint: hint });
            return;
          }
          update({
            unit_price: hint.price,
            amount: toIntStr(Number(hint.price) * pickedQty),
            lastPriceHint: hint,
          });
        })
        .catch(() => {
          // 失敗不影響主流程
        });
    }

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
          const cp = unitCustomPrice(p, only.payload);
          if (cp) {
            patch.unit_price = cp;
            patch.amount = cp;
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
      // 切到非續約方案 → 清掉 override(避免殘留誤判);續約方案保留店員之前的選擇
      card_override:
        newPlan?.kind === "renewal" ? line.card_override : false,
    });
  }

  // 卡號欄顯示條件:新辦/攜碼 一律顯示;續約預設不顯,店員按「+ 加卡號」才開
  const showCard =
    allowTelecom &&
    !!plan &&
    (requiresCard || (plan.kind === "renewal" && !!line.card_override));

  const showTelecomSub = allowTelecom || allowCommission;

  return (
    <>
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
          max={perUnitPriced ? 1 : undefined}
          value={line.qty}
          onChange={(e) => {
            const raw = Math.max(1, Number(e.target.value));
            const q = perUnitPriced ? 1 : raw;
            update({
              qty: q,
              amount: toIntStr(q * Number(line.unit_price || 0)),
            });
          }}
          disabled={readonly || perUnitPriced}
          title={perUnitPriced ? "一列一台" : undefined}
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
        <MoneyInput
          className="num-input"
          value={line.unit_price}
          onChange={(v) =>
            update({
              unit_price: v,
              amount: toIntStr(lineTotal(line.qty, v)),
            })
          }
          onBlur={(e) =>
            update({
              unit_price: toIntStr(e.target.value),
              amount: toIntStr(lineTotal(line.qty, e.target.value)),
            })
          }
          disabled={readonly}
        />
        {line.lastPriceHint && (
          <div
            style={{
              fontSize: 14,
              color: "var(--text-dim)",
              marginTop: 2,
              textAlign: "right",
            }}
            title={`前次成交價,來源單據 ${line.lastPriceHint.no}`}
          >
            前次 ${money(line.lastPriceHint.price)} ({line.lastPriceHint.date})
          </div>
        )}
      </td>
      <td>
        <input
          type="number"
          className="num-input"
          step="1"
          value={toIntStr(lineAmount(line, readonly))}
          disabled
          title="自動計算:數量 × 單價"
          readOnly
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
    {showTelecomSub && (
      <tr className="telecom-sub-row">
        <td></td>
        <td colSpan={6}>
          <div className="telecom-sub-grid">
            {allowTelecom && (
              <div className="telecom-sub-field">
                <input
                  value={line.msisdn}
                  onChange={(e) => update({ msisdn: e.target.value })}
                  disabled={readonly}
                  placeholder="門號 0912xxxxxx"
                />
              </div>
            )}
            {allowTelecom && (
              <div className="telecom-sub-field">
                <ComboBox<TelecomPlan>
                  value={line.telecom_plan}
                  selectedOption={line.telecomPlanOption}
                  onChange={onPlanPick}
                  fetchOptions={(q) =>
                    searchTelecomPlans(q, { activeOnly: true })
                  }
                  disabled={readonly}
                  placeholder="促銷方案"
                />
              </div>
            )}
            {showCard && (
              <div
                className="telecom-sub-field"
                style={{ display: "flex", gap: 4, alignItems: "center" }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
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
                    placeholder="卡號"
                  />
                </div>
                {plan?.kind === "renewal" && !readonly && (
                  <button
                    type="button"
                    onClick={() =>
                      update({
                        card_override: false,
                        sim_card: "",
                        simCardOption: null,
                      })
                    }
                    style={{
                      background: "transparent",
                      border: 0,
                      color: "var(--text-dim)",
                      cursor: "pointer",
                      padding: "0 4px",
                      fontSize: 16,
                      flexShrink: 0,
                    }}
                    title="續約不換卡,收起此欄"
                  >
                    ×
                  </button>
                )}
              </div>
            )}
            {allowTelecom &&
              plan?.kind === "renewal" &&
              !line.card_override &&
              !readonly && (
                <div className="telecom-sub-field">
                  <button
                    type="button"
                    className="btn"
                    onClick={() => update({ card_override: true })}
                    style={{ width: "100%" }}
                  >
                    + 加卡號
                  </button>
                </div>
              )}
            {allowCommission && (
              <div className="telecom-sub-field">
                <input
                  type="number"
                  className="num-input"
                  step="1"
                  value={line.commission}
                  disabled
                  placeholder="佣金"
                  title="佣金以方案設定為準,不可於銷貨時更改;請至「電信作業 → 電信方案」調整"
                />
              </div>
            )}
          </div>
        </td>
      </tr>
    )}
    </>
  );
}

const SALES_DRAFT_KEY = "sales-entry-draft";

interface SalesDraft {
  customer: Customer | null;
  customerOption: ComboOption<Customer> | null;
  member: Member | null;
  memberOption: ComboOption<Member> | null;
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
  const [searchParams] = useSearchParams();
  const focusMode = searchParams.get("focus") === "1";
  const isNew = id === "new";
  const soId = isNew ? null : Number(id);

  const defaultWarehouse = useDefaultWarehouse();
  const defaultHandledBy = useDefaultHandledBy();

  const existing = useSalesOrder(soId);
  const createMutation = useCreateSalesOrder();
  const voidMutation = useVoidSalesOrder();
  const saveCustomer = useSaveCustomer();
  const saveMember = useSaveMember();
  const invoiceTypesQuery = useInvoiceTypes({ activeOnly: true });
  const invoiceTypes = invoiceTypesQuery.data ?? [];
  const defaultInvoiceCode =
    invoiceTypes.find((t) => t.is_default)?.code ?? invoiceTypes[0]?.code ?? "";

  // 新單模式才啟用草稿;切到其他分頁回來不會掉
  const draft = useRef<SalesDraft | null>(
    isNew ? loadSalesDraft() : null,
  ).current;

  // 客戶(同行/直客/企業,用名稱搜):對應 SalesOrder.customer
  const [customer, setCustomer] = useState<Customer | null>(
    draft?.customer ?? null,
  );
  const [customerOption, setCustomerOption] =
    useState<ComboOption<Customer> | null>(draft?.customerOption ?? null);

  // 會員(獨立主檔,可掛在任何客戶底下消費):對應 SalesOrder.member;與 customer 不互斥
  const [member, setMember] = useState<Member | null>(draft?.member ?? null);
  const [memberOption, setMemberOption] =
    useState<ComboOption<Member> | null>(draft?.memberOption ?? null);
  const [showCreateMember, setShowCreateMember] = useState(false);
  const [newMember, setNewMember] = useState<{
    phone: string;
    name: string;
    national_id: string;
  }>({
    phone: "",
    name: "",
    national_id: "",
  });

  const [showCreateCustomer, setShowCreateCustomer] = useState(false);
  const [newCustomer, setNewCustomer] = useState<{
    name: string;
    kind: CustomerKind;
    tax_id: string;
    phone: string;
    note: string;
  }>({
    name: "",
    kind: "peer",
    tax_id: "",
    phone: "",
    note: "",
  });
  const [warehouse, setWarehouse] = useState<number | "">(
    draft?.warehouse ?? (isNew && defaultWarehouse.id ? defaultWarehouse.id : ""),
  );
  const [warehouseOption, setWarehouseOption] = useState<
    ComboOption<unknown> | null
  >(
    draft?.warehouseOption ??
      (isNew && defaultWarehouse.id
        ? {
            id: defaultWarehouse.id,
            label: defaultWarehouse.name,
            secondary: "",
          }
        : null),
  );
  // 單據日期永遠 = 今天,不開放更改(防竄改);舊單載入時會被 existing data 覆寫顯示原始日期
  const [docDate, setDocDate] = useState(
    () => new Date().toISOString().slice(0, 10),
  );
  const [taxMethod, setTaxMethod] = useState<TaxMethod>(
    draft?.taxMethod ?? "taxable_included",
  );
  const [buyerTaxId, setBuyerTaxId] = useState(draft?.buyerTaxId ?? "");
  const [invoiceForm, setInvoiceForm] = useState<string>(
    draft?.invoiceForm ?? "",
  );
  const [invoiceNo, setInvoiceNo] = useState(draft?.invoiceNo ?? "");
  // 發票日期一律 = 今天,不開放更改(防竄改);舊單載入時會被 existing data 覆寫顯示原始日期
  const [invoiceDate, setInvoiceDate] = useState(
    () => new Date().toISOString().slice(0, 10),
  );
  // 新單時:依發票類型 peek 下一張要開的號碼;送單時後端會原子地取走它
  const [previewInvoiceNo, setPreviewInvoiceNo] = useState<string | null>(null);
  const [salesPerson, setSalesPerson] = useState<number | "">(
    draft?.salesPerson ??
      (isNew && defaultHandledBy.id ? defaultHandledBy.id : ""),
  );
  const [salesPersonOption, setSalesPersonOption] = useState<
    ComboOption<unknown> | null
  >(
    draft?.salesPersonOption ??
      (isNew && defaultHandledBy.id
        ? {
            id: defaultHandledBy.id,
            label: defaultHandledBy.name,
            secondary: defaultHandledBy.code,
          }
        : null),
  );
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

  // 毛利隱藏:店員可一鍵遮蔽,避免螢幕面向客戶時毛利被看見。跨單據保留
  const [marginHidden, setMarginHidden] = useState<boolean>(() => {
    try {
      return localStorage.getItem("sales-margin-hidden") === "1";
    } catch {
      return false;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem("sales-margin-hidden", marginHidden ? "1" : "0");
    } catch {}
  }, [marginHidden]);

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
      if (defaultInvoiceCode === "none") setTaxMethod("untaxed");
    }
  }, [isNew, invoiceForm, defaultInvoiceCode]);

  const noInvoice = invoiceForm === "" || invoiceForm === "none";

  // 新單時把表單狀態 debounce 寫進 sessionStorage,跨分頁不掉
  useEffect(() => {
    if (!isNew) return;
    const snapshot: SalesDraft = {
      customer,
      customerOption,
      member,
      memberOption,
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
    customerOption,
    member,
    memberOption,
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
    setCustomerOption(null);
    setMember(null);
    setMemberOption(null);
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
    // 清:客戶 / 會員 / 明細 / 付款 / 發票號 / 買受人統編 / 備註
    setCustomer(null);
    setCustomerOption(null);
    setMember(null);
    setMemberOption(null);
    setLines([newLine(1)]);
    setSelectedLineKey(null);
    setPayAmounts({});
    setPayNotes({});
    setBuyerTaxId("");
    setInvoiceNo("");
    setInvoiceDate(new Date().toISOString().slice(0, 10));
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
        const c: Customer = {
          id: d.customer,
          code: "",
          phone: d.customer_phone ?? "",
          name: d.customer_name ?? "",
          kind: "individual",
          kind_label: d.customer_kind_label ?? "",
          tax_id: "",
          address: "",
          note: "",
          is_active: true,
        };
        setCustomer(c);
        setCustomerOption({
          id: c.id,
          label: c.name,
          secondary: c.kind_label,
          payload: c,
        });
      }
      if (d.member) {
        const m: Member = {
          id: d.member,
          code: "",
          phone: d.member_phone ?? "",
          name: d.member_name ?? "",
          national_id: "",
          birthday: null,
          address: "",
          note: "",
          is_active: true,
        };
        setMember(m);
        setMemberOption({
          id: m.id,
          label: m.name || m.phone || `#${m.id}`,
          secondary: m.phone,
          payload: m,
        });
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
          // 舊單若是續約 + 有卡號(換卡特例),把 card_override 開上,UI 才會顯示卡號欄
          card_override:
            it.telecom_plan_kind === "renewal" && !!it.sim_card,
        })),
      );
    }
  }, [existing.data, isNew]);

  async function handleCreateMember() {
    const phone = newMember.phone.trim();
    const name = newMember.name.trim();
    if (!name) {
      setError("姓名必填");
      return;
    }
    try {
      const created = await saveMember.mutateAsync({
        phone,
        name,
        national_id: newMember.national_id || undefined,
      });
      setMember(created);
      setMemberOption({
        id: created.id,
        label: created.name || created.phone || `#${created.id}`,
        secondary: created.phone,
        payload: created,
      });
      setShowCreateMember(false);
      setNewMember({
        phone: "",
        name: "",
        national_id: "",
      });
    } catch (e) {
      if (e instanceof ApiHttpError) {
        const body = e.body;
        setError(`新增會員失敗:${JSON.stringify(body)}`);
      }
    }
  }

  async function handleCreateCustomer() {
    const name = newCustomer.name.trim();
    if (!name) return;
    try {
      const created = await saveCustomer.mutateAsync({
        name,
        kind: newCustomer.kind,
        tax_id: newCustomer.tax_id.trim() || undefined,
        phone: newCustomer.phone.trim() || undefined,
        note: newCustomer.note.trim() || undefined,
      });
      setCustomer(created);
      setCustomerOption({
        id: created.id,
        label: created.name || `#${created.id}`,
        secondary: [created.kind_label, created.tax_id || null]
          .filter(Boolean)
          .join(" / "),
        payload: created,
      });
      if (isTaxable && created.tax_id && !buyerTaxId) {
        setBuyerTaxId(created.tax_id);
      }
      setShowCreateCustomer(false);
      setNewCustomer({
        name: "",
        kind: "peer",
        tax_id: "",
        phone: "",
        note: "",
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
        // 優先用該台的核定售價
        const serialPrice = unitCustomPrice(p, ms) ?? price;
        // 逐台定價的商品一台一列。合併成一列會讓第二台沿用第一台的單價
        // (兩台 16000 / 18000 連掃會收成 32000,少收 2000)。
        const perUnitPriced = tracksUnitCondition(p);
        if (existingIdx >= 0 && !perUnitPriced) {
          return ls.map((l, i) =>
            i === existingIdx
              ? {
                  ...l,
                  qty: l.qty + 1,
                  serialChoices: [...l.serialChoices, opt],
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
      // 先看刷到的是不是某一台設備(IMEI 或 SN 完全相同):
      // - 對到兩台以上(舊資料的碼撞在一起):不知道是哪一台,不能隨便加一台。
      // - 那一台不在這個出貨倉、或不是在庫:講出它在哪,不要加一行空的讓人挑同款的別台。
      const devices = await findDevicesByCode(code);
      if (devices.length > 1) {
        setScanMsg({
          ok: false,
          text: `${code} 對到 ${devices.length} 台設備,請先到每日對帳處理`,
        });
        return;
      }
      const device = devices[0];
      if (
        device &&
        (device.status !== "in_stock" || device.warehouse !== warehouse)
      ) {
        setScanMsg({
          ok: false,
          text: `這一台${device.status_label}${
            device.warehouse_code ? `,在 ${device.warehouse_code}` : ""
          },不能在這裡賣`,
        });
        return;
      }
      const results = await searchProductsForSales(code, {
        warehouseId: warehouse,
      });
      // 刷到的是某一台設備,就只能加那一台。它的商品不在可銷貨的清單裡(已停用…)時直接講,
      // 不能退回去用條碼 / 品號 / 第一筆加進別的商品。
      if (
        device &&
        !results.some((r) => r.payload?.matched_serial?.id === device.id)
      ) {
        setScanMsg({
          ok: false,
          text: `這一台的商品目前不能銷貨:${device.product_name}`,
        });
        return;
      }
      if (results.length === 0) {
        setScanMsg({ ok: false, text: `查無:${code}` });
        return;
      }
      // 優先:刷到的就是某一台設備的碼(IMEI 或 SN 完全相同)→ 條碼 / 品號完全命中 → 第一筆。
      // 設備的碼排在商品條碼前面:刷到 SN 時不能因為別的商品品號剛好一樣就加錯商品。
      const best =
        results.find((r) => r.payload?.matched_serial?.exact) ??
        results.find(
          (r) => r.payload?.barcode === code || r.payload?.sku === code,
        ) ??
        results[0];
      // 刷條碼只在「碼完全相同」時自動掛序號。只對到一部分的(下拉裡打末幾碼用的)不算:
      // 刷到的整個碼不等於任何一台,卻剛好被某一台的碼包含,掛上去就是賣錯實機。
      const hit = best.payload as SalesProductHit;
      const p: SalesProductHit = hit.matched_serial?.exact
        ? hit
        : { ...hit, matched_serial: undefined };
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
          text: `已加入 ${p.name} · ${codesLabel(p.matched_serial)}`,
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
        // 挑到序號就把該台的核定售價帶入單價(只在第 0 格觸發,避免亂蓋)
        const product = l.productOption?.payload;
        if (idx === 0 && option) {
          const cp = unitCustomPrice(product, option.payload);
          if (cp) {
            patch.unit_price = cp;
            patch.amount = toIntStr(Number(cp) * l.qty);
          }
        }
        return { ...l, ...patch };
      }),
    );
  }

  // 試算跟伺服器存檔用同一套算法(整數元、四捨五入)
  // 看已經存好的單:直接顯示存下來的小計 / 稅額 / 總額,不重算(舊單是用以前的算法存的,重算會差幾元)
  const savedDoc = readonly ? existing.data : undefined;
  const [estSubtotal, estTax, estTotal] = savedDoc
    ? [savedDoc.subtotal, savedDoc.tax_amount, savedDoc.total].map(roundInt)
    : splitTax(lines.map((l) => lineAmount(l)), taxMethod);

  // 預估毛利 = 計毛利那幾行的(未稅金額 − 平均成本 × 數量 + 佣金)。
  // 成本與佣金都是 0、每一行都計毛利時,毛利就等於未稅小計(以前成本沒乘數量,賣 2 支只扣 1 支的成本)。
  // 看已經存好的單:用存檔當下記在每一行的未稅金額、成本、佣金(不計毛利的商品不算),
  // 不拿現在的平均成本重算(載進來的商品沒有帶成本,重算會把成本當成 0)。
  const estGrossMargin = savedDoc
    ? savedDoc.items.reduce(
        (sum, it) =>
          it.product_counts_margin === false
            ? sum
            : sum +
              Number(it.untaxed_amount || 0) -
              Number(it.cost_at_post || 0) +
              Number(it.commission || 0),
        0,
      )
    : (() => {
        // 開單中:每一行的未稅金額跟存檔時分到每行的算法一樣;不計毛利的商品(例:收購二手)整行不算,
        // 存檔前後看到的毛利才會是同一個數字
        const untaxed = splitUntaxedByLine(
          lines.map((l) => lineAmount(l)),
          taxMethod,
        );
        return lines.reduce((sum, l, i) => {
          const p = l.productOption?.payload;
          if (!p || p.counts_margin === false) return sum;
          const lineCost = p.is_virtual
            ? 0
            : (Number(p.weighted_avg_cost) || 0) * l.qty;
          return sum + untaxed[i] - lineCost + roundInt(l.commission);
        }, 0);
      })();

  function validate(): string | null {
    if (!warehouse) return "請選出貨倉";
    if (!customer) return "請選客戶";
    if (!salesPerson) return "請選業務員";
    if (!invoiceForm) return "請選發票類型";
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
    const total = roundInt(estTotal);
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
    const target = roundInt(estTotal);
    const paid = Object.values(payAmounts).reduce(
      (s, v) => s + roundInt(v),
      0,
    );
    if (paid !== target) {
      setError(`付款金額 ${paid} 與含稅總額 ${target} 不一致`);
      return;
    }
    const payments: Array<{ method: string; amount: string; note?: string }> = [];
    for (const m of paymentMethods) {
      const amt = roundInt(payAmounts[m.code]);
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
        member: member ? member.id : null,
        warehouse: warehouse as number,
        doc_date: docDate,
        tax_method: taxMethod,
        buyer_tax_id: isTaxable ? buyerTaxId : "",
        invoice_form: invoiceForm,
        invoice_no: invoiceNo,
        invoice_date: noInvoice ? null : invoiceDate,
        sales_person: salesPerson === "" ? null : (salesPerson as number),
        note,
        items: lines.map((l, idx) => ({
          line_no: idx + 1,
          product: l.product as number,
          qty: l.qty,
          unit_price: toIntStr(l.unit_price),
          amount: toIntStr(lineAmount(l)),
          serial_ids: pickedSerialIds(l),
          msisdn: l.msisdn,
          telecom_plan:
            l.telecom_plan === "" ? null : (l.telecom_plan as number),
          sim_card: l.sim_card === "" ? null : (l.sim_card as number),
          // 上線日預設 = 單據日期;之後會有獨立分頁修改實際上線時間
          activation_date:
            l.activation_date ||
            (l.telecom_plan !== "" ? docDate : null),
          commission: toIntStr(l.commission),
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
          focusMode ? null : (
          <>
            <button className="btn" onClick={() => navigate("/sales")}>
              回列表
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
          )
        }
      />

      <div className="entry-body-split">
       <div className="entry-body">
        {error && <Banner kind="error" message={error} />}

        <div className="entry-header" style={{ marginBottom: 8 }}>
          <div className="sales-header-grid">
            <div style={{ gridArea: "wh" }} className="medium-field">
              <Field label="出貨倉" required>
                {defaultWarehouse.locked && isNew ? (
                  <input
                    value={defaultWarehouse.name || "(未設定)"}
                    disabled
                    title="此帳號鎖定於此門市"
                  />
                ) : (
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
                )}
              </Field>
            </div>
            <div style={{ gridArea: "date" }} className="short-field">
              <Field label="單據日期" required>
                <input
                  type="date"
                  value={docDate}
                  disabled
                  title="單據日期一律以系統當天為準,不可更改"
                />
              </Field>
            </div>
            <div style={{ gridArea: "invdate" }} className="short-field">
              <Field label="發票日期" required={!noInvoice}>
                <input
                  type="date"
                  value={invoiceDate}
                  disabled
                  title="發票日期一律以系統當天為準,不可更改"
                />
              </Field>
            </div>
            <div style={{ gridArea: "customer" }} className="medium-field">
              <Field label="客戶" required>
                <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <ComboBox<Customer>
                      value={customer?.id ?? ""}
                      selectedOption={customerOption}
                      onChange={(_id, opt) => {
                        setCustomerOption(opt ?? null);
                        const c = opt?.payload ?? null;
                        setCustomer(c);
                        if (isTaxable && c?.tax_id && !buyerTaxId) {
                          setBuyerTaxId(c.tax_id);
                        }
                      }}
                      fetchOptions={searchCustomers}
                      placeholder="搜尋名稱 / 電話 / 統編"
                      disabled={readonly}
                    />
                  </div>
                  {!readonly && (
                    <button
                      type="button"
                      className="btn"
                      onClick={() => setShowCreateCustomer(true)}
                      style={{ flexShrink: 0 }}
                    >
                      + 新增
                    </button>
                  )}
                </div>
              </Field>
            </div>

            <div style={{ gridArea: "tax" }} className="short-field">
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
              {isTaxable && (
                <Field label="買方統編">
                  <input
                    value={buyerTaxId}
                    onChange={(e) => setBuyerTaxId(e.target.value)}
                    disabled={readonly}
                    maxLength={10}
                    placeholder="選填,選客戶/會員時自動帶入"
                  />
                </Field>
              )}
            </div>
            <div style={{ gridArea: "invtype" }} className="short-field">
              <Field label="發票類型" required>
                <select
                  value={invoiceForm}
                  onChange={(e) => {
                    const v = e.target.value;
                    setInvoiceForm(v);
                    // 免用統一發票 → 課稅別連動到未稅
                    if (v === "none") setTaxMethod("untaxed");
                    // 電子發票 → 課稅別預設應稅內含
                    else if (v === "e_invoice") setTaxMethod("taxable_included");
                  }}
                  disabled={readonly}
                >
                  {!invoiceForm && <option value="">— 請選 —</option>}
                  {invoiceTypes.map((f) => (
                    <option key={f.code} value={f.code}>
                      {f.name}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <div style={{ gridArea: "member" }} className="medium-field">
              <Field label="會員">
                <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <ComboBox<Member>
                      value={member?.id ?? ""}
                      selectedOption={memberOption}
                      onChange={(_id, opt) => {
                        setMemberOption(opt ?? null);
                        const m = opt?.payload ?? null;
                        setMember(m);
                      }}
                      fetchOptions={searchMembers}
                      placeholder="搜尋電話 / 姓名 / 身分證,查無按 Enter 新增"
                      disabled={readonly}
                      onCreateNew={(q) => {
                        const isPhone = /^[\d-]+$/.test(q);
                        setNewMember({
                          phone: isPhone ? q : "",
                          name: isPhone ? "" : q,
                          national_id: "",
                        });
                        setShowCreateMember(true);
                      }}
                      createNewLabel="+ 新增會員"
                    />
                  </div>
                </div>
              </Field>
            </div>

            <div style={{ gridArea: "invno" }} className="short-field">
              <Field label="發票號碼(自動取號)" required={!noInvoice}>
                <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
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
                  {existing.data?.invoice_voided && (
                    <span
                      style={{
                        padding: "2px 6px",
                        background: "var(--danger, #c33)",
                        color: "white",
                        borderRadius: 3,
                        fontSize: 14,
                        whiteSpace: "nowrap",
                      }}
                      title="此銷貨單已有銷退,原發票已標作廢"
                    >
                      已作廢
                    </span>
                  )}
                </div>
              </Field>
            </div>
            <div style={{ gridArea: "note" }}>
              <Field label="備註">
                <input
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  disabled={readonly}
                />
              </Field>
            </div>
            <div style={{ gridArea: "salesperson" }} className="medium-field">
              <Field label="業務員" required>
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
              </Field>
            </div>
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
                style={{ color: scanMsg.ok ? "var(--success-text-soft)" : "var(--danger-text)" }}
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
              <th style={{ width: 84 }} className="num">
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
                memberId={member?.id ?? null}
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
       {(() => {
         const sel = lines.find((l) => l.key === selectedLineKey);
         const p = sel?.productOption?.payload;
         if (!p?.requires_serial || p.is_virtual) return null;
         return (
           <SalesSerialAside
             line={sel ?? null}
             warehouseId={warehouse}
             readonly={readonly}
             containerRef={serialPanelRef}
             onPickSerial={(idx, opt) =>
               selectedLineKey &&
               updateSerialChoice(selectedLineKey, idx, opt)
             }
           />
         );
       })()}
      </div>

      <div className="entry-footer">
        <div className="entry-summary">
          <span>
            未稅小計<b>{money(estSubtotal)}</b>
          </span>
          <span>
            稅額<b>{money(estTax)}</b>
          </span>
          <span className="grand">
            含稅總額<b>{money(estTotal)}</b>
          </span>
          <span
            style={{
              color: marginHidden
                ? "var(--text-dim)"
                : estGrossMargin >= 0
                ? "var(--success-text-soft)"
                : "var(--danger-text)",
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            預估毛利
            <b>
              {marginHidden
                ? "•••"
                : money(estGrossMargin)}
            </b>
            <button
              type="button"
              onClick={() => setMarginHidden((v) => !v)}
              title={
                marginHidden
                  ? "顯示毛利"
                  : "隱藏毛利(避免客戶從螢幕看到)"
              }
              style={{
                background: "transparent",
                border: 0,
                color: "inherit",
                cursor: "pointer",
                padding: 0,
                marginLeft: 2,
                display: "inline-flex",
                alignItems: "center",
              }}
              aria-label={marginHidden ? "顯示毛利" : "隱藏毛利"}
            >
              {marginHidden ? (
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
                  <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
                  <path d="M14.12 14.12a3 3 0 1 1-4.24-4.24" />
                  <line x1="1" y1="1" x2="23" y2="23" />
                </svg>
              ) : (
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                  <circle cx="12" cy="12" r="3" />
                </svg>
              )}
            </button>
          </span>
        </div>
        {isNew && (
          <button
            type="button"
            className="btn primary checkout-cta"
            onClick={openConfirm}
            disabled={createMutation.isPending}
          >
            {createMutation.isPending ? "儲存中…" : "確認結帳"}
          </button>
        )}
      </div>

      {showConfirm && (
        <CheckoutModal
          totalGross={roundInt(estTotal)}
          subtotal={roundInt(estSubtotal)}
          tax={roundInt(estTax)}
          itemsCount={lines.length}
          customerLabel={
            customer || member
              ? [
                  customer ? `客戶: ${customer.name}` : null,
                  member ? `會員: ${member.name}` : null,
                ]
                  .filter(Boolean)
                  .join(" / ")
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
        title="新增會員"
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
              disabled={saveMember.isPending || !newMember.name.trim()}
            >
              {saveMember.isPending ? "儲存中…" : "建立並使用"}
            </button>
          </>
        }
      >
        <Field label="姓名" required>
          <input
            value={newMember.name}
            autoFocus
            onChange={(e) =>
              setNewMember((s) => ({ ...s, name: e.target.value }))
            }
            maxLength={120}
          />
        </Field>
        <Field label="電話">
          <input
            value={newMember.phone}
            onChange={(e) =>
              setNewMember((s) => ({ ...s, phone: e.target.value }))
            }
            maxLength={40}
          />
        </Field>
        <Field label="身分證字號">
          <input
            value={newMember.national_id}
            onChange={(e) =>
              setNewMember((s) => ({ ...s, national_id: e.target.value }))
            }
            maxLength={20}
          />
        </Field>
      </Drawer>

      <Drawer
        open={showCreateCustomer}
        title="新增客戶 (同行 / 企業)"
        onClose={() => setShowCreateCustomer(false)}
        width={420}
        footer={
          <>
            <button
              className="btn"
              type="button"
              onClick={() => setShowCreateCustomer(false)}
            >
              取消
            </button>
            <button
              className="btn primary"
              type="button"
              onClick={handleCreateCustomer}
              disabled={saveCustomer.isPending || !newCustomer.name.trim()}
            >
              {saveCustomer.isPending ? "儲存中…" : "建立並使用"}
            </button>
          </>
        }
      >
        <Field label="名稱" required>
          <input
            value={newCustomer.name}
            autoFocus
            onChange={(e) =>
              setNewCustomer((s) => ({ ...s, name: e.target.value }))
            }
            maxLength={120}
            placeholder="例:中華電信 / 通訊宅配 / 陳通路"
          />
        </Field>
        <Field label="客戶類別">
          <select
            value={newCustomer.kind}
            onChange={(e) =>
              setNewCustomer((s) => ({
                ...s,
                kind: e.target.value as CustomerKind,
              }))
            }
          >
            {BUSINESS_KINDS.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="統一編號">
          <input
            value={newCustomer.tax_id}
            onChange={(e) =>
              setNewCustomer((s) => ({ ...s, tax_id: e.target.value }))
            }
            maxLength={20}
            placeholder="企業/同行建議填,開發票自動帶入"
          />
        </Field>
        <Field label="電話">
          <input
            value={newCustomer.phone}
            onChange={(e) =>
              setNewCustomer((s) => ({ ...s, phone: e.target.value }))
            }
            maxLength={40}
            placeholder="選填"
          />
        </Field>
        <Field label="備註">
          <input
            value={newCustomer.note}
            onChange={(e) =>
              setNewCustomer((s) => ({ ...s, note: e.target.value }))
            }
            maxLength={200}
          />
        </Field>
      </Drawer>
    </div>
  );
}
