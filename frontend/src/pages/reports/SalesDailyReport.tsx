import { useMemo, useState } from "react";

import { useSalesDailyReport } from "@/api/hooks";
import { searchCustomers, searchSalesPersons, searchWarehouses } from "@/api/search";
import { useDefaultWarehouse } from "@/auth/AuthContext";
import type {
  Customer,
  SalesOrder,
  SalesOrderItem,
  SalesPerson,
  Warehouse,
} from "@/api/types";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { Toolbar } from "@/components/Toolbar";
import { useIsMobile } from "@/hooks/useIsMobile";

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

/**
 * 金額(含稅)→ 未稅。
 * taxable_included:除 1.05
 * 其他(taxable_excluded / untaxed / 以及舊資料 tax_free / zero_tax):amount 已是未稅
 */
function itemUntaxedAmount(it: SalesOrderItem, taxMethod: string): number {
  const amount = Number(it.amount);
  if (taxMethod === "taxable_included") return amount / 1.05;
  return amount;
}

/**
 * 是否該項目計入毛利。
 * 收購二手等 counts_margin=false 的虛擬商品不計毛利(只計現金支出)
 */
function itemCountsMargin(it: SalesOrderItem): boolean {
  return it.product_counts_margin !== false;
}

function itemGrossProfit(it: SalesOrderItem, taxMethod: string): number {
  if (!itemCountsMargin(it)) return 0;
  return itemUntaxedAmount(it, taxMethod) - Number(it.cost_at_post);
}

function fmtMoney(v: number): string {
  return Math.round(v).toLocaleString();
}

function serialList(it: SalesOrderItem): string {
  if (!it.serials || it.serials.length === 0) return "";
  return it.serials.map((s) => s.serial_no).join(" / ");
}

interface AppliedFilter {
  from: string;
  to: string;
  warehouse: number | "";
  sales_person: number | "";
  customer: number | "";
}

export function SalesDailyReportPage() {
  const defaultWarehouse = useDefaultWarehouse();
  const isMobile = useIsMobile();
  // 表單狀態
  const [from, setFrom] = useState<string>(today);
  const [to, setTo] = useState<string>(today);
  const [warehouse, setWarehouse] = useState<number | "">(
    defaultWarehouse.locked && defaultWarehouse.id ? defaultWarehouse.id : "",
  );
  const [warehouseOpt, setWarehouseOpt] = useState<ComboOption<Warehouse> | null>(
    defaultWarehouse.locked && defaultWarehouse.id
      ? {
          id: defaultWarehouse.id,
          label: defaultWarehouse.name,
          secondary: "",
        }
      : null,
  );
  const [salesPerson, setSalesPerson] = useState<number | "">("");
  const [salesPersonOpt, setSalesPersonOpt] = useState<ComboOption<SalesPerson> | null>(
    null,
  );
  const [customer, setCustomer] = useState<number | "">("");
  const [customerOpt, setCustomerOpt] = useState<ComboOption<Customer> | null>(null);

  // 已套用 — 按「查詢」才打 API
  const [applied, setApplied] = useState<AppliedFilter>(() => ({
    from: today(),
    to: today(),
    warehouse: "",
    sales_person: "",
    customer: "",
  }));

  const { data, isLoading, isError, error } = useSalesDailyReport({
    from: applied.from,
    to: applied.to,
    warehouse: applied.warehouse === "" ? undefined : applied.warehouse,
    sales_person: applied.sales_person === "" ? undefined : applied.sales_person,
    customer: applied.customer === "" ? undefined : applied.customer,
  });

  const orders = data ?? [];

  // 分組:正常單 + 作廢單(顯示在底部)
  const { activeOrders, voidOrders } = useMemo(() => {
    const active: SalesOrder[] = [];
    const voided: SalesOrder[] = [];
    for (const o of orders) {
      if (o.is_void) voided.push(o);
      else active.push(o);
    }
    return { activeOrders: active, voidOrders: voided };
  }, [orders]);

  // 統計合計(只算正常單;毛利 / 成本只算 counts_margin=true 的項目)
  const totals = useMemo(() => {
    let lines = 0;
    let amountIncl = 0;
    let cost = 0;
    let profit = 0;
    for (const o of activeOrders) {
      for (const it of o.items) {
        lines += 1;
        amountIncl += Number(it.amount);
        if (itemCountsMargin(it)) {
          cost += Number(it.cost_at_post);
          profit += itemGrossProfit(it, o.tax_method);
        }
      }
    }
    return { lines, amountIncl, cost, profit };
  }, [activeOrders]);

  function runQuery() {
    setApplied({
      from,
      to,
      warehouse,
      sales_person: salesPerson,
      customer,
    });
  }

  function resetFilters() {
    const t = today();
    setFrom(t);
    setTo(t);
    setWarehouse("");
    setWarehouseOpt(null);
    setSalesPerson("");
    setSalesPersonOpt(null);
    setCustomer("");
    setCustomerOpt(null);
    setApplied({ from: t, to: t, warehouse: "", sales_person: "", customer: "" });
  }

  function exportCsv() {
    const headers = [
      "日期",
      "單號",
      "出貨倉",
      "業務員",
      "客戶",
      "商品",
      "序號",
      "數量",
      "單價",
      "金額",
      "成本",
      "毛利",
      "業務員毛利",
      "作廢",
    ];
    const rows: string[][] = [];
    const writeOrder = (o: SalesOrder, voidFlag: boolean) => {
      for (const it of o.items) {
        const countsMargin = itemCountsMargin(it);
        rows.push([
          o.doc_date,
          o.no,
          `${o.warehouse_code ?? ""} ${o.warehouse_name ?? ""}`.trim(),
          o.sales_person_name ?? "",
          o.customer_name ?? "散客",
          it.product_name,
          serialList(it),
          String(it.qty),
          String(Math.round(Number(it.unit_price))),
          String(Math.round(Number(it.amount))),
          countsMargin ? String(Math.round(Number(it.cost_at_post))) : "",
          countsMargin
            ? String(Math.round(itemGrossProfit(it, o.tax_method)))
            : "",
          "",
          voidFlag ? "Y" : "",
        ]);
      }
    };
    for (const o of activeOrders) writeOrder(o, false);
    for (const o of voidOrders) writeOrder(o, true);

    const csv = [headers, ...rows]
      .map((r) =>
        r
          .map((c) => {
            const s = String(c ?? "");
            return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
          })
          .join(","),
      )
      .join("\r\n");

    // BOM 讓 Excel 開繁中不亂碼
    const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `銷貨日報_${applied.from}_${applied.to}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  return (
    <div className="page">
      <Toolbar title="銷貨日報" />
      <div className="list-filterbar sd-filter">
        <div className="sd-filter-group sd-filter-dates">
          <label className="sd-field">
            起日
            <input
              type="date"
              value={from}
              onChange={(e) => setFrom(e.target.value)}
            />
          </label>
          <label className="sd-field">
            迄日
            <input
              type="date"
              value={to}
              onChange={(e) => setTo(e.target.value)}
            />
          </label>
        </div>

        <div className="sd-filter-group sd-filter-quick">
          <button
            className="btn"
            type="button"
            onClick={() => {
              const t = today();
              setFrom(t);
              setTo(t);
            }}
          >
            今天
          </button>
          <button
            className="btn"
            type="button"
            onClick={() => {
              const t = today();
              const d = new Date();
              d.setDate(d.getDate() - 6);
              setFrom(d.toISOString().slice(0, 10));
              setTo(t);
            }}
          >
            近 7 天
          </button>
          <button
            className="btn"
            type="button"
            onClick={() => {
              const t = today();
              const d = new Date();
              d.setDate(1);
              setFrom(d.toISOString().slice(0, 10));
              setTo(t);
            }}
          >
            本月
          </button>
        </div>

        <div className="sd-filter-group sd-filter-people">
          <label className="sd-field">
            倉別
            {defaultWarehouse.locked ? (
              <input
                value={defaultWarehouse.name || "(未設定)"}
                disabled
                title="此帳號鎖定於此門市"
              />
            ) : (
              <ComboBox<Warehouse>
                value={warehouse}
                selectedOption={warehouseOpt}
                onChange={(id, opt) => {
                  setWarehouse(id);
                  setWarehouseOpt(opt ?? null);
                }}
                fetchOptions={searchWarehouses}
                placeholder="全部"
              />
            )}
          </label>
          <label className="sd-field">
            業務員
            <ComboBox<SalesPerson>
              value={salesPerson}
              selectedOption={salesPersonOpt}
              onChange={(id, opt) => {
                setSalesPerson(id);
                setSalesPersonOpt(opt ?? null);
              }}
              fetchOptions={searchSalesPersons}
              placeholder="全部"
            />
          </label>
          <label className="sd-field">
            客戶
            <ComboBox<Customer>
              value={customer}
              selectedOption={customerOpt}
              onChange={(id, opt) => {
                setCustomer(id);
                setCustomerOpt(opt ?? null);
              }}
              fetchOptions={searchCustomers}
              placeholder="全部"
            />
          </label>
        </div>

        <div className="sd-filter-group sd-filter-actions">
          <button type="button" className="btn primary" onClick={runQuery}>
            查詢
          </button>
          <button type="button" className="btn" onClick={resetFilters}>
            清除
          </button>
          <button
            type="button"
            className="btn"
            onClick={exportCsv}
            disabled={orders.length === 0}
          >
            轉 Excel
          </button>
        </div>
      </div>

      <div className="sd-summary">
        <div className="sd-summary-card">
          <div className="sd-summary-card-label">正常單</div>
          <div className="sd-summary-card-value">{activeOrders.length}</div>
        </div>
        <div className="sd-summary-card">
          <div className="sd-summary-card-label">明細</div>
          <div className="sd-summary-card-value">{totals.lines}</div>
        </div>
        <div className="sd-summary-card">
          <div className="sd-summary-card-label">含稅金額</div>
          <div className="sd-summary-card-value">
            ${fmtMoney(totals.amountIncl)}
          </div>
        </div>
        <div className="sd-summary-card">
          <div className="sd-summary-card-label">成本</div>
          <div className="sd-summary-card-value">${fmtMoney(totals.cost)}</div>
        </div>
        <div className="sd-summary-card">
          <div className="sd-summary-card-label">毛利</div>
          <div
            className="sd-summary-card-value"
            style={{ color: totals.profit < 0 ? "#ff7070" : undefined }}
          >
            ${fmtMoney(totals.profit)}
          </div>
        </div>
        {voidOrders.length > 0 && (
          <div className="sd-summary-card sd-summary-card-void">
            <div className="sd-summary-card-label">作廢</div>
            <div className="sd-summary-card-value">
              {voidOrders.length} 筆
            </div>
          </div>
        )}
      </div>
      <div className="sd-summary-hint">毛利以未稅金額減成本計算</div>

      <div className="report-table">
        {isLoading && <div className="md-empty">載入中…</div>}
        {isError && <div className="md-empty">{String(error)}</div>}
        {!isLoading && !isError && (
          <>
            {isMobile ? (
              <SalesReportMobileList orders={activeOrders} voided={false} />
            ) : (
              <SalesReportTable orders={activeOrders} voided={false} />
            )}
            {voidOrders.length > 0 && (
              <>
                <div className="report-void-header">作廢單據</div>
                {isMobile ? (
                  <SalesReportMobileList orders={voidOrders} voided={true} />
                ) : (
                  <SalesReportTable orders={voidOrders} voided={true} />
                )}
              </>
            )}
            {orders.length === 0 && (
              <div className="md-empty">查無資料</div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function SalesReportMobileList({ orders, voided }: ReportTableProps) {
  if (orders.length === 0) return null;
  return (
    <div className="report-mobile-list">
      {orders.map((o) => {
        const hasMarginItem = o.items.some(itemCountsMargin);
        const orderProfit = o.items.reduce(
          (s, it) => s + itemGrossProfit(it, o.tax_method),
          0,
        );
        const orderAmount = o.items.reduce(
          (s, it) => s + Number(it.amount),
          0,
        );
        return (
          <div
            key={o.id}
            className={`report-card ${voided ? "void" : ""}`}
          >
            <div className="report-card-head">
              <div className="report-card-no">{o.no}</div>
              <div className="report-card-date">{o.doc_date}</div>
            </div>
            <div className="report-card-customer">
              {o.customer_name ?? "散客"}
              {voided && <span className="report-card-badge">作廢</span>}
            </div>
            <div className="report-card-meta">
              {`${o.warehouse_code ?? ""} ${o.warehouse_name ?? ""}`.trim() || "—"}
              {o.sales_person_name && (
                <>
                  <span className="report-card-sep">·</span>
                  {o.sales_person_name}
                </>
              )}
            </div>

            <div className="report-card-items">
              {o.items.map((it) => {
                const countsMargin = itemCountsMargin(it);
                const profit = itemGrossProfit(it, o.tax_method);
                const serials = serialList(it);
                return (
                  <div key={it.id} className="report-card-item">
                    <div className="report-card-item-name">
                      {it.product_name}
                    </div>
                    {serials && (
                      <div className="report-card-item-serial">{serials}</div>
                    )}
                    <div className="report-card-item-row">
                      <span>
                        {it.qty} × ${fmtMoney(Number(it.unit_price))}
                      </span>
                      <b>${fmtMoney(Number(it.amount))}</b>
                    </div>
                    {countsMargin ? (
                      <div className="report-card-item-cost">
                        成本 ${fmtMoney(Number(it.cost_at_post))}
                        <span className="report-card-sep">·</span>
                        毛利{" "}
                        <span
                          style={{
                            color: profit < 0 ? "#ff7070" : undefined,
                          }}
                        >
                          ${fmtMoney(profit)}
                        </span>
                      </div>
                    ) : (
                      <div className="report-card-item-cost dim">不計毛利</div>
                    )}
                  </div>
                );
              })}
            </div>

            <div className="report-card-foot">
              <span>含稅金額</span>
              <b>${fmtMoney(orderAmount)}</b>
              <span className="report-card-sep">·</span>
              <span>該單毛利</span>
              <b
                style={{
                  color: !hasMarginItem
                    ? "var(--text-dim)"
                    : orderProfit < 0
                    ? "#ff7070"
                    : undefined,
                }}
              >
                {hasMarginItem ? `$${fmtMoney(orderProfit)}` : "—"}
              </b>
            </div>
          </div>
        );
      })}
    </div>
  );
}

interface ReportTableProps {
  orders: SalesOrder[];
  voided: boolean;
}

function SalesReportTable({ orders, voided }: ReportTableProps) {
  if (orders.length === 0) return null;
  return (
    <table className={`report-grid ${voided ? "void" : ""}`}>
      <thead>
        <tr>
          <th>日期</th>
          <th>單號</th>
          <th>出貨倉</th>
          <th>業務員</th>
          <th>客戶</th>
          <th>商品</th>
          <th>序號</th>
          <th className="num">數量</th>
          <th className="num">單價</th>
          <th className="num">金額</th>
          <th className="num">成本</th>
          <th className="num">毛利</th>
          <th className="num">業務員毛利</th>
        </tr>
      </thead>
      <tbody>
        {orders.map((o) => {
          const hasMarginItem = o.items.some(itemCountsMargin);
          const orderProfit = o.items.reduce(
            (s, it) => s + itemGrossProfit(it, o.tax_method),
            0,
          );
          return (
            <ReportOrderGroup
              key={o.id}
              order={o}
              orderProfit={orderProfit}
              hasMarginItem={hasMarginItem}
            />
          );
        })}
      </tbody>
    </table>
  );
}

function ReportOrderGroup({
  order,
  orderProfit,
  hasMarginItem,
}: {
  order: SalesOrder;
  orderProfit: number;
  hasMarginItem: boolean;
}) {
  return (
    <>
      {order.items.map((it, idx) => {
        const first = idx === 0;
        const countsMargin = itemCountsMargin(it);
        const profit = itemGrossProfit(it, order.tax_method);
        return (
          <tr
            key={it.id}
            className={
              first
                ? "report-row order-first"
                : "report-row order-cont"
            }
          >
            <td>{first ? order.doc_date : ""}</td>
            <td>{first ? order.no : ""}</td>
            <td>
              {first
                ? `${order.warehouse_code ?? ""} ${order.warehouse_name ?? ""}`.trim()
                : ""}
            </td>
            <td>{first ? order.sales_person_name ?? "" : ""}</td>
            <td>{first ? order.customer_name ?? "散客" : ""}</td>
            <td>{it.product_name}</td>
            <td className="report-serial">{serialList(it)}</td>
            <td className="num">{it.qty}</td>
            <td className="num">{fmtMoney(Number(it.unit_price))}</td>
            <td className="num">{fmtMoney(Number(it.amount))}</td>
            <td className="num">
              {countsMargin ? fmtMoney(Number(it.cost_at_post)) : "—"}
            </td>
            <td
              className="num"
              style={{
                color: !countsMargin
                  ? "var(--text-dim)"
                  : profit < 0
                  ? "#ff7070"
                  : undefined,
              }}
            >
              {countsMargin ? fmtMoney(profit) : "—"}
            </td>
            <td className="num" style={{ color: "var(--text-dim)" }}>
              —
            </td>
          </tr>
        );
      })}
      <tr className="report-row order-subtotal">
        <td colSpan={11} className="num" style={{ textAlign: "right" }}>
          該單小計
        </td>
        <td
          className="num"
          style={{
            color: !hasMarginItem
              ? "var(--text-dim)"
              : orderProfit < 0
              ? "#ff7070"
              : undefined,
          }}
        >
          {hasMarginItem ? fmtMoney(orderProfit) : "—"}
        </td>
        <td className="num" style={{ color: "var(--text-dim)" }}>
          —
        </td>
      </tr>
    </>
  );
}
