import { useEffect, useMemo, useState } from "react";

import { useBusinessDailyReport, useWarehouses } from "@/api/hooks";
import { useDefaultWarehouse } from "@/auth/AuthContext";
import { Toolbar } from "@/components/Toolbar";

const today = () => new Date().toISOString().slice(0, 10);

export function BusinessDailyReportPage() {
  const defaultWarehouse = useDefaultWarehouse();
  const warehousesQuery = useWarehouses();
  const allWarehouses = warehousesQuery.data ?? [];
  // 鎖倉帳號:只能看自己倉的日報,門市下拉只顯示這一個
  const warehouses = defaultWarehouse.locked
    ? allWarehouses.filter((w) => w.id === defaultWarehouse.id)
    : allWarehouses;
  const [warehouse, setWarehouse] = useState<number | "">(
    defaultWarehouse.locked && defaultWarehouse.id ? defaultWarehouse.id : "",
  );
  const [date, setDate] = useState(today());

  // 首次載入帶第一個倉(鎖倉者已經是自己的倉)
  useEffect(() => {
    if (warehouses.length > 0 && warehouse === "") {
      setWarehouse(warehouses[0].id);
    }
  }, [warehouses, warehouse]);

  const reportQuery = useBusinessDailyReport(
    warehouse === "" ? null : (warehouse as number),
    date,
  );
  const report = reportQuery.data;

  // 期初現金 = 該倉之前所有現金動作的累計(後端自動算,使用者不可改)
  const openingInt = report?.opening_cash ?? 0;
  const salesTotal = report?.sales.total ?? 0;
  const nonCashSalesTotal = report?.non_cash_sales.total ?? 0;
  const salesReturnsTotal = report?.sales_returns.total ?? 0;
  const purchasesTotal = report?.purchases.total ?? 0;
  const expensesTotal = report?.expenses.total ?? 0;
  const phoneBillsTotal = report?.phone_bills.total ?? 0;
  const adjInTotal = report?.adjustments.in_total ?? 0;
  const adjOutTotal = report?.adjustments.out_total ?? 0;
  const netChange =
    salesTotal
    + phoneBillsTotal
    - salesReturnsTotal
    - purchasesTotal
    - expensesTotal
    + adjInTotal
    - adjOutTotal;
  const closing = openingInt + netChange;
  const dailyRevenue = salesTotal + nonCashSalesTotal + phoneBillsTotal;

  const warehouseName = useMemo(() => {
    const w = warehouses.find((x) => x.id === warehouse);
    return w ? `${w.code} ${w.name}` : "";
  }, [warehouses, warehouse]);

  function exportCsv() {
    if (!report) return;
    const lines: string[] = [];
    lines.push(`營業日報 - ${warehouseName} - ${date}`);
    lines.push("");
    lines.push(`前日現金,${openingInt}`);
    lines.push("");
    lines.push("【銷貨現金收入】");
    lines.push("單號,客戶,業務員,單據總額,現金部分");
    for (const r of report.sales.rows) {
      lines.push(
        [
          r.no,
          (r.customer_name ?? "").toString().replace(/,/g, " "),
          (r.sales_person_name ?? "").toString().replace(/,/g, " "),
          r.total,
          r.cash_amount,
        ].join(","),
      );
    }
    lines.push(`小計,,,,${salesTotal}`);
    lines.push("");
    lines.push("【非現金收入(匯款 / 刷卡 / LinePay 等)】");
    lines.push("單號,客戶,業務員,單據總額,非現金部分,方式拆分");
    for (const r of report.non_cash_sales.rows) {
      const breakdown = Array.isArray(r.method_breakdown)
        ? (r.method_breakdown as { name: string; amount: string }[])
            .map((m) => `${m.name}:${m.amount}`)
            .join(" + ")
        : "";
      lines.push(
        [
          r.no,
          (r.customer_name ?? "").toString().replace(/,/g, " "),
          (r.sales_person_name ?? "").toString().replace(/,/g, " "),
          r.total,
          r.non_cash_amount,
          breakdown.replace(/,/g, " "),
        ].join(","),
      );
    }
    lines.push(`小計,,,,${nonCashSalesTotal},`);
    lines.push("");
    lines.push("【代收話費】");
    lines.push("單號,電信,電話,會員,經手人,金額");
    for (const r of report.phone_bills.rows) {
      lines.push(
        [
          r.no,
          String(r.carrier_name ?? "").replace(/,/g, " "),
          String(r.phone_no ?? "").replace(/,/g, " "),
          String(r.member_name ?? "").replace(/,/g, " "),
          String(r.handled_by_name ?? "").replace(/,/g, " "),
          r.amount,
        ].join(","),
      );
    }
    lines.push(`小計,,,,,${phoneBillsTotal}`);
    lines.push("");
    lines.push("【進貨現金付款】");
    lines.push("單號,供應商,付款方式,金額");
    for (const r of report.purchases.rows) {
      lines.push(
        [
          r.no,
          (r.supplier_name ?? "").toString().replace(/,/g, " "),
          r.payment_method_name,
          r.total_cost,
        ].join(","),
      );
    }
    lines.push(`小計,,,${purchasesTotal}`);
    lines.push("");
    lines.push("【雜支現金支出】");
    lines.push("單號,類別,收款對象,備註,金額");
    for (const r of report.expenses.rows) {
      lines.push(
        [
          r.no,
          r.category_label,
          (r.payee ?? "").toString().replace(/,/g, " "),
          (r.note ?? "").toString().replace(/,/g, " "),
          r.amount,
        ].join(","),
      );
    }
    lines.push(`小計,,,,${expensesTotal}`);
    lines.push("");
    lines.push("【銷退現金支出】");
    lines.push("銷退單號,原銷貨單,客戶,退款方式,金額");
    for (const r of report.sales_returns.rows) {
      lines.push(
        [
          r.no,
          String(r.original_so_no ?? ""),
          (r.customer_name ?? "").toString().replace(/,/g, " "),
          String(r.payment_method_name ?? ""),
          r.total,
        ].join(","),
      );
    }
    lines.push(`小計,,,,${salesReturnsTotal}`);
    lines.push("");
    lines.push("【現金調整】");
    lines.push("單號,方向,事由,備註,金額");
    for (const r of report.adjustments.rows) {
      lines.push(
        [
          r.no,
          r.direction_label,
          r.reason_label,
          (r.note ?? "").toString().replace(/,/g, " "),
          r.amount,
        ].join(","),
      );
    }
    lines.push(`存入小計,,,,${adjInTotal}`);
    lines.push(`提取小計,,,,${adjOutTotal}`);
    lines.push("");
    lines.push(`前日現金,${openingInt}`);
    lines.push(`銷貨現金收入,${salesTotal}`);
    lines.push(`非現金收入,${nonCashSalesTotal}`);
    lines.push(`代收話費,${phoneBillsTotal}`);
    lines.push(`銷退現金支出,-${salesReturnsTotal}`);
    lines.push(`進貨現金付款,-${purchasesTotal}`);
    lines.push(`雜支現金支出,-${expensesTotal}`);
    lines.push(`現金存入,+${adjInTotal}`);
    lines.push(`現金提取,-${adjOutTotal}`);
    lines.push(`今日結餘(僅現金),${closing}`);
    lines.push(`當日總營收(現金+非現金),${dailyRevenue}`);

    const csv = "﻿" + lines.join("\r\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `營業日報_${warehouseName}_${date}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  return (
    <div className="page">
      <Toolbar
        title="營業日報"
        actions={
          <button
            className="btn"
            type="button"
            onClick={exportCsv}
            disabled={!report}
          >
            匯出 CSV
          </button>
        }
      >
        <label style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
          門市:
          <select
            value={warehouse}
            onChange={(e) =>
              setWarehouse(e.target.value ? Number(e.target.value) : "")
            }
          >
            {warehouses.map((w) => (
              <option key={w.id} value={w.id}>
                {w.code} {w.name}
              </option>
            ))}
          </select>
        </label>
        <label style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
          日期:
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
          />
        </label>
      </Toolbar>

      <div className="entry-body" style={{ padding: 16 }}>
        {reportQuery.isLoading && <div className="md-empty">載入中…</div>}
        {reportQuery.isError && (
          <div className="md-empty">
            載入失敗:{String(reportQuery.error)}
          </div>
        )}

        {report && (
          <>
            {/* 兩張摘要卡片:現金櫃流水 + 當日營收 */}
            <div className="biz-summary-grid">
              {/* 現金櫃流水 */}
              <div className="biz-summary-card">
                <div className="biz-summary-card-title">現金櫃流水</div>
                <div className="biz-cash-cells">
                  <CashItem label="前日現金" value={openingInt} />
                  <CashItem label="銷貨現金" value={salesTotal} />
                  <CashItem label="代收話費" value={phoneBillsTotal} />
                  <CashItem
                    label="銷退現金"
                    value={salesReturnsTotal}
                    sign="−"
                    color={salesReturnsTotal > 0 ? "#ff7070" : undefined}
                  />
                  <CashItem
                    label="進貨付款"
                    value={purchasesTotal}
                    sign="−"
                    color={purchasesTotal > 0 ? "#ff7070" : undefined}
                  />
                  <CashItem label="今日結餘" value={closing} />
                  <CashItem
                    label="雜支支出"
                    value={expensesTotal}
                    sign="−"
                    color={expensesTotal > 0 ? "#ff7070" : undefined}
                  />
                  <CashItem label="現金存入" value={adjInTotal} />
                  <CashItem
                    label="現金提取"
                    value={adjOutTotal}
                    sign="−"
                    color={adjOutTotal > 0 ? "#ff7070" : undefined}
                  />
                  <div style={{ background: "var(--panel)" }} />
                </div>
              </div>

              {/* 當日營收 */}
              <div className="biz-summary-card">
                <div className="biz-summary-card-title">當日營收</div>
                <div className="biz-revenue-cells">
                  <CashItem label="現金" value={salesTotal} />
                  <CashItem label="代收話費" value={phoneBillsTotal} />
                  <CashItem label="非現金" value={nonCashSalesTotal} />
                  <CashItem label="總計" value={dailyRevenue} />
                </div>
              </div>
            </div>

            {/* 收入區 */}
            <SectionGroup label="收入">

            {/* 銷貨現金 */}
            <Section
              title="銷貨現金收入"
              count={report.sales.rows.length}
              total={salesTotal}
            >
              <table className="line-table">
                <thead>
                  <tr>
                    <th>單號</th>
                    <th>客戶</th>
                    <th>業務員</th>
                    <th className="num">單據總額</th>
                    <th className="num">現金部分</th>
                  </tr>
                </thead>
                <tbody>
                  {report.sales.rows.map((r) => (
                    <tr
                      key={r.id}
                      onClick={() =>
                        window.open(`/sales/${r.id}?focus=1`, "_blank")
                      }
                      style={{ cursor: "pointer" }}
                      title="點擊在新分頁查看銷貨單"
                    >
                      <td>{r.no}</td>
                      <td>{String(r.customer_name || "—")}</td>
                      <td>{String(r.sales_person_name || "—")}</td>
                      <td className="num">
                        {Math.round(Number(r.total)).toLocaleString()}
                      </td>
                      <td className="num">
                        {Math.round(Number(r.cash_amount)).toLocaleString()}
                      </td>
                    </tr>
                  ))}
                  {report.sales.rows.length === 0 && (
                    <tr>
                      <td colSpan={5} className="md-empty">
                        本日無現金銷貨
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </Section>

            {/* 非現金收入 */}
            <Section
              title="非現金收入"
              count={report.non_cash_sales.rows.length}
              total={nonCashSalesTotal}
            >
              <table className="line-table">
                <thead>
                  <tr>
                    <th>單號</th>
                    <th>客戶</th>
                    <th>業務員</th>
                    <th className="num">單據總額</th>
                    <th className="num">非現金部分</th>
                    <th>方式</th>
                  </tr>
                </thead>
                <tbody>
                  {report.non_cash_sales.rows.map((r) => {
                    const breakdown = Array.isArray(r.method_breakdown)
                      ? (r.method_breakdown as {
                          name: string;
                          amount: string;
                        }[])
                      : [];
                    return (
                      <tr
                        key={r.id}
                        onClick={() =>
                          window.open(`/sales/${r.id}?focus=1`, "_blank")
                        }
                        style={{ cursor: "pointer" }}
                        title="點擊在新分頁查看銷貨單"
                      >
                        <td>{r.no}</td>
                        <td>{String(r.customer_name || "—")}</td>
                        <td>{String(r.sales_person_name || "—")}</td>
                        <td className="num">
                          {Math.round(Number(r.total)).toLocaleString()}
                        </td>
                        <td className="num">
                          {Math.round(
                            Number(r.non_cash_amount),
                          ).toLocaleString()}
                        </td>
                        <td style={{ fontSize: 12 }}>
                          {breakdown
                            .map(
                              (m) =>
                                `${m.name} ${Math.round(
                                  Number(m.amount),
                                ).toLocaleString()}`,
                            )
                            .join(" / ")}
                        </td>
                      </tr>
                    );
                  })}
                  {report.non_cash_sales.rows.length === 0 && (
                    <tr>
                      <td colSpan={6} className="md-empty">
                        本日無非現金收入
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </Section>

            {/* 代收話費 */}
            <Section
              title="代收話費"
              count={report.phone_bills.rows.length}
              total={phoneBillsTotal}
            >
              <table className="line-table">
                <thead>
                  <tr>
                    <th>單號</th>
                    <th>電信</th>
                    <th>電話</th>
                    <th>會員</th>
                    <th>經手人</th>
                    <th className="num">金額</th>
                  </tr>
                </thead>
                <tbody>
                  {report.phone_bills.rows.map((r) => (
                    <tr
                      key={r.id}
                      onClick={() =>
                        window.open(
                          `/telecom/billing/${r.id}/receipt`,
                          "_blank",
                          "width=380,height=720",
                        )
                      }
                      style={{ cursor: "pointer" }}
                      title="點擊在新分頁列印收據"
                    >
                      <td>{r.no}</td>
                      <td>{String(r.carrier_name ?? "")}</td>
                      <td>{String(r.phone_no ?? "")}</td>
                      <td>{String(r.member_name || "—")}</td>
                      <td>{String(r.handled_by_name || "—")}</td>
                      <td className="num">
                        {Math.round(Number(r.amount)).toLocaleString()}
                      </td>
                    </tr>
                  ))}
                  {report.phone_bills.rows.length === 0 && (
                    <tr>
                      <td colSpan={6} className="md-empty">
                        本日無代收話費
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </Section>

            </SectionGroup>

            {/* 支出區 */}
            <SectionGroup label="支出">

            {/* 進貨現金 */}
            <Section
              title="進貨現金付款"
              count={report.purchases.rows.length}
              total={purchasesTotal}
              totalColor="#ff7070"
            >
              <table className="line-table">
                <thead>
                  <tr>
                    <th>單號</th>
                    <th>供應商</th>
                    <th>付款方式</th>
                    <th className="num">金額</th>
                  </tr>
                </thead>
                <tbody>
                  {report.purchases.rows.map((r) => (
                    <tr
                      key={r.id}
                      onClick={() =>
                        window.open(`/purchases/${r.id}?focus=1`, "_blank")
                      }
                      style={{ cursor: "pointer" }}
                      title="點擊在新分頁查看進貨單"
                    >
                      <td>{r.no}</td>
                      <td>{String(r.supplier_name || "—")}</td>
                      <td>{String(r.payment_method_name)}</td>
                      <td className="num">
                        {Math.round(Number(r.total_cost)).toLocaleString()}
                      </td>
                    </tr>
                  ))}
                  {report.purchases.rows.length === 0 && (
                    <tr>
                      <td colSpan={4} className="md-empty">
                        本日無現金進貨付款
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </Section>

            {/* 雜支現金 */}
            <Section
              title="雜支現金支出"
              count={report.expenses.rows.length}
              total={expensesTotal}
              totalColor="#ff7070"
            >
              <table className="line-table">
                <thead>
                  <tr>
                    <th>單號</th>
                    <th>類別</th>
                    <th>收款對象</th>
                    <th>備註</th>
                    <th className="num">金額</th>
                  </tr>
                </thead>
                <tbody>
                  {report.expenses.rows.map((r) => (
                    <tr
                      key={r.id}
                      onClick={() => window.open("/expenses", "_blank")}
                      style={{ cursor: "pointer" }}
                      title="點擊在新分頁開啟雜支列表"
                    >
                      <td>{r.no}</td>
                      <td>{String(r.category_label)}</td>
                      <td>{String(r.payee || "—")}</td>
                      <td>{String(r.note || "—")}</td>
                      <td className="num">
                        {Math.round(Number(r.amount)).toLocaleString()}
                      </td>
                    </tr>
                  ))}
                  {report.expenses.rows.length === 0 && (
                    <tr>
                      <td colSpan={5} className="md-empty">
                        本日無現金雜支
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </Section>

            {/* 銷退現金支出 */}
            <Section
              title="銷退現金支出"
              count={report.sales_returns.rows.length}
              total={salesReturnsTotal}
              totalColor="#ff7070"
            >
              <table className="line-table">
                <thead>
                  <tr>
                    <th>銷退單號</th>
                    <th>原銷貨單</th>
                    <th>客戶</th>
                    <th>退款方式</th>
                    <th className="num">退款金額</th>
                  </tr>
                </thead>
                <tbody>
                  {report.sales_returns.rows.map((r) => (
                    <tr
                      key={r.id}
                      onClick={() =>
                        window.open(`/sales/returns/${r.id}?focus=1`, "_blank")
                      }
                      style={{ cursor: "pointer" }}
                      title="點擊在新分頁查看銷退單"
                    >
                      <td>{r.no}</td>
                      <td>{String(r.original_so_no ?? "—")}</td>
                      <td>{String(r.customer_name || "—")}</td>
                      <td>{String(r.payment_method_name ?? "")}</td>
                      <td className="num" style={{ color: "#ff7070" }}>
                        −{Math.round(Number(r.total)).toLocaleString()}
                      </td>
                    </tr>
                  ))}
                  {report.sales_returns.rows.length === 0 && (
                    <tr>
                      <td colSpan={5} className="md-empty">
                        本日無現金銷退
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </Section>

            </SectionGroup>

            {/* 調整區 */}
            <SectionGroup label="調整">

            {/* 現金調整 */}
            <Section
              title="現金調整"
              count={report.adjustments.rows.length}
              total={adjInTotal - adjOutTotal}
              totalColor={
                adjInTotal - adjOutTotal < 0 ? "#ff7070" : undefined
              }
            >
              <table className="line-table">
                <thead>
                  <tr>
                    <th>單號</th>
                    <th>方向</th>
                    <th>事由</th>
                    <th>備註</th>
                    <th className="num">金額</th>
                  </tr>
                </thead>
                <tbody>
                  {report.adjustments.rows.map((r) => (
                    <tr
                      key={r.id}
                      onClick={() => window.open("/cash-adjustments", "_blank")}
                      style={{ cursor: "pointer" }}
                      title="點擊在新分頁開啟現金調整列表"
                    >
                      <td>{r.no}</td>
                      <td
                        style={{
                          color:
                            String(r.direction) === "out"
                              ? "#ff7070"
                              : undefined,
                        }}
                      >
                        {String(r.direction_label)}
                      </td>
                      <td>{String(r.reason_label)}</td>
                      <td>{String(r.note || "—")}</td>
                      <td
                        className="num"
                        style={{
                          color:
                            String(r.direction) === "out"
                              ? "#ff7070"
                              : undefined,
                        }}
                      >
                        {String(r.direction) === "in" ? "+" : "−"}
                        {Math.round(Number(r.amount)).toLocaleString()}
                      </td>
                    </tr>
                  ))}
                  {report.adjustments.rows.length === 0 && (
                    <tr>
                      <td colSpan={5} className="md-empty">
                        本日無現金調整
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </Section>

            </SectionGroup>
          </>
        )}
      </div>
    </div>
  );
}

function SectionGroup({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div style={{ marginBottom: 20 }}>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "20px 220px 80px 1fr",
          alignItems: "center",
          gap: 12,
          padding: "0 12px 4px 16px",
          marginBottom: 4,
          borderBottom: "1px solid var(--border)",
        }}
      >
        <span />
        <span
          style={{
            fontSize: 13,
            fontWeight: 700,
            color: "var(--text)",
            letterSpacing: 1,
          }}
        >
          {label}
        </span>
        <span
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: "var(--text-dim)",
            textAlign: "right",
          }}
        >
          筆數
        </span>
        <span
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: "var(--text-dim)",
            textAlign: "right",
          }}
        >
          小計
        </span>
      </div>
      {children}
    </div>
  );
}

function Section({
  title,
  count,
  total,
  totalColor,
  children,
}: {
  title: string;
  count: number;
  total?: number;
  totalColor?: string;
  children: React.ReactNode;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="biz-section">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="biz-section-header"
        style={{
          borderLeft: `4px solid ${totalColor ?? "var(--border)"}`,
        }}
        aria-expanded={expanded}
      >
        <span
          className="biz-section-arrow"
          style={{
            transform: expanded ? "rotate(90deg)" : "rotate(0)",
          }}
        >
          ▶
        </span>
        <span className="biz-section-title">{title}</span>
        <span className="biz-section-count">{count}</span>
        {total !== undefined ? (
          <span
            className="biz-section-total"
            style={{ color: totalColor ?? undefined }}
          >
            {total.toLocaleString()}
          </span>
        ) : (
          <span />
        )}
      </button>
      {expanded && <div className="biz-section-body">{children}</div>}
    </div>
  );
}

function CashItem({
  label,
  value,
  sign,
  color,
}: {
  label: string;
  value: number;
  sign?: "+" | "−";
  color?: string;
}) {
  const effectiveColor = color ?? (value < 0 ? "#ff7070" : "var(--text)");
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 1,
        padding: "6px 10px",
        background: "var(--panel)",
      }}
    >
      <span style={{ fontSize: 11, color: "var(--text-dim)", lineHeight: 1.3 }}>
        {label}
      </span>
      <span
        style={{
          fontSize: 16,
          fontWeight: 700,
          color: effectiveColor,
          fontVariantNumeric: "tabular-nums",
          lineHeight: 1.2,
        }}
      >
        {sign && value > 0 ? sign : ""}
        {value.toLocaleString()}
      </span>
    </div>
  );
}

