import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useSalesOrders } from "@/api/hooks";
import { searchCustomers } from "@/api/search";
import type { Customer } from "@/api/types";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { Field } from "@/components/Field";
import { Toolbar } from "@/components/Toolbar";

export function MembersPage() {
  const navigate = useNavigate();
  const [customerOption, setCustomerOption] =
    useState<ComboOption<Customer> | null>(null);
  const customer = customerOption?.payload ?? null;
  const customerId = customer?.id ?? null;

  const orders = useSalesOrders(
    customerId ? { customer: customerId } : undefined,
  );

  // 統計
  const stats = useMemo(() => {
    const list = orders.data ?? [];
    const active = list.filter((o) => !o.is_void);
    const total = active.reduce((s, o) => s + Number(o.total || 0), 0);
    const lastVisit = active.reduce<string | null>((d, o) => {
      if (!d) return o.doc_date;
      return o.doc_date > d ? o.doc_date : d;
    }, null);
    return { count: active.length, total, lastVisit };
  }, [orders.data]);

  return (
    <div className="page">
      <Toolbar title="會員查詢" />
      <div className="entry-body">
        <Field label="電話 / 姓名">
          <ComboBox<Customer>
            value={customer?.id ?? ""}
            selectedOption={customerOption}
            onChange={(_id, opt) => setCustomerOption(opt ?? null)}
            fetchOptions={searchCustomers}
            placeholder="輸入電話、姓名或統編搜尋"
          />
        </Field>

        {customer && (
          <div
            className="fieldset"
            style={{ marginTop: 16, maxWidth: 720, padding: 12 }}
          >
            <legend>會員資料</legend>
            <div className="member-detail">
              <Row label="姓名" value={customer.name || "—"} />
              <Row label="電話" value={customer.phone || "—"} />
              <Row label="類別" value={customer.kind_label} />
              <Row
                label="會員身份"
                value={
                  customer.is_member ? (
                    <span style={{ color: "#80d090" }}>會員</span>
                  ) : (
                    <span style={{ color: "var(--text-dim)" }}>非會員</span>
                  )
                }
              />
              <Row label="統一編號" value={customer.tax_id || "—"} />
              <Row label="累計消費" value={
                <b>${stats.total.toLocaleString()}</b>
              } />
              <Row
                label="消費次數"
                value={`${stats.count} 筆`}
              />
              <Row label="最近消費" value={stats.lastVisit || "—"} />
            </div>
          </div>
        )}

        <h3 style={{ marginTop: 24 }}>
          銷售紀錄 {customer ? `(${stats.count} 筆)` : ""}
        </h3>

        {!customer && (
          <div className="md-empty">先在上方搜尋一位會員</div>
        )}

        {customer && orders.isLoading && (
          <div className="md-empty">載入中…</div>
        )}

        {customer && !orders.isLoading && (
          <div className="md-table" style={{ height: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th>單號</th>
                  <th>日期</th>
                  <th>業務員</th>
                  <th>課稅別</th>
                  <th>發票號</th>
                  <th className="num">總額</th>
                </tr>
              </thead>
              <tbody>
                {(orders.data ?? []).map((so) => (
                  <tr
                    key={so.id}
                    onClick={() => navigate(`/sales/${so.id}`)}
                    className={so.is_void ? "row-void" : undefined}
                  >
                    <td>{so.no}</td>
                    <td>{so.doc_date}</td>
                    <td>
                      {so.sales_person_name
                        ? `${so.sales_person_code ?? ""} ${so.sales_person_name}`
                        : "—"}
                    </td>
                    <td>{so.tax_method_label}</td>
                    <td>{so.invoice_no || "—"}</td>
                    <td className="num">
                      {Number(so.total).toLocaleString()}
                    </td>
                  </tr>
                ))}
                {(orders.data ?? []).length === 0 && (
                  <tr>
                    <td colSpan={6} className="md-empty">
                      此會員尚無銷售紀錄
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function Row({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="member-row">
      <span className="member-row-label">{label}</span>
      <span className="member-row-value">{value}</span>
    </div>
  );
}
