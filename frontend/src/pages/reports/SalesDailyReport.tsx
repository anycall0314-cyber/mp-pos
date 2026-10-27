import { useMemo, useState } from "react";

import { useSalesDaily } from "@/api/hooks";
import {
  searchCustomers,
  searchMembers,
  searchSalesPersons,
} from "@/api/search";
import { useDefaultWarehouse, useSeesActualCost } from "@/auth/AuthContext";
import type { Customer, Member, SalesPerson, Warehouse } from "@/api/types";
import { Banner } from "@/components/Banner";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { Toolbar } from "@/components/Toolbar";
import { useIsMobile } from "@/hooks/useIsMobile";
import { shortDay } from "@/lib/dates";
import { rangeReady } from "@/lib/fixedReports";
import { money } from "@/lib/money";
import {
  customerText,
  dailyTable,
  dailyTotals,
  daysAgo,
  itemCountsMargin,
  itemGrossProfit,
  itemStaffProfit,
  narrowedBy,
  netTotals,
  orderPaidAmount,
  serialList,
  shownOrders,
  splitOrders,
  truncatedText,
  type DailyFilter,
  type DailyOrder,
} from "@/lib/salesDaily";
import { downloadCsv } from "@/components/downloadCsv";
import { exportFileName, exportIfComplete } from "@/lib/reportExports";
import { errorText } from "@/lib/errorText";
import { staffCostOf } from "@/lib/staffCost";
import { PeriodQuick } from "@/components/PeriodQuick";
import { StoreSelect } from "@/components/StoreSelect";

/** 這台電腦的今天(不用世界時間:台灣早上八點以前會變成昨天)。 */
function today(): string {
  return daysAgo(0);
}

function fmtMoney(v: number): string {
  return money(v);
}

type AppliedFilter = DailyFilter;

/**
 * 銷貨日報:期間內每一張銷貨單的每一行;期間內的銷退另外一塊(每一行是負的);作廢的單在最下面。
 * 資料由伺服器一次給齊(`sales-daily-report/`);標題旁邊那幾格的合計是沒扣銷退的,銷退另外一格。
 * 怎麼列、怎麼算在 `lib/salesDaily.ts`。
 */
export function SalesDailyReportPage() {
  const defaultWarehouse = useDefaultWarehouse();
  // 實際成本與毛利只有管理員;其他人的資料裡沒有實際成本,看業務員成本與業務員毛利(owner 2026-10-28)
  const actual = useSeesActualCost();
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
  const [member, setMember] = useState<number | "">("");
  const [memberOpt, setMemberOpt] = useState<ComboOption<Member> | null>(null);
  const [search, setSearch] = useState("");
  // 打了商品的字之後:只列對得上的那幾行;勾了才把同一張單的其他行一起列出來(合計跟著變)
  const [whole, setWhole] = useState(false);
  // 查詢當下選的門市叫什麼(匯出的檔名用)
  const [appliedStoreName, setAppliedStoreName] = useState("");

  // 已套用 — 按「查詢」才打 API
  const [applied, setApplied] = useState<AppliedFilter>(() => ({
    from: today(),
    to: today(),
    warehouse: "",
    sales_person: "",
    customer: "",
    member: "",
    search: "",
  }));

  const { data, isLoading, isError, error } = useSalesDaily(applied);

  // 要列的單與行(打了商品的字、沒勾整張單 = 只留對得上的行);正常單 / 作廢單 / 銷退各一塊
  const { activeOrders, voidOrders, returnOrders } = useMemo(() => {
    const all = !data?.searching || whole;
    const { active, voided } = splitOrders(shownOrders(data?.orders ?? [], all));
    return { activeOrders: active, voidOrders: voided, returnOrders: shownOrders(data?.returns ?? [], all) };
  }, [data, whole]);
  const nothing = activeOrders.length + voidOrders.length + returnOrders.length === 0;
  // 銷退的合計(本身是負的);「扣掉銷退之後」那一組 = 相加
  const backTotals = useMemo(() => dailyTotals(returnOrders), [returnOrders]);
  const narrowed = narrowedBy(applied);
  const cut = data ? truncatedText(data) : "";

  // 標題旁邊那幾格(商品 / 零件分開;沒扣銷退 —— 銷退另外一格)
  const totals = useMemo(() => dailyTotals(activeOrders), [activeOrders]);
  const net = netTotals(totals, backTotals);

  // 日期要兩個都有、而且起日不晚於迄日才查(不然請求不會送,畫面會像是「查無資料」)
  const ready = rangeReady({ from, to });

  function runQuery(over?: { from: string; to: string }) {
    if (!over && !ready) return;
    setAppliedStoreName(warehouseOpt?.label ?? "");
    setApplied({
      ...(over ?? { from, to }),
      warehouse,
      sales_person: salesPerson,
      customer,
      member,
      search,
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
    setMember("");
    setMemberOpt(null);
    setSearch("");
    setWhole(false);
    setAppliedStoreName("");
    setApplied({ from: t, to: t, warehouse: "", sales_person: "", customer: "", member: "", search: "" });
  }

  function exportCsv() {
    // 超過上限、合計不完整:不給只有一部分的檔(按鈕這時候也不能按)
    exportIfComplete(
      { count: data?.limit ?? 0, truncated: data?.truncated },
      exportFileName("銷貨日報", {
        store: defaultWarehouse.locked ? defaultWarehouse.name : appliedStoreName,
        from: applied.from,
        to: applied.to,
      }),
      () => dailyTable(activeOrders, returnOrders, voidOrders, actual),
      downloadCsv,
    );
  }

  // 表格上的日期:查的期間在同一年裡只寫月日(寬度留給品名)
  const day = (d: string) => shortDay(d, applied.from, applied.to);

  return (
    <div className="page sd-page">
      <Toolbar
        title="銷貨日報"
        actions={
          <button
            type="button"
            className="btn"
            onClick={exportCsv}
            disabled={nothing || !!cut}
            title={cut || undefined}
          >
            匯出
          </button>
        }
      >
        {/* 合計:標題旁邊的小表格(上面一列名稱、下面一列數字)。算式放在滑鼠提示 */}
        <div className="sd-sum">
          {narrowed.length > 0 && (
            <span className="wb-badge warn sd-narrowed" title={`只看:${narrowed.join("、")}。合計是這些條件的,不是整段期間的`}>
              篩選中
            </span>
          )}
          <SumCell label="正常單" value={String(activeOrders.length)} />
          <SumCell label="明細" value={String(totals.lines)} />
          <SumCell label="含稅金額" value={`$${fmtMoney(totals.amountIncl)}`} />
          {actual ? (
            <>
              <SumCell label="成本" value={`$${fmtMoney(totals.cost)}`} />
              <SumCell
                label="毛利"
                title="毛利 = 未稅金額 − 成本"
                value={`$${fmtMoney(totals.profit)}`}
                negative={totals.profit < 0}
              />
            </>
          ) : (
            <SumCell label="業務員成本" value={`$${fmtMoney(totals.staffCost)}`} />
          )}
          <SumCell
            label="業務員毛利"
            title="業務員毛利 = 未稅金額 − 業務員成本"
            value={`$${fmtMoney(totals.staffProfit)}`}
            negative={totals.staffProfit < 0}
          />
          {returnOrders.length > 0 && (
            <>
              <SumCell
                label="銷退"
                title={`期間內退回 ${returnOrders.length} 張(列在退的那一天);前面幾格沒有扣掉這個數字`}
                value={`$${fmtMoney(backTotals.amountIncl)}`}
                negative
              />
              <SumCell label="淨額" title="含稅金額 − 銷退" value={`$${fmtMoney(net.amount)}`} negative={net.amount < 0} />
              {actual && (
                <SumCell label="淨毛利" title="毛利 − 銷退的毛利" value={`$${fmtMoney(net.profit)}`} negative={net.profit < 0} />
              )}
              <SumCell
                label="業務員淨毛利"
                title="業務員毛利 − 銷退的業務員毛利"
                value={`$${fmtMoney(net.staffProfit)}`}
                negative={net.staffProfit < 0}
              />
            </>
          )}
          {voidOrders.length > 0 && (
            <SumCell label="作廢" value={`${voidOrders.length} 筆`} negative />
          )}
        </div>
      </Toolbar>
      {cut && <Banner kind="error" message={cut} />}
      {/* 桌機:整排只有一行(欄名收起來,靠框裡的字);手機:一項一排、欄名在上面 */}
      <div className="list-filterbar sd-filter">
        <div className="sd-filter-group sd-filter-dates">
          <label className="sd-field">
            <span className="sd-label">起日</span>
            <input
              type="date"
              aria-label="起日"
              value={from}
              onChange={(e) => setFrom(e.target.value)}
            />
          </label>
          <span className="sd-range-sep">~</span>
          <label className="sd-field">
            <span className="sd-label">迄日</span>
            <input
              type="date"
              aria-label="迄日"
              value={to}
              onChange={(e) => setTo(e.target.value)}
            />
          </label>
        </div>

        <div className="sd-filter-group sd-filter-quick">
          {/* 今天、昨天、本月、上月,按了直接查(全站檢視 E10:各報表同一組) */}
          <PeriodQuick
            onPick={(f, t) => {
              setFrom(f);
              setTo(t);
              runQuery({ from: f, to: t });
            }}
          />
        </div>

        <div className="sd-filter-group sd-filter-people">
          <label className="sd-field">
            <span className="sd-label">門市</span>
            {defaultWarehouse.locked ? (
              <input
                value={defaultWarehouse.name || "(未設定)"}
                disabled
                title="此帳號鎖定於此門市"
              />
            ) : (
              <StoreSelect
                value={warehouse}
                onChange={(id, name) => {
                  setWarehouse(id);
                  setWarehouseOpt(id === "" ? null : { id, label: name, secondary: "" });
                }}
              />
            )}
          </label>
          <label className="sd-field">
            <span className="sd-label">業務員</span>
            <ComboBox<SalesPerson>
              value={salesPerson}
              selectedOption={salesPersonOpt}
              onChange={(id, opt) => {
                setSalesPerson(id);
                setSalesPersonOpt(opt ?? null);
              }}
              fetchOptions={searchSalesPersons}
              placeholder="全部業務員"
            />
          </label>
          <label className="sd-field">
            <span className="sd-label">來源</span>
            <ComboBox<Customer>
              value={customer}
              selectedOption={customerOpt}
              onChange={(id, opt) => {
                setCustomer(id);
                setCustomerOpt(opt ?? null);
              }}
              fetchOptions={searchCustomers}
              placeholder="全部來源"
            />
          </label>
          <label className="sd-field">
            <span className="sd-label">會員</span>
            <ComboBox<Member>
              value={member}
              selectedOption={memberOpt}
              onChange={(id, opt) => {
                setMember(id);
                setMemberOpt(opt ?? null);
              }}
              fetchOptions={searchMembers}
              placeholder="全部會員"
            />
          </label>
          <label className="sd-field">
            <span className="sd-label">商品</span>
            <input
              type="text"
              aria-label="商品"
              value={search}
              placeholder="品號 / 品名 / 序號"
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.nativeEvent.isComposing) runQuery();
              }}
            />
          </label>
          {data?.searching && (
            <label className="sd-field sd-whole" title="把同一張單的其他行一起列出來(合計跟著變成整張單的)">
              <input type="checkbox" checked={whole} onChange={(e) => setWhole(e.target.checked)} />
              整張單
            </label>
          )}
        </div>

        <div className="sd-filter-group sd-filter-actions">
          <button
            type="button"
            className="btn primary"
            onClick={() => runQuery()}
            disabled={!ready}
            title={ready ? undefined : "起日不能晚於迄日"}
          >
            查詢
          </button>
          <button type="button" className="btn" onClick={resetFilters}>
            清除
          </button>
        </div>
      </div>

      {/* 零件調貨另外一排(有零件才出現);商品的合計在標題旁邊 */}
      {(totals.partsLines > 0 || backTotals.partsLines > 0) && (
        <div className="sd-strip sd-strip-parts" title="零件調貨獨立列計,不污染商品毛利">
          <StripItem label="零件調貨" value={String(totals.partsLines)} />
          <StripItem label="含稅金額" value={`$${fmtMoney(totals.partsAmount)}`} />
          {actual ? (
            <>
              <StripItem label="成本" value={`$${fmtMoney(totals.partsCost)}`} />
              <StripItem
                label="毛利"
                value={`$${fmtMoney(totals.partsProfit)}`}
                negative={totals.partsProfit < 0}
              />
            </>
          ) : (
            <StripItem label="業務員成本" value={`$${fmtMoney(totals.partsStaffCost)}`} />
          )}
          <StripItem
            label="業務員毛利"
            value={`$${fmtMoney(totals.partsStaffProfit)}`}
            negative={totals.partsStaffProfit < 0}
          />
          {backTotals.partsLines > 0 && (
            <StripItem label="銷退" value={`$${fmtMoney(backTotals.partsAmount)}`} negative />
          )}
        </div>
      )}

      <div className="report-table sd-table">
        {isLoading && <div className="md-empty">載入中…</div>}
        {isError && <div className="md-empty">{errorText(error)}</div>}
        {!isLoading && !isError && (
          <>
            {isMobile ? (
              <SalesReportMobileList orders={activeOrders} voided={false} />
            ) : (
              <SalesReportTable orders={activeOrders} voided={false} day={day} />
            )}
            {returnOrders.length > 0 && (
              <>
                <div className="report-void-header sd-return-header">
                  銷退單據　{returnOrders.length} 張
                </div>
                {isMobile ? (
                  <SalesReportMobileList orders={returnOrders} voided={false} returned />
                ) : (
                  <SalesReportTable orders={returnOrders} voided={false} returned day={day} />
                )}
              </>
            )}
            {voidOrders.length > 0 && (
              <>
                <div className="report-void-header">作廢單據</div>
                {isMobile ? (
                  <SalesReportMobileList orders={voidOrders} voided={true} />
                ) : (
                  <SalesReportTable orders={voidOrders} voided={true} day={day} />
                )}
              </>
            )}
            {nothing && <div className="md-empty">查無資料</div>}
          </>
        )}
      </div>
    </div>
  );
}

function SalesReportMobileList({ orders, voided, returned }: ReportTableProps) {
  const actual = useSeesActualCost();
  if (orders.length === 0) return null;
  return (
    <div className="report-mobile-list">
      {orders.map((o) => {
        const hasMarginItem = o.items.some(itemCountsMargin);
        const orderProfit = o.items.reduce(
          (s, it) => s + itemGrossProfit(it),
          0,
        );
        // 客人付的(手機回補那一行不算;複審抓到這裡原本直接加總全部明細)
        const orderAmount = orderPaidAmount(o);
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
              {customerText(o)}
              {voided && <span className="report-card-badge">作廢</span>}
              {returned && (
                <span className="report-card-badge">銷退{o.original_so_no ? ` ${o.original_so_no}` : ""}</span>
              )}
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
                const profit = itemGrossProfit(it);
                const serials = serialList(it);
                return (
                  <div key={it.id} className="report-card-item">
                    <div className="report-card-item-name">
                      {it.product_name}
                      {it.product_warehouse_type === "parts" && (
                        <span className="sd-parts-badge"> 零件調貨</span>
                      )}
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
                    {countsMargin && !actual ? (
                      <div className="report-card-item-cost">
                        業務員成本 ${fmtMoney(staffCostOf(it))}
                        <span className="report-card-sep">·</span>
                        業務員毛利 ${fmtMoney(itemStaffProfit(it))}
                      </div>
                    ) : countsMargin ? (
                      <div className="report-card-item-cost">
                        成本 ${fmtMoney(Number(it.cost_at_post ?? 0))}
                        <span className="report-card-sep">·</span>
                        毛利{" "}
                        <span
                          style={{
                            color: profit < 0 ? "var(--danger-text)" : undefined,
                          }}
                        >
                          ${fmtMoney(profit)}
                        </span>
                        <span className="report-card-sep">·</span>
                        業務員毛利 ${fmtMoney(itemStaffProfit(it))}
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
              {actual && (
                <>
                  <span className="report-card-sep">·</span>
                  <span>該單毛利</span>
                  <b
                    style={{
                      color: !hasMarginItem
                        ? "var(--text-dim)"
                        : orderProfit < 0
                        ? "var(--danger-text)"
                        : undefined,
                    }}
                  >
                    {hasMarginItem ? `$${fmtMoney(orderProfit)}` : "—"}
                  </b>
                </>
              )}
              {hasMarginItem && (
                <>
                  <span className="report-card-sep">·</span>
                  <span>業務員毛利</span>
                  <b>
                    ${fmtMoney(o.items.reduce((s, it) => s + itemStaffProfit(it), 0))}
                  </b>
                </>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

interface ReportTableProps {
  orders: DailyOrder[];
  voided: boolean;
  /** 這一塊是銷退(每一行是負的;單號底下寫原銷貨單) */
  returned?: boolean;
}

/** 標題旁邊那張小表格的一格:上面是名稱、下面是數字。 */
function SumCell({
  label,
  value,
  title,
  negative,
}: {
  label: string;
  value: string;
  title?: string;
  negative?: boolean;
}) {
  return (
    <div className="sd-sum-cell" title={title}>
      <span className="sd-sum-label">{label}</span>
      <b className={negative ? "sd-sum-neg" : undefined}>{value}</b>
    </div>
  );
}

/** 零件調貨那一排的一項:小字的名稱 + 粗體的數字。 */
function StripItem({
  label,
  value,
  title,
  negative,
}: {
  label: string;
  value: string;
  title?: string;
  negative?: boolean;
}) {
  return (
    <span className="sd-strip-item" title={title}>
      <span className="sd-strip-label">{label}</span>
      <b className={negative ? "sd-strip-neg" : undefined}>{value}</b>
    </span>
  );
}

function SalesReportTable({
  orders,
  voided,
  returned,
  day,
}: ReportTableProps & { day: (d: string) => string }) {
  const actual = useSeesActualCost();
  if (orders.length === 0) return null;
  return (
    <table className={`report-grid sd-grid ${voided ? "void" : ""}`}>
      <thead>
        <tr>
          <th>日期</th>
          <th>單號</th>
          <th>門市</th>
          <th>業務員</th>
          <th>來源</th>
          <th>商品</th>
          <th>序號</th>
          <th className="num">數量</th>
          <th className="num">單價</th>
          <th className="num">金額</th>
          <th className="num">{actual ? "成本" : "業務員成本"}</th>
          {actual && <th className="num">毛利</th>}
          <th className="num">業務員毛利</th>
        </tr>
      </thead>
      <tbody>
        {orders.map((o) => {
          const hasMarginItem = o.items.some(itemCountsMargin);
          const orderProfit = o.items.reduce(
            (s, it) => s + itemGrossProfit(it),
            0,
          );
          return (
            <ReportOrderGroup
              key={o.id}
              order={o}
              orderProfit={orderProfit}
              hasMarginItem={hasMarginItem}
              returned={returned}
              day={day}
              actual={actual}
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
  returned,
  day,
  actual,
}: {
  order: DailyOrder;
  orderProfit: number;
  hasMarginItem: boolean;
  returned?: boolean;
  day: (d: string) => string;
  /** 看得到實際成本(管理員);其他人:成本那一欄是業務員成本、沒有毛利那一欄 */
  actual: boolean;
}) {
  const orderStaffProfit = order.items.reduce((s, it) => s + itemStaffProfit(it), 0);
  return (
    <>
      {order.items.map((it, idx) => {
        const first = idx === 0;
        const countsMargin = itemCountsMargin(it);
        const profit = itemGrossProfit(it);
        return (
          <tr
            key={it.id}
            className={
              first
                ? "report-row order-first"
                : "report-row order-cont"
            }
          >
            <td title={first ? order.doc_date : undefined}>
              {first ? day(order.doc_date) : ""}
            </td>
            <td title={first && returned && order.original_so_no ? `原銷貨單 ${order.original_so_no}` : undefined}>
              {first ? order.no : ""}
            </td>
            {/* 只寫名稱(代碼在匯出的檔裡有):寬度留給品名 */}
            <td>
              {first ? order.warehouse_name || order.warehouse_code || "" : ""}
            </td>
            <td>{first ? order.sales_person_name ?? "" : ""}</td>
            <td className="sd-customer" title={first ? customerText(order) : undefined}>
              {first ? customerText(order) : ""}
            </td>
            <td className="sd-product">
              {it.product_name}
              {it.product_warehouse_type === "parts" && (
                <span className="sd-parts-badge"> 零件調貨</span>
              )}
            </td>
            <td className="report-serial">{serialList(it)}</td>
            <td className="num">{it.qty}</td>
            <td className="num">{fmtMoney(Number(it.unit_price))}</td>
            <td className="num">{fmtMoney(Number(it.amount))}</td>
            <td className="num">
              {!countsMargin ? "—" : fmtMoney(actual ? Number(it.cost_at_post ?? 0) : staffCostOf(it))}
            </td>
            {actual && (
              <td
                className="num"
                style={{
                  color: !countsMargin
                    ? "var(--text-dim)"
                    : profit < 0
                    ? "var(--danger-text)"
                    : undefined,
                }}
              >
                {countsMargin ? fmtMoney(profit) : "—"}
              </td>
            )}
            <td
              className="num"
              style={{
                color: !countsMargin
                  ? "var(--text-dim)"
                  : itemStaffProfit(it) < 0
                  ? "var(--danger-text)"
                  : undefined,
              }}
            >
              {countsMargin ? fmtMoney(itemStaffProfit(it)) : "—"}
            </td>
          </tr>
        );
      })}
      {/* 只有一行的單,小計就是那一行:不另外佔一列 */}
      {order.items.length > 1 && (
      <tr className="report-row order-subtotal">
        <td colSpan={11} className="num" style={{ textAlign: "right" }}>
          該單小計
        </td>
        {actual && (
          <td
            className="num"
            style={{
              color: !hasMarginItem
                ? "var(--text-dim)"
                : orderProfit < 0
                ? "var(--danger-text)"
                : undefined,
            }}
          >
            {hasMarginItem ? fmtMoney(orderProfit) : "—"}
          </td>
        )}
        <td
          className="num"
          style={{
            color: !hasMarginItem
              ? "var(--text-dim)"
              : orderStaffProfit < 0
              ? "var(--danger-text)"
              : undefined,
          }}
        >
          {hasMarginItem ? fmtMoney(orderStaffProfit) : "—"}
        </td>
      </tr>
      )}
    </>
  );
}
