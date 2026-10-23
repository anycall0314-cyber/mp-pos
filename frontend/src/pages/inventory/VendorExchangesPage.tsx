import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { lookupVendorExchange, useSuppliers, useVendorExchangeDo, useVendorExchanges } from "@/api/hooks";
import { useCurrentUser } from "@/auth/AuthContext";
import { Banner, errorMessageOf } from "@/components/Banner";
import { Toolbar } from "@/components/Toolbar";
import { ArmButton } from "@/components/workbench/ArmButton";
import { toast } from "@/components/workbench/toast";
import { money } from "@/lib/money";
import { isManager } from "@/lib/roles";
import {
  codesText,
  cutText,
  defaultStore,
  EXCHANGE_TABS,
  focusAfterLook,
  qtyText,
  resultText,
  supplierGroups,
  type ExchangeLookup,
  type ExchangeTab,
  type VendorExchangeRow,
} from "@/lib/vendorExchange";

/**
 * 廠商換貨(owner 2026-10-21:以前調去維修倉、換完再調回門市,門市常漏調回)。
 * 送廠商:刷序號或條碼 → 有序號的那一台留在原門市、不能賣;配件填數量、從門市數量扣掉。廠商一定要選
 * (設備照進貨單帶;配件列進過這個品號的廠商,最近的在前,照標籤選)。
 * 換回來按「已換貨」:設備一定要刷回來的那一台;配件填回來幾個(可以分批)。
 * 「不換了」(配件少補 / 不補,沒回來的不加回)只有管理員看得到。規則在伺服器。
 */
export function VendorExchangesPage() {
  const manager = isManager(useCurrentUser()?.profile?.role);
  const [tab, setTab] = useState<ExchangeTab>("pending");
  const pending = useVendorExchanges("pending");
  const closed = useVendorExchanges("closed");
  const list = tab === "pending" ? pending : closed;
  const suppliers = useSuppliers();
  const run = useVendorExchangeDo();

  const [code, setCode] = useState("");
  const [found, setFound] = useState<ExchangeLookup | null>(null);
  const [looking, setLooking] = useState(false);
  const [note, setNote] = useState("");
  const [supplier, setSupplier] = useState<number | "">("");
  const [qty, setQty] = useState("1");
  const [store, setStore] = useState<number | "">("");
  const codeRef = useRef<HTMLInputElement>(null);
  const nextRef = useRef<HTMLInputElement>(null);
  const supplierRef = useRef<HTMLSelectElement>(null);
  const [backOf, setBackOf] = useState<number | null>(null);
  const [backValue, setBackValue] = useState("");

  async function look(given?: string) {
    const c = (given ?? code).trim();
    if (!c || looking) return;
    setLooking(true);
    try {
      const hit = await lookupVendorExchange(c);
      setFound(hit);
      setSupplier(hit.default_supplier ?? "");
      setQty("1");
      setStore(hit.kind === "product" ? defaultStore(hit.stores) : "");
      if (hit.kind === "serial" && !hit.sendable) toast(`這一台${hit.status_label},不能送廠商`, "err");
      const to = focusAfterLook(hit);
      window.setTimeout(() => {
        const el = to === "qty" ? nextRef.current : to === "supplier" ? supplierRef.current : codeRef.current;
        el?.focus();
        if (el instanceof HTMLInputElement) el.select();
      }, 0);
    } catch (e) {
      setFound(null);
      toast(errorMessageOf(e), "err");
    } finally {
      setLooking(false);
    }
  }

  // 序號查詢「已退」那一台按「廠商換貨」帶 ?code= 進來:直接查好那一台(還要選廠商、按送出)
  const [params, setParams] = useSearchParams();
  useEffect(() => {
    const given = params.get("code");
    if (!given) return;
    setParams({}, { replace: true });
    setCode(given);
    look(given);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function reset() {
    setCode("");
    setFound(null);
    setNote("");
    setSupplier("");
    setQty("1");
    setStore("");
    codeRef.current?.focus();
  }

  const ready =
    !!found &&
    supplier !== "" &&
    (found.kind === "serial" ? found.sendable : store !== "" && Number(qty) >= 1);

  async function send() {
    if (!found || !ready || run.isPending) return;
    const body =
      found.kind === "serial"
        ? { serial: found.serial, supplier, note }
        : { product: found.product.id, warehouse: store, qty: Number(qty), supplier, note };
    try {
      const row = await run.mutateAsync({ body });
      toast(`${row.product.name} ×${row.qty} 送廠商換貨`, "ok");
      reset();
    } catch (e) {
      toast(errorMessageOf(e), "err");
    }
  }

  async function back(row: VendorExchangeRow) {
    if (run.isPending) return;
    const value = backValue.trim();
    // 設備:一定要刷回來的那一台(紅隊);配件:回來幾個,空的 = 剩下的全部
    if (row.kind === "serial" && !value) return;
    const body = row.kind === "serial" ? { code: value } : value ? { qty: Number(value) } : {};
    try {
      const done = await run.mutateAsync({ path: `${row.id}/done/`, body });
      toast(`${done.product.name} ${done.status === "pending" ? `回來 ${done.back_qty} 個` : resultText(done)}`, "ok");
      setBackOf(null);
      setBackValue("");
    } catch (e) {
      toast(errorMessageOf(e), "err");
    }
  }

  const act = (path: string, ok: (r: VendorExchangeRow) => string) =>
    run.mutateAsync({ path }).then((r) => toast(ok(r), "ok")).catch((e) => toast(errorMessageOf(e), "err"));

  const rows = list.data?.results ?? [];
  const cut = cutText(list.data);
  const groups = supplierGroups(found?.suppliers ?? [], (suppliers.data ?? []).filter((s) => s.is_active));

  return (
    <div className="page sr-page">
      <Toolbar title="廠商換貨">
        <div className="ia-tabs">
          {EXCHANGE_TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              className={`ia-tab${tab === t.key ? " active" : ""}`}
              onClick={() => setTab(t.key)}
            >
              {t.label}
              {t.key === "pending" && (pending.data?.count ?? 0) > 0 && (
                <span className="ia-tab-badge">{pending.data?.count}</span>
              )}
            </button>
          ))}
        </div>
      </Toolbar>

      <div className="list-filterbar sr-filter">
        <label>
          送廠商
          <input
            ref={codeRef}
            type="text"
            value={code}
            placeholder="刷序號或條碼"
            onChange={(e) => {
              setCode(e.target.value);
              setFound(null);
            }}
            onKeyDown={(e) => {
              if (e.key !== "Enter" || e.nativeEvent.isComposing) return;
              // 刷到之後碼沒改過(改了 found 就清掉)、設備、可以送:再按一次 Enter = 送出
              if (found?.kind === "serial" && ready) void send();
              else void look();
            }}
          />
        </label>
        {found && <span className="sr-only-one">{found.product.name}</span>}
        {found?.kind === "serial" && found.warehouse && <span className="sr-only-one">{found.warehouse.name}</span>}
        {found?.kind === "product" && (
          <>
            <label>
              門市
              <select value={store} onChange={(e) => setStore(e.target.value ? Number(e.target.value) : "")}>
                {found.stores.map((s) => (
                  <option key={s.id} value={s.id}>{`${s.name}(${s.qty})`}</option>
                ))}
              </select>
            </label>
            <label>
              數量
              <input
                ref={nextRef}
                type="number"
                min={1}
                value={qty}
                style={{ width: 70 }}
                onChange={(e) => setQty(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.nativeEvent.isComposing) void send();
                }}
              />
            </label>
          </>
        )}
        {found && (
          <>
            <label>
              廠商
              <select ref={supplierRef} value={supplier} onChange={(e) => setSupplier(e.target.value ? Number(e.target.value) : "")}>
                <option value="">選廠商</option>
                {groups.hinted.length > 0 && (
                  <optgroup label="進過">
                    {groups.hinted.map((s) => (
                      <option key={s.id} value={s.id}>{`${s.name} ${s.last}`}</option>
                    ))}
                  </optgroup>
                )}
                <optgroup label={groups.hinted.length > 0 ? "其他" : "全部"}>
                  {groups.others.map((s) => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </optgroup>
              </select>
            </label>
            <label>
              瑕疵狀況
              <input
                type="text"
                value={note}
                maxLength={200}
                onChange={(e) => setNote(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.nativeEvent.isComposing) void send();
                }}
              />
            </label>
            <button className="btn primary" type="button" disabled={!ready || run.isPending} onClick={() => void send()}>
              送廠商換貨
            </button>
          </>
        )}
      </div>

      {list.isError && <Banner kind="error" message={errorMessageOf(list.error)} />}
      <div className="report-table sr-table">
        {list.isLoading && <div className="md-empty">載入中…</div>}
        {list.data && rows.length === 0 && (
          <div className="md-empty">{tab === "pending" ? "沒有在廠商換貨的" : "還沒有處理過的"}</div>
        )}
        {rows.length > 0 && tab === "pending" && (
          <table className="report-grid">
            <thead>
              <tr>
                <th>送出日</th>
                <th className="num">天數</th>
                <th>門市</th>
                <th>品名</th>
                <th>序號</th>
                <th className="num">數量</th>
                <th>廠商</th>
                <th>瑕疵狀況</th>
                <th>送出人</th>
                {manager && <th className="num">成本</th>}
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="report-row">
                  <td>{r.sent_at.slice(0, 10)}</td>
                  <td className="num">{r.days}</td>
                  <td>{r.warehouse.name}</td>
                  <td>{r.product.name}</td>
                  <td>{r.kind === "serial" ? codesText(r.sent_imei, r.sent_sn) : "—"}</td>
                  <td className="num">{qtyText(r)}</td>
                  <td>{r.supplier?.name ?? "—"}</td>
                  <td>{r.note || "—"}</td>
                  <td>{r.sent_by}</td>
                  {manager && <td className="num">{money(r.amount ?? "0")}</td>}
                  <td style={{ whiteSpace: "nowrap" }}>
                    {backOf === r.id ? (
                      <input
                        type={r.kind === "serial" ? "text" : "number"}
                        autoFocus
                        min={1}
                        value={backValue}
                        style={r.kind === "serial" ? undefined : { width: 70 }}
                        placeholder={r.kind === "serial" ? "刷回來的那一台" : String(r.qty - r.back_qty)}
                        onChange={(e) => setBackValue(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && !e.nativeEvent.isComposing) void back(r);
                          if (e.key === "Escape") setBackOf(null);
                        }}
                      />
                    ) : (
                      <>
                        <button
                          className="btn"
                          type="button"
                          disabled={run.isPending}
                          onClick={() => {
                            setBackOf(r.id);
                            setBackValue("");
                          }}
                        >
                          已換貨
                        </button>
                        {r.back_qty === 0 && (
                          <>
                            {" "}
                            <ArmButton
                              className="btn"
                              label="標錯了"
                              disabled={run.isPending}
                              onConfirm={() => act(`${r.id}/cancel/`, (x) => `${x.product.name} 回到在庫`)}
                            />
                          </>
                        )}
                        {manager && r.kind === "product" && (
                          <>
                            {" "}
                            <ArmButton
                              className="btn"
                              label="不換了"
                              disabled={run.isPending}
                              onConfirm={() => act(`${r.id}/unreturned/`, (x) => `${x.product.name} ${resultText(x)}`)}
                            />
                          </>
                        )}
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {rows.length > 0 && tab === "closed" && (
          <table className="report-grid">
            <thead>
              <tr>
                <th>送出日</th>
                <th>處理日</th>
                <th>門市</th>
                <th>品名</th>
                <th>送出的序號</th>
                <th className="num">數量</th>
                <th>結果</th>
                <th>廠商</th>
                <th>送出人</th>
                <th>處理人</th>
                {manager && <th className="num">少回成本</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="report-row">
                  <td>{r.sent_at.slice(0, 10)}</td>
                  <td>{r.done_at?.slice(0, 10) ?? "—"}</td>
                  <td>{r.warehouse.name}</td>
                  <td>{r.product.name}</td>
                  <td>{r.kind === "serial" ? codesText(r.sent_imei, r.sent_sn) : "—"}</td>
                  <td className="num">{r.qty}</td>
                  <td>{resultText(r)}</td>
                  <td>{r.supplier?.name ?? "—"}</td>
                  <td>{r.sent_by}</td>
                  <td>{r.done_by}</td>
                  {manager && <td className="num">{r.status === "unreturned" ? money(r.amount ?? "0") : "—"}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {cut && <div className="md-empty">{cut}</div>}
      </div>
    </div>
  );
}
