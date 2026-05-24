import { useEffect, useMemo, useState } from "react";

import { useBusinessDailyReport, useWarehouses } from "@/api/hooks";
import { Toolbar } from "@/components/Toolbar";

const OPENING_CASH_KEY = "business-daily-opening-cash";

interface OpeningMap {
  [key: string]: string; // key = `${warehouseId}:${date}` 或 `${warehouseId}:last`
}

function loadOpeningMap(): OpeningMap {
  try {
    const raw = localStorage.getItem(OPENING_CASH_KEY);
    return raw ? (JSON.parse(raw) as OpeningMap) : {};
  } catch {
    return {};
  }
}

function saveOpening(warehouse: number, date: string, v: string) {
  const map = loadOpeningMap();
  map[`${warehouse}:${date}`] = v;
  map[`${warehouse}:last`] = v;
  try {
    localStorage.setItem(OPENING_CASH_KEY, JSON.stringify(map));
  } catch {}
}

function getOpening(warehouse: number, date: string): string {
  const map = loadOpeningMap();
  return map[`${warehouse}:${date}`] ?? map[`${warehouse}:last`] ?? "";
}

const today = () => new Date().toISOString().slice(0, 10);

export function BusinessDailyReportPage() {
  const warehousesQuery = useWarehouses();
  const warehouses = warehousesQuery.data ?? [];
  const [warehouse, setWarehouse] = useState<number | "">("");
  const [date, setDate] = useState(today());
  const [opening, setOpening] = useState("");

  // 首次載入或切倉/切日時帶入記住的期初
  useEffect(() => {
    if (warehouses.length > 0 && warehouse === "") {
      setWarehouse(warehouses[0].id);
    }
  }, [warehouses, warehouse]);

  useEffect(() => {
    if (warehouse) {
      setOpening(getOpening(warehouse as number, date));
    }
  }, [warehouse, date]);

  const reportQuery = useBusinessDailyReport(
    warehouse === "" ? null : (warehouse as number),
    date,
  );
  const report = reportQuery.data;

  const openingInt = Math.round(Number(opening) || 0);
  const salesTotal = report?.sales.total ?? 0;
  const purchasesTotal = report?.purchases.total ?? 0;
  const expensesTotal = report?.expenses.total ?? 0;
  const adjInTotal = report?.adjustments.in_total ?? 0;
  const adjOutTotal = report?.adjustments.out_total ?? 0;
  const netChange =
    salesTotal - purchasesTotal - expensesTotal + adjInTotal - adjOutTotal;
  const closing = openingInt + netChange;

  const warehouseName = useMemo(() => {
    const w = warehouses.find((x) => x.id === warehouse);
    return w ? `${w.code} ${w.name}` : "";
  }, [warehouses, warehouse]);

  function commitOpening() {
    if (warehouse) {
      saveOpening(warehouse as number, date, opening);
    }
  }

  function exportCsv() {
    if (!report) return;
    const lines: string[] = [];
    lines.push(`營業日報 - ${warehouseName} - ${date}`);
    lines.push("");
    lines.push(`期初現金,${openingInt}`);
    lines.push("");
    lines.push("【銷貨 cash 收入】");
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
    lines.push("【進貨 cash 付款】");
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
    lines.push("【雜支 cash 支出】");
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
    lines.push(`期初,${openingInt}`);
    lines.push(`銷貨現金收入,${salesTotal}`);
    lines.push(`進貨現金付款,-${purchasesTotal}`);
    lines.push(`雜支現金支出,-${expensesTotal}`);
    lines.push(`現金存入,+${adjInTotal}`);
    lines.push(`現金提取,-${adjOutTotal}`);
    lines.push(`期末結餘,${closing}`);

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
            {/* 期初現金 + 結餘總覽 */}
            <div
              style={{
                display: "flex",
                gap: 24,
                flexWrap: "wrap",
                alignItems: "center",
                padding: 16,
                background: "var(--panel)",
                border: "1px solid var(--border)",
                borderRadius: 4,
                marginBottom: 16,
              }}
            >
              <label
                style={{
                  display: "inline-flex",
                  gap: 6,
                  alignItems: "center",
                }}
              >
                期初現金:
                <input
                  type="number"
                  step="1"
                  min="0"
                  value={opening}
                  onChange={(e) => setOpening(e.target.value)}
                  onBlur={commitOpening}
                  placeholder="昨日交班結餘"
                  style={{ width: 110, textAlign: "right" }}
                />
              </label>
              <SummaryItem
                label="今日收入(銷貨現金)"
                value={salesTotal}
                color="#80d090"
              />
              <SummaryItem
                label="今日支出(進貨+雜支)"
                value={purchasesTotal + expensesTotal}
                color="#ff7070"
              />
              <SummaryItem
                label="現金調整(+存入/-提取)"
                value={adjInTotal - adjOutTotal}
                color={
                  adjInTotal - adjOutTotal >= 0 ? "#80d090" : "#ff7070"
                }
              />
              <SummaryItem
                label="淨變動"
                value={netChange}
                color={netChange >= 0 ? "#80d090" : "#ff7070"}
              />
              <SummaryItem
                label="期末結餘"
                value={closing}
                color="var(--text)"
                big
              />
            </div>

            {/* 銷貨 cash */}
            <Section
              title={`銷貨 cash 收入 (${report.sales.rows.length} 筆 · 小計 ${salesTotal.toLocaleString()})`}
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
                    <tr key={r.id}>
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

            {/* 進貨 cash */}
            <Section
              title={`進貨 cash 付款 (${report.purchases.rows.length} 筆 · 小計 ${purchasesTotal.toLocaleString()})`}
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
                    <tr key={r.id}>
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

            {/* 現金調整 */}
            <Section
              title={`現金調整 (${report.adjustments.rows.length} 筆 · 存入 +${adjInTotal.toLocaleString()} / 提取 -${adjOutTotal.toLocaleString()})`}
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
                    <tr key={r.id}>
                      <td>{r.no}</td>
                      <td
                        style={{
                          color:
                            String(r.direction) === "in"
                              ? "#80d090"
                              : "#ff7070",
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
                            String(r.direction) === "in"
                              ? "#80d090"
                              : "#ff7070",
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

            {/* 雜支 cash */}
            <Section
              title={`雜支 cash 支出 (${report.expenses.rows.length} 筆 · 小計 ${expensesTotal.toLocaleString()})`}
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
                    <tr key={r.id}>
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
          </>
        )}
      </div>
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div style={{ marginBottom: 16 }}>
      <h3 style={{ marginBottom: 6, fontSize: 14, color: "var(--text-dim)" }}>
        {title}
      </h3>
      {children}
    </div>
  );
}

function SummaryItem({
  label,
  value,
  color,
  big = false,
}: {
  label: string;
  value: number;
  color: string;
  big?: boolean;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      <span style={{ fontSize: 12, color: "var(--text-dim)" }}>{label}</span>
      <span
        style={{
          fontSize: big ? 24 : 18,
          fontWeight: 700,
          color,
        }}
      >
        {value.toLocaleString()}
      </span>
    </div>
  );
}
