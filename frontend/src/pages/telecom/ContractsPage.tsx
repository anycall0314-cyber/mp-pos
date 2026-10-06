import { Fragment, useEffect, useRef, useState } from "react";
import { NavLink } from "react-router-dom";

import type { ContractRow, ContractTab, FollowStatus } from "@/api/contracts";
import { useCarriers, useContractFollowUp, useContracts, useWarehouses } from "@/api/hooks";
import { useDefaultWarehouse } from "@/auth/AuthContext";
import { apiErrorText } from "@/components/workbench/errors";
import { toast } from "@/components/workbench/toast";
import { useIsMobile } from "@/hooks/useIsMobile";
import {
  cursorOf,
  hasNextPage,
  hasPrevPage,
  inTab,
  keepSaved,
  keptRows,
  type KeptRows,
  settleDraft,
} from "@/lib/contractList";

/**
 * 合約到期:門號合約快到期(或已經過期還沒續)的客人名單,打電話用。
 *
 * 四個分頁:待聯絡(還沒處理、到期日在「今天 + 設定的月數」以內)/ 已聯絡 / 不續約 / 已續約。
 * 客人續約了(同一個門號在另一張單上有更新的合約)會自己跑到「已續約」,不用人標。
 * 每一筆可以標已聯絡、不續約、寫一句備註(沒聯絡上也可以只存備註);標錯了按「未聯絡」改回來(備註留著)。
 *
 * 這一頁最怕標錯人,所以:
 * - 畫面上的名單不是現在要的那一份時(剛換分頁 / 篩選 / 翻頁、搜尋還沒查)整份不能按。
 * - 標完的那一列留在原地、變淡,不會抽掉讓下面的往上跳;展開的那一列標完也不自己收起來(收起來下面一樣會跳)。
 *   換分頁、換篩選、翻頁,或再點一次同一個分頁才放掉。
 * - 每一列的三顆按鈕(未聯絡 / 已聯絡 / 不續約)位置固定,現在的狀況那一顆亮著、不能按:
 *   標完之後同一個位置還是同一顆,連點兩下不會變成按到另一顆。
 */

const TABS: { key: ContractTab; label: string }[] = [
  { key: "pending", label: "待聯絡" },
  { key: "contacted", label: "已聯絡" },
  { key: "declined", label: "不續約" },
  { key: "renewed", label: "已續約" },
];

const STATE_LABEL: Record<ContractRow["state"], string> = {
  // 跟那一顆按鈕同一個詞(回到還沒處理;到期日還很遠的不一定在「待聯絡」裡)
  open: "未聯絡",
  contacted: "已聯絡",
  declined: "不續約",
  renewed: "已續約",
};

/** 每一列的三顆按鈕(順序固定):按下去送什麼狀態、送完這一筆會是什麼狀況 */
const STATE_BUTTONS: { state: ContractRow["state"]; status: FollowStatus | ""; label: string }[] = [
  { state: "open", status: "", label: "未聯絡" },
  { state: "contacted", status: "contacted", label: "已聯絡" },
  { state: "declined", status: "declined", label: "不續約" },
];

/** 標完留在原地的那一列,狀況用什麼顏色的標籤 */
const STATE_BADGE: Record<ContractRow["state"], string> = {
  open: "wb-badge warn",
  contacted: "wb-badge ok",
  declined: "wb-badge",
  renewed: "wb-badge",
};

/** 待聯絡要看多遠:預設照系統設定;也可以先看遠一點的 */
const RANGES: { key: string; label: string }[] = [
  { key: "", label: "設定範圍" },
  { key: "6", label: "六個月內" },
  { key: "12", label: "一年以內" },
  { key: "all", label: "全部列出" },
];

function leftText(days: number): string {
  if (days < 0) return `過期 ${-days} 天`;
  if (days === 0) return "今天到期";
  return `剩 ${days} 天`;
}

/** 這位客人是誰:有會員看會員(門號是他在用),沒有才看這張單的客戶 */
function who(r: ContractRow): { name: string; phone: string } {
  return r.member_name
    ? { name: r.member_name, phone: r.member_phone }
    : { name: r.customer_name, phone: r.customer_phone };
}

export function ContractsPage() {
  const isMobile = useIsMobile();
  const store = useDefaultWarehouse();
  const warehouses = useWarehouses();
  const carriers = useCarriers();

  const [tab, setTab] = useState<ContractTab>("pending");
  const [range, setRange] = useState("");
  const [warehouse, setWarehouse] = useState<number | "">("");
  const [carrier, setCarrier] = useState<number | "">("");
  const [typed, setTyped] = useState("");
  const [search, setSearch] = useState("");
  /** 翻到哪了:接在哪一列後面 / 排在哪一列前面;null = 最前面那一頁 */
  const [cursor, setCursor] = useState<{ after?: string; before?: string } | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  /** 每一列打到一半、還沒存的備註(收起來、去看別列都還在) */
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  /** 這一頁標過之後的樣子(是第幾次名單的):標完的列留在原地 */
  const [kept, setKept] = useState<KeptRows<ContractRow> | null>(null);
  /** 名單要比這個時間新才能按(自己標完、或要求重抓之後,舊的那一份先鎖著) */
  const [freshAfter, setFreshAfter] = useState(0);

  // 打字停一下才查
  useEffect(() => {
    const handle = window.setTimeout(() => setSearch(typed), 300);
    return () => window.clearTimeout(handle);
  }, [typed]);
  useEffect(() => setCursor(null), [tab, range, warehouse, carrier, search]);

  const months =
    tab !== "pending" || range === "" ? undefined : range === "all" ? ("all" as const) : Number(range);
  const listQ = useContracts({ state: tab, months, warehouse, carrier, search, ...cursor });
  const followUp = useContractFollowUp();
  const data = listQ.data;

  // 現在看的是第幾次名單(`epoch`):條件一換、或人自己要求重整,就是新的一次。
  // 留在原地的那幾列只屬於它那一次 —— 換過條件再換回來是新的一次,不能把舊的那一份再搬出來蓋住新抓的名單
  // (別人剛改回未聯絡的客人會被遮住、翻頁還會把他跳過);標記送出去到回來之間換了名單,回來的結果也不能蓋上去
  const view = JSON.stringify([tab, range, warehouse, carrier, search, cursor]);
  const viewRef = useRef(view);
  const epoch = useRef(0);
  if (viewRef.current !== view) {
    viewRef.current = view;
    epoch.current += 1;
  }
  const mine = keptRows(kept, epoch.current);
  const rows = mine ?? data?.results ?? [];

  // 畫面上的名單不是現在要的那一份:上一份先墊著、搜尋的字還沒查、標完或要求重抓之後還沒回來
  const stale =
    listQ.isPlaceholderData || typed !== search || (!mine && !!data && listQ.dataUpdatedAt < freshAfter);
  const busy = followUp.isPending || stale;

  /** 標完留在原地、已經不屬於這個分頁的那一列(換名單時先墊著的上一份不算) */
  const done = (r: ContractRow) => !!mine && !inTab(r.state, tab);

  // 翻頁:接在畫面最後一列後面 / 排在第一列前面(不用頁碼,前面少了誰都不會漏人)
  const hasNext = !!data && hasNextPage(rows, data.results, data.has_more, tab);
  const hasPrev = !!data && hasPrevPage(rows, data.results, data.has_prev, tab);

  // 翻過去是空的(這一頁的人都處理完了、後面也沒有人):回最前面
  // (不然是「沒有資料」,上面的筆數卻不是 0,人會以為打完了)
  useEffect(() => {
    if (!data || stale || mine) return;
    if (cursor !== null && data.results.length === 0) setCursor(null);
  }, [data, stale, mine, cursor]);

  // 「六個月內」「一年以內」跟系統設定一樣時不列(同一個範圍不出現兩次)
  const ranges = RANGES.filter((r) => !data || r.key !== String(data.remind_months));
  useEffect(() => {
    if (data && range === String(data.remind_months)) setRange("");
  }, [data, range]);

  /** 放掉留在原地的那幾列(接下來是新的一次名單) */
  function forget() {
    epoch.current += 1;
    setKept(null);
    setOpen(null);
  }

  /** 條件沒變、但要看伺服器現在的名單(再點一次同一個分頁):重抓,回來之前先鎖著 */
  function reload() {
    forget();
    setFreshAfter(Date.now());
    void listQ.refetch();
  }

  function goto(to: { after?: string; before?: string } | null) {
    if (JSON.stringify(to) === JSON.stringify(cursor)) {
      reload();
      return;
    }
    forget();
    setCursor(to);
  }

  /** 這一列現在的備註:打到一半的優先,沒有就是存好的那一句 */
  const noteOf = (r: ContractRow) => drafts[r.id] ?? r.follow?.note ?? "";
  const unsaved = (r: ContractRow) => noteOf(r).trim() !== (r.follow?.note ?? "");

  /** 送出這一列的狀況與備註(備註一律送這一列現在的:按「已聯絡」會把打好的備註一起存) */
  async function mark(r: ContractRow, status: FollowStatus | "", done: string) {
    const at = epoch.current;
    const shown = rows;
    const sent = noteOf(r);
    try {
      const saved = await followUp.mutateAsync({ id: r.id, status, note: sent });
      setFreshAfter(Date.now());
      // 用回來的那一筆換掉這一列,其他列原地不動(展開的也不收:收起來下面的會往上跳)
      setKept((cur) => keepSaved(cur, epoch.current, at, shown, saved));
      // 送出之後又補打的字不是這一次存的:留著(那一格會標「未存」),不能跟著清掉
      setDrafts((cur) => settleDraft(cur, r.id, sent));
      toast(`${r.msisdn} ${done}`, "ok");
    } catch (e) {
      toast(apiErrorText(e), "err");
    }
  }

  /**
   * 這一筆的三顆按鈕。位置固定、現在的狀況那一顆亮著不能按:
   * 標完之後同一個位置還是同一顆(已經不能按),連點兩下不會變成按到旁邊那一顆。
   */
  function actions(r: ContractRow) {
    if (r.state === "renewed") return null;
    return (
      <>
        {STATE_BUTTONS.map((b) => {
          const current = r.state === b.state;
          return (
            <button
              key={b.state}
              type="button"
              className={`wb-btn small ct-state${current ? " on" : ""}`}
              aria-pressed={current}
              disabled={busy || current}
              title={b.status === "" ? "標錯了:改回未聯絡,備註留著" : undefined}
              onClick={(e) => {
                e.stopPropagation();
                void mark(r, b.status, b.label);
              }}
            >
              {b.label}
            </button>
          );
        })}
      </>
    );
  }

  function detail(r: ContractRow) {
    return (
      <div className="ct-detail" onClick={(e) => e.stopPropagation()}>
        <div className="wb-dim wb-small">
          <NavLink to={`/sales/${r.so_id}`} className="wb-link">
            {r.so_no}
          </NavLink>
          {" · "}開單 {r.doc_date}
          {r.activation_date ? ` · 起算 ${r.activation_date}` : ""}
          {r.contract_months ? ` · 綁約 ${r.contract_months} 個月` : ""}
          {r.sales_person_name ? ` · 業務 ${r.sales_person_name}` : ""}
          {r.member_name && r.customer_name && r.customer_name !== r.member_name
            ? ` · 客戶 ${r.customer_name}`
            : ""}
        </div>
        {r.follow && (
          <div className="wb-dim wb-small">
            {r.follow.by} {r.follow.at.slice(0, 10)} {r.follow.status ? "標的" : "記的"}
          </div>
        )}
        {r.state !== "renewed" && (
          <div className="ct-note">
            <input
              value={noteOf(r)}
              maxLength={200}
              placeholder="備註"
              aria-label="備註"
              onChange={(e) => setDrafts((cur) => ({ ...cur, [r.id]: e.target.value }))}
            />
            <button
              type="button"
              className="wb-btn small"
              disabled={busy || !unsaved(r)}
              onClick={() => void mark(r, r.follow?.status ?? "", "備註已存")}
            >
              存備註
            </button>
            {actions(r)}
          </div>
        )}
      </div>
    );
  }

  /** 還剩幾天。標完留在原地的那一列改顯示它現在的狀況;已經續約的,舊約還剩幾天不重要了 */
  const left = (r: ContractRow) =>
    done(r) ? (
      <span className={STATE_BADGE[r.state]}>{STATE_LABEL[r.state]}</span>
    ) : r.state === "renewed" ? (
      <span className="wb-dim">已續約</span>
    ) : (
      <span className={r.days_left < 0 ? "wb-badge bad" : r.days_left <= 30 ? "wb-badge warn" : ""}>
        {leftText(r.days_left)}
      </span>
    );

  /** 備註那一格:打了還沒存的要看得出來(按那一列的按鈕會一起存) */
  const noteCell = (r: ContractRow) =>
    unsaved(r) ? <span className="ct-unsaved">{noteOf(r)}(未存)</span> : (r.follow?.note ?? "");

  return (
    <div className="wb">
      <div className="wb-section ws-list-bar ct-bar">
        <div className="wb-chips">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              className={`wb-chip cat${tab === t.key ? " on" : ""}`}
              onClick={() => {
                // 再點一次同一個分頁 = 把標完的那幾列收掉、重抓現在的名單
                if (t.key === tab) {
                  reload();
                } else {
                  setTab(t.key);
                  forget();
                }
              }}
            >
              {t.label}
              {data ? ` ${data.counts[t.key]}` : ""}
            </button>
          ))}
        </div>
        <span className="ws-grow" />
        {tab === "pending" && (
          <select value={range} aria-label="看到多遠" onChange={(e) => setRange(e.target.value)}>
            {ranges.map((r) => (
              <option key={r.key} value={r.key}>
                {r.key === "" && data ? `${data.remind_months} 個月內` : r.label}
              </option>
            ))}
          </select>
        )}
        <select
          value={carrier}
          aria-label="電信業者"
          onChange={(e) => setCarrier(e.target.value ? Number(e.target.value) : "")}
        >
          <option value="">全部電信</option>
          {(carriers.data ?? []).map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        {!store.locked && (
          <select
            value={warehouse}
            aria-label="門市"
            onChange={(e) => setWarehouse(e.target.value ? Number(e.target.value) : "")}
          >
            <option value="">全部門市</option>
            {(warehouses.data ?? []).map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
        )}
        <input
          type="search"
          className="ct-search"
          value={typed}
          placeholder="門號 / 姓名 / 電話"
          aria-label="搜尋"
          onChange={(e) => setTyped(e.target.value)}
        />
      </div>

      {tab === "pending" && data && !listQ.isError && data.counts.overdue > 0 && (
        <div className="wb-warn ct-overdue">已過期還沒續 {data.counts.overdue} 筆</div>
      )}
      {listQ.isError && <div className="wb-warn err">載入失敗:{apiErrorText(listQ.error)}</div>}

      {isMobile && !listQ.isError && (
        <div className={`wb-inv-cards${stale ? " ct-stale" : ""}`} aria-busy={stale}>
          {listQ.isLoading && <div className="wb-card wb-dim">載入中…</div>}
          {!listQ.isLoading && rows.length === 0 && <div className="wb-card wb-dim">沒有資料</div>}
          {rows.map((r) => {
            const c = who(r);
            return (
              <div
                key={r.id}
                className={`wb-card wb-inv-card${done(r) ? " ct-done" : ""}`}
                onClick={() => setOpen(open === r.id ? null : r.id)}
              >
                <div className="wb-xfer-card-head">
                  <span className="pname">{r.msisdn}</span>
                  {left(r)}
                  <span className="wb-dim wb-small">{r.contract_end}</span>
                </div>
                <div>
                  {c.name}
                  {c.phone && c.phone !== r.msisdn ? ` ${c.phone}` : ""}
                  <span className="wb-dim">
                    {" "}
                    · {r.carrier_name} {r.plan_name}
                  </span>
                </div>
                {(r.follow?.note || unsaved(r)) && (
                  <div className="wb-dim wb-small ct-card-note">{noteCell(r)}</div>
                )}
                {open === r.id ? (
                  detail(r)
                ) : (
                  <div className="wb-detail-actions">{actions(r)}</div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {!isMobile && !listQ.isError && (
        <table className={`wb-table ct-table${stale ? " ct-stale" : ""}`} aria-busy={stale}>
          <thead>
            <tr>
              <th>到期日</th>
              <th>還剩</th>
              <th>門號</th>
              <th>客人</th>
              <th>電信 / 方案</th>
              <th>門市</th>
              <th>備註</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {listQ.isLoading && (
              <tr>
                <td colSpan={8} className="empty">
                  載入中…
                </td>
              </tr>
            )}
            {!listQ.isLoading && rows.length === 0 && (
              <tr>
                <td colSpan={8} className="empty">
                  沒有資料
                </td>
              </tr>
            )}
            {rows.map((r) => {
              const c = who(r);
              return (
                <Fragment key={r.id}>
                  <tr
                    className={`clickable${done(r) ? " ct-done" : ""}`}
                    onClick={() => setOpen(open === r.id ? null : r.id)}
                  >
                    <td className="wb-mono">{r.contract_end}</td>
                    <td className="ct-fit">{left(r)}</td>
                    <td className="wb-mono">{r.msisdn}</td>
                    <td>
                      {c.name}
                      {c.phone && c.phone !== r.msisdn && (
                        <span className="wb-dim wb-small"> {c.phone}</span>
                      )}
                    </td>
                    <td>
                      {r.carrier_name}
                      <span className="wb-dim wb-small"> {r.plan_name}</span>
                    </td>
                    <td className="ct-fit">{r.warehouse_name}</td>
                    <td className="wb-dim wb-small ct-note-cell">{noteCell(r)}</td>
                    <td className="ct-actions">{open === r.id ? null : actions(r)}</td>
                  </tr>
                  {open === r.id && (
                    <tr className="detail">
                      <td colSpan={8}>{detail(r)}</td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      )}

      {!listQ.isError && data && (hasPrev || hasNext) && (
        <div className="ct-pages">
          <button
            type="button"
            className="wb-btn small"
            disabled={busy || !hasPrev}
            onClick={() => goto(rows.length > 0 ? { before: cursorOf(rows[0]) } : null)}
          >
            上一頁
          </button>
          <span className="wb-dim">共 {data.total} 筆</span>
          <button
            type="button"
            className="wb-btn small"
            disabled={busy || !hasNext}
            onClick={() => goto({ after: cursorOf(rows[rows.length - 1]) })}
          >
            下一頁
          </button>
        </div>
      )}
    </div>
  );
}
