import { useRef, useState } from "react";

import { useSuppliers, useVendorExchangeDo, useVendorExchanges } from "@/api/hooks";
import { Banner, errorMessageOf } from "@/components/Banner";
import { Toolbar } from "@/components/Toolbar";
import { ArmButton } from "@/components/workbench/ArmButton";
import { toast } from "@/components/workbench/toast";
import {
  codesText,
  cutText,
  EXCHANGE_TABS,
  resultText,
  type ExchangeTab,
  type VendorExchangeRow,
} from "@/lib/vendorExchange";

/**
 * 廠商換貨(owner 2026-10-21:以前調去維修倉、換完再調回門市,門市常漏調回)。
 * 送廠商:刷那一台(可寫瑕疵狀況、換廠商;沒選照進貨單)→ 留在原門市、不能賣。
 * 換回來按「已換貨」、刷回來的那一台(一定要刷:碼一樣 = 同一台;不一樣 = 換成另一台、帳上的碼改成新的)。
 * 規則在伺服器;鎖在門市的帳號只看得到、只動得到自己門市的。
 */
export function VendorExchangesPage() {
  const [tab, setTab] = useState<ExchangeTab>("pending");
  const pending = useVendorExchanges("pending");
  const closed = useVendorExchanges("closed");
  const list = tab === "pending" ? pending : closed;
  const suppliers = useSuppliers();
  const run = useVendorExchangeDo();

  const [code, setCode] = useState("");
  const [note, setNote] = useState("");
  const [supplier, setSupplier] = useState<number | "">("");
  const noteRef = useRef<HTMLInputElement>(null);
  const codeRef = useRef<HTMLInputElement>(null);
  const [backOf, setBackOf] = useState<number | null>(null);
  const [backCode, setBackCode] = useState("");

  async function send() {
    if (!code.trim() || run.isPending) return;
    try {
      const row = await run.mutateAsync({ body: { code: code.trim(), note, supplier } });
      toast(`${row.product.name} 送廠商換貨`, "ok");
      setCode("");
      setNote("");
      setSupplier("");
      codeRef.current?.focus();
    } catch (e) {
      toast(errorMessageOf(e), "err");
    }
  }

  async function back(row: VendorExchangeRow) {
    if (!backCode.trim() || run.isPending) return;
    try {
      const done = await run.mutateAsync({ path: `${row.id}/done/`, body: { code: backCode.trim() } });
      toast(`${done.product.name} ${resultText(done)}`, "ok");
      setBackOf(null);
      setBackCode("");
    } catch (e) {
      toast(errorMessageOf(e), "err");
    }
  }

  const rows = list.data?.results ?? [];
  const cut = cutText(list.data);

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
            placeholder="刷序號"
            onChange={(e) => setCode(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.nativeEvent.isComposing && code.trim()) noteRef.current?.focus();
            }}
          />
        </label>
        <label>
          瑕疵狀況
          <input
            ref={noteRef}
            type="text"
            value={note}
            maxLength={200}
            onChange={(e) => setNote(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.nativeEvent.isComposing) void send();
            }}
          />
        </label>
        <label>
          廠商
          <select value={supplier} onChange={(e) => setSupplier(e.target.value ? Number(e.target.value) : "")}>
            <option value="">照進貨單</option>
            {(suppliers.data ?? []).filter((s) => s.is_active).map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
        </label>
        <button className="btn primary" type="button" disabled={!code.trim() || run.isPending} onClick={() => void send()}>
          送廠商換貨
        </button>
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
                <th>廠商</th>
                <th>瑕疵狀況</th>
                <th>送出人</th>
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
                  <td>{codesText(r.sent_imei, r.sent_sn)}</td>
                  <td>{r.supplier?.name ?? "—"}</td>
                  <td>{r.note || "—"}</td>
                  <td>{r.sent_by}</td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    {backOf === r.id ? (
                      <input
                        type="text"
                        autoFocus
                        value={backCode}
                        placeholder="刷回來的那一台"
                        onChange={(e) => setBackCode(e.target.value)}
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
                            setBackCode("");
                          }}
                        >
                          已換貨
                        </button>{" "}
                        <ArmButton
                          className="btn"
                          label="標錯了"
                          disabled={run.isPending}
                          onConfirm={() =>
                            run.mutateAsync({ path: `${r.id}/cancel/` })
                              .then((x) => toast(`${x.product.name} 回到在庫`, "ok"))
                              .catch((e) => toast(errorMessageOf(e), "err"))
                          }
                        />
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
                <th>結果</th>
                <th>廠商</th>
                <th>送出人</th>
                <th>處理人</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="report-row">
                  <td>{r.sent_at.slice(0, 10)}</td>
                  <td>{r.done_at?.slice(0, 10) ?? "—"}</td>
                  <td>{r.warehouse.name}</td>
                  <td>{r.product.name}</td>
                  <td>{codesText(r.sent_imei, r.sent_sn)}</td>
                  <td>{resultText(r)}</td>
                  <td>{r.supplier?.name ?? "—"}</td>
                  <td>{r.sent_by}</td>
                  <td>{r.done_by}</td>
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
