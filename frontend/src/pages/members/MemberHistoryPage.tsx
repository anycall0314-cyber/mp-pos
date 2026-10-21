import { useEffect, useMemo } from "react";
import { useParams } from "react-router-dom";

import {
  useLegacyPurchases,
  useMember,
  useOrdersOf,
  useOrderSummary,
} from "@/api/hooks";
import { Toolbar } from "@/components/Toolbar";
import { cutNote, latestDay } from "@/lib/listAll";
import { memberIdFromRoute, memberTabTitle } from "@/lib/memberUrl";
import { money } from "@/lib/money";

import { LegacyHistorySection } from "./LegacyHistorySection";

/**
 * 會員的消費紀錄(`/members/編號`;會員名單點一位開的新分頁)。
 * owner 2026-10-20:「跳分頁只要顯示消費紀錄不要編輯會員資料，原來的頁面右邊只需顯示編輯欄位」
 * —— 這一頁只看、不能改會員資料;改資料在原本那一頁的右邊。
 * 2026-10-21:「不用有側邊欄，也不需要有客戶，單純只要消費紀錄，讓分頁無需有任何功能讓門市開了兩個功能pos頁面」
 * —— 外框不放側邊欄與上面那排(`isMemberHistoryPath`),點一列也不跳去銷貨單。
 */
export function MemberHistoryPage() {
  const memberId = memberIdFromRoute(useParams().id);
  const one = useMember(memberId);
  const member = one.data;

  const who = memberId ? { member: memberId } : undefined;
  const orders = useOrdersOf(who);            // 最近的 100 張(底下那張表)
  const summary = useOrderSummary(who);       // 幾張、累計、最近:伺服器算全部
  const legacy = useLegacyPurchases(memberId);

  // 分頁標題寫會員名字(開好幾位分得出來);離開這一頁還原
  const name = member?.name;
  useEffect(() => {
    const before = document.title;
    document.title = memberTabTitle(name);
    return () => {
      document.title = before;
    };
  }, [name]);

  // 把現役銷貨單明細 + 舊系統紀錄整成單一時間軸,每列一個商品 row。
  type Row = {
    key: string;
    source: "current" | "legacy";
    doc_date: string;
    is_void: boolean;
    product_name: string;
    product_sku: string;
    qty: number;
    unit_price: string;
    amount: string;
    serial_or_msisdn: string;
    sales_person_label: string;
    customer_name: string;
    doc_no: string;
  };

  const rows = useMemo<Row[]>(() => {
    const fromCurrent: Row[] = (orders.data?.rows ?? []).flatMap((so) =>
      so.items.map((it) => ({
        key: `c-${so.id}-${it.id}`,
        source: "current" as const,
        doc_date: so.doc_date,
        is_void: so.is_void,
        product_name: it.product_name,
        product_sku: it.product_sku,
        qty: it.qty,
        unit_price: it.unit_price,
        amount: it.amount,
        serial_or_msisdn:
          it.msisdn ||
          (it.serials ?? []).map((s) => s.serial_no).join(", ") ||
          "—",
        sales_person_label: so.sales_person_name
          ? `${so.sales_person_code ?? ""} ${so.sales_person_name}`
          : "—",
        customer_name: so.source_name || so.customer_name || "—",
        doc_no: so.no,
      })),
    );
    const fromLegacy: Row[] = (legacy.data ?? []).map((lp) => ({
      key: `l-${lp.id}`,
      source: "legacy" as const,
      doc_date: lp.doc_date,
      is_void: false,
      product_name: lp.product_name,
      product_sku: lp.product_sku,
      qty: lp.qty,
      unit_price: lp.unit_price,
      amount: lp.amount,
      serial_or_msisdn: lp.serial_no || "—",
      sales_person_label: "—",
      customer_name: "—",
      doc_no: lp.source_no || "(舊系統)",
    }));
    return [...fromCurrent, ...fromLegacy].sort((a, b) =>
      a.doc_date < b.doc_date ? 1 : a.doc_date > b.doc_date ? -1 : 0,
    );
  }, [orders.data, legacy.data]);

  const orderStats = useMemo(() => {
    const legacyList = legacy.data ?? [];
    const legacyTotal = legacyList.reduce(
      (s, lp) => s + Number(lp.amount || 0),
      0,
    );
    return {
      count: summary.data?.count ?? 0,
      total: Number(summary.data?.total ?? 0),
      legacyCount: legacyList.length,
      legacyTotal,
      lastVisit: latestDay(summary.data?.last_date, ...legacyList.map((lp) => lp.doc_date)),
    };
  }, [summary.data, legacy.data]);
  const ordersLoading = orders.isLoading || summary.isLoading || legacy.isLoading;
  const ordersFailed = orders.isError || summary.isError || legacy.isError;
  const ordersCut = cutNote(orders.data, "只列最近", "張");

  return (
    <div className="page">
      <Toolbar title="消費紀錄" />

      <div className="pc-layout solo">
        <div className="pc-detail">
          {!member && (
            <div className="md-empty" style={{ marginTop: 40 }}>
              {memberId == null || one.isError ? "找不到這位會員" : "載入中…"}
            </div>
          )}

          {member && (
            <div className="pc-detail-body">
              <h3 className="pc-detail-title">
                {member.name}
                <span style={{ fontWeight: "normal", color: "var(--text-dim)", marginLeft: 12 }}>
                  {[member.code, member.phone].filter(Boolean).join(" · ")}
                </span>
              </h3>
              <h4 className="pc-detail-title">
                購買明細
                {ordersLoading
                  ? " 載入中…"
                  : ordersFailed
                    ? " 載入失敗"
                    : ` (${orderStats.count} 筆銷貨 · 累計 $${money(orderStats.total)}${
                      orderStats.legacyCount > 0
                        ? ` · 舊系統 ${orderStats.legacyCount} 筆 / $${money(orderStats.legacyTotal)}`
                        : ""
                    }${
                      orderStats.lastVisit
                        ? ` · 最近 ${orderStats.lastVisit}`
                        : ""
                    })`}
              </h4>
              <div className="md-table" style={{ height: "auto" }}>
                <table>
                  <thead>
                    <tr>
                      <th style={{ width: 100 }}>日期</th>
                      <th>商品</th>
                      <th style={{ width: 160 }}>序號 / 門號</th>
                      <th className="num" style={{ width: 50 }}>數量</th>
                      <th className="num" style={{ width: 90 }}>單價</th>
                      <th className="num" style={{ width: 100 }}>小計</th>
                      <th style={{ width: 100 }}>業務員</th>
                      <th style={{ width: 100 }}>來源／舊客戶</th>
                      <th style={{ width: 120 }}>單號</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr
                        key={r.key}
                        className={r.is_void ? "row-void" : undefined}
                        style={{ opacity: r.source === "legacy" ? 0.85 : 1 }}
                      >
                        <td>{r.doc_date}</td>
                        <td>
                          <div>{r.product_name}</div>
                          <div style={{ fontSize: 14, color: "var(--text-dim)" }}>
                            {r.product_sku}
                          </div>
                        </td>
                        <td style={{ fontSize: 14 }}>{r.serial_or_msisdn}</td>
                        <td className="num">{r.qty}</td>
                        <td className="num">
                          {money(r.unit_price)}
                        </td>
                        <td className="num">
                          {money(r.amount)}
                        </td>
                        <td>{r.sales_person_label}</td>
                        <td>{r.customer_name}</td>
                        <td style={{ fontSize: 14, color: "var(--text-dim)" }}>
                          {r.doc_no}
                          {r.source === "legacy" && (
                            <span
                              style={{
                                marginLeft: 4,
                                fontSize: 12,
                                padding: "1px 4px",
                                border: "1px solid var(--text-dim)",
                                borderRadius: 3,
                              }}
                            >
                              舊
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                    {!ordersLoading && !ordersFailed && rows.length === 0 && (
                      <tr>
                        <td colSpan={9} className="md-empty">
                          此會員尚無銷售紀錄
                        </td>
                      </tr>
                    )}
                    {ordersCut && (
                      <tr>
                        <td colSpan={9} className="md-empty">
                          {ordersCut}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              <LegacyHistorySection memberId={member.id} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
