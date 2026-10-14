import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { useStockCount, useStockCountDo } from "@/api/hooks";
import type { Product } from "@/api/types";
import { searchProducts } from "@/api/search";
import { Banner, errorMessageOf } from "@/components/Banner";
import { ComboBox, type ComboOption } from "@/components/ComboBox";
import { Toolbar } from "@/components/Toolbar";
import { ArmButton } from "@/components/workbench/ArmButton";
import { isNegative } from "@/lib/fixedReports";
import { money } from "@/lib/money";
import {
  amountCards,
  approveBody,
  assignProduct,
  countedQty,
  extraText,
  missingText,
  movedHint,
  newEditOf,
  newGroups,
  newResult,
  progressText,
  scopeText,
  signed,
  type LineEdit,
  type MissingEdit,
  type NewEdit,
} from "@/lib/stockCount";

/**
 * 一張盤點單。盤點中:配件輸入數到的數量、手機逐台刷,送出。
 * 待核准:管理員看差異(帳上、數到、差多少、金額),每一列可以改調整量或先不調,核准才動庫存。
 * 帳上數量、差異、金額只有管理員的回應裡有;盤的人的畫面沒有那幾欄(伺服器沒給)。
 * 系統不認得的碼(第一次盤點入庫):管理員照舊品名分組勾、指定品號,填成本(舊系統的先帶出來)才入庫;沒指定的不入。
 */
export function StockCountPage() {
  const id = Number(useParams().id);
  const { data: detail, isLoading, isError, error } = useStockCount(id);
  const run = useStockCountDo(id);
  const [code, setCode] = useState("");
  const [product, setProduct] = useState<{ id: number | ""; option: ComboOption<Product> | null }>({ id: "", option: null });
  const [qty, setQty] = useState("");
  const [phonesDone, setPhonesDone] = useState(false);
  const [lineEdits, setLineEdits] = useState<Record<number, LineEdit | undefined>>({});
  const [missingEdits, setMissingEdits] = useState<Record<number, MissingEdit | undefined>>({});
  const [newEdits, setNewEdits] = useState<Record<number, NewEdit | undefined>>({});
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [assignTo, setAssignTo] = useState<{ id: number | ""; option: ComboOption<Product> | null }>({ id: "", option: null });
  const [note, setNote] = useState("");

  if (isLoading) return <div className="page"><div className="md-empty">載入中…</div></div>;
  if (isError || !detail) return <div className="page"><Banner kind="error" message={errorMessageOf(error)} /></div>;

  const counting = detail.status === "counting";
  const submitted = detail.status === "submitted";
  const approved = detail.status === "approved";
  const reviewing = detail.manager && submitted;
  const call = (path: string, body?: object, method: "POST" | "DELETE" = "POST") => {
    setNote("");
    return run.mutateAsync({ path, body, method }).catch(() => undefined);
  };

  async function scan() {
    const text = code.trim();
    if (!text) return;
    const done = await call("scans/", { code: text });
    if (done) setCode("");
  }

  async function saveLine() {
    const n = countedQty(qty);
    if (product.id === "" || n === null) return;
    const done = await call("lines/", { product: product.id, counted_qty: n });
    if (done) {
      setProduct({ id: "", option: null });
      setQty("");
    }
  }

  async function approve() {
    if (!detail) return;
    const body = approveBody(detail, lineEdits, missingEdits, newEdits);
    if ("error" in body) {
      setNote(body.error);
      return;
    }
    await call("approve/", body);
  }

  const lineEdit = (rowId: number, diff: number): LineEdit => lineEdits[rowId] ?? { adjust: String(diff), skipped: false, reason: "" };
  const missingEdit = (rowId: number): MissingEdit => missingEdits[rowId] ?? { skipped: false, reason: "" };
  const newRows = detail.new_rows ?? [];
  const togglePick = (ids: number[], on: boolean) =>
    setPicked((old) => {
      const next = new Set(old);
      for (const one of ids) {
        if (on) next.add(one);
        else next.delete(one);
      }
      return next;
    });
  function assign() {
    const p = assignTo.option?.payload;
    if (!p) return;
    setNewEdits((all) => assignProduct(newRows, picked, { id: p.id, sku: p.sku, name: p.name, unit: !!p.tracks_unit_condition }, all));
    setPicked(new Set());
    setAssignTo({ id: "", option: null });
  }

  return (
    <div className="page sr-page">
      <Toolbar
        title={`盤點 ${detail.no}`}
        actions={
          <>
            <Link className="btn" to="/inventory/stocktake">
              返回
            </Link>
            {(counting || reviewing) && <ArmButton label="作廢" className="btn" onConfirm={() => call("void/")} />}
            {reviewing && <ArmButton label="退回" className="btn" onConfirm={() => call("return/")} />}
            {reviewing && <ArmButton label="核准" className="btn primary" onConfirm={approve} />}
          </>
        }
      />
      <div className="ex-period">
        {detail.warehouse.name}　{scopeText(detail)}　{detail.status_label}　{progressText(detail)}
      </div>
      {run.isError && <Banner kind="error" message={errorMessageOf(run.error)} />}
      {note && <Banner kind="error" message={note} />}

      {counting && (
        <div className="list-filterbar sr-filter">
          <label>
            手機
            <input
              type="text"
              value={code}
              placeholder="刷序號"
              onChange={(e) => setCode(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.nativeEvent.isComposing) void scan();
              }}
            />
          </label>
          <label>
            配件
            <ComboBox<Product>
              value={product.id}
              selectedOption={product.option}
              onChange={(pid, opt) => setProduct({ id: pid, option: opt ?? null })}
              fetchOptions={(q) => searchProducts(q, { activeOnly: true })}
              placeholder="品名 / 條碼"
            />
          </label>
          <label>
            數量
            <input
              type="text"
              inputMode="numeric"
              value={qty}
              onChange={(e) => setQty(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.nativeEvent.isComposing) void saveLine();
              }}
            />
          </label>
          <button className="btn" type="button" disabled={product.id === "" || countedQty(qty) === null || run.isPending} onClick={() => void saveLine()}>
            記下
          </button>
          <label>
            <input type="checkbox" checked={phonesDone} onChange={(e) => setPhonesDone(e.target.checked)} />
            手機全部刷完
          </label>
          <ArmButton label="送出" className="btn primary" onConfirm={() => call("submit/", { phones_done: phonesDone })} />
        </div>
      )}

      {detail.manager && detail.amounts && (submitted || approved) && (
        <div className="sd-summary">
          {amountCards(detail.amounts).map((card) => (
            <div key={card.label} className="sd-summary-card">
              <div className="sd-summary-card-label">{card.label}</div>
              <div className="sd-summary-card-value">{card.value}</div>
            </div>
          ))}
        </div>
      )}

      <div className="report-table sr-table">
        {detail.line_rows.length === 0 && detail.scan_rows.length === 0 && <div className="md-empty">還沒有盤任何東西</div>}
        {detail.line_rows.length > 0 && (
          <table className="report-grid">
            <thead>
              <tr>
                <th>品號</th>
                <th>品名</th>
                {detail.manager && <th className="num">帳上</th>}
                <th className="num">數到</th>
                {detail.manager && <th className="num">差異</th>}
                <th>異動</th>
                {detail.manager && <th className="num">金額</th>}
                {detail.manager && (submitted || approved) && <th className="num">調整</th>}
                {detail.manager && (submitted || approved) && <th>不調</th>}
                {detail.manager && (submitted || approved) && <th>原因</th>}
                {counting && <th />}
              </tr>
            </thead>
            <tbody>
              {detail.line_rows.map((r) => {
                const edit = lineEdit(r.id, r.diff ?? 0);
                const change = (next: Partial<LineEdit>) => setLineEdits((all) => ({ ...all, [r.id]: { ...edit, ...next } }));
                return (
                  <tr key={r.id} className="report-row">
                    <td>{r.product.sku}</td>
                    <td>{r.product.name}</td>
                    {detail.manager && <td className="num">{r.book_qty}</td>}
                    <td className="num">{r.counted_qty}</td>
                    {detail.manager && <td className={(r.diff ?? 0) < 0 ? "num report-neg" : "num"}>{signed(r.diff ?? 0)}</td>}
                    <td>{movedHint(r)}</td>
                    {detail.manager && <td className={isNegative(r.amount) ? "num report-neg" : "num"}>{money(r.amount ?? 0)}</td>}
                    {reviewing && (
                      <>
                        <td className="num">
                          <input type="text" inputMode="numeric" className="sc-adjust" value={edit.adjust} disabled={edit.skipped} onChange={(e) => change({ adjust: e.target.value })} />
                        </td>
                        <td>
                          <input type="checkbox" checked={edit.skipped} onChange={(e) => change({ skipped: e.target.checked })} />
                        </td>
                        <td>
                          <input type="text" value={edit.reason} maxLength={100} onChange={(e) => change({ reason: e.target.value })} />
                        </td>
                      </>
                    )}
                    {detail.manager && approved && (
                      <>
                        <td className="num">{signed(r.adjust_qty ?? 0)}</td>
                        <td>{r.skipped ? "不調" : ""}</td>
                        <td>{r.reason}</td>
                      </>
                    )}
                    {counting && (
                      <td>
                        <button className="btn" type="button" disabled={run.isPending} onClick={() => void call(`lines/${r.id}/`, undefined, "DELETE")}>
                          移除
                        </button>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {detail.scan_rows.length > 0 && (
        <div className="report-table sr-table">
          <table className="report-grid">
            <thead>
              <tr>
                <th>刷到的碼</th>
                <th>品名</th>
                {counting && <th />}
              </tr>
            </thead>
            <tbody>
              {detail.scan_rows.map((s) => (
                <tr key={s.id} className="report-row">
                  <td>{s.code}</td>
                  <td>{s.known ? s.name : s.name || "不認得"}</td>
                  {counting && (
                    <td>
                      <button className="btn" type="button" disabled={run.isPending} onClick={() => void call(`scans/${s.id}/`, undefined, "DELETE")}>
                        移除
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {detail.manager && (detail.missing_rows?.length ?? 0) > 0 && (
        <div className="report-table sr-table">
          <table className="report-grid">
            <thead>
              <tr>
                <th>少的序號</th>
                <th>品名</th>
                <th className="num">成本</th>
                <th>現況</th>
                {reviewing && <th>不調</th>}
                <th>原因</th>
                {approved && <th />}
              </tr>
            </thead>
            <tbody>
              {(detail.missing_rows ?? []).map((m) => {
                const edit = missingEdit(m.id);
                const change = (next: Partial<MissingEdit>) => setMissingEdits((all) => ({ ...all, [m.id]: { ...edit, ...next } }));
                return (
                  <tr key={m.id} className="report-row">
                    <td>{m.serial_no}</td>
                    <td>{m.name}</td>
                    <td className="num">{money(m.cost)}</td>
                    <td>{missingText(m, approved)}</td>
                    {reviewing && (
                      <td>
                        <input type="checkbox" checked={edit.skipped} onChange={(e) => change({ skipped: e.target.checked })} />
                      </td>
                    )}
                    <td>
                      {reviewing ? (
                        <input type="text" value={edit.reason} maxLength={100} onChange={(e) => change({ reason: e.target.value })} />
                      ) : (
                        m.reason
                      )}
                    </td>
                    {approved && <td>{m.applied && !m.found && <ArmButton label="找回" className="btn" onConfirm={() => call(`missing/${m.id}/found/`)} />}</td>}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {detail.manager && newRows.length > 0 && (submitted || approved) && (
        <div className="report-table sr-table">
          {reviewing && (
            <div className="list-filterbar sr-filter">
              <label>
                品號
                <ComboBox<Product>
                  value={assignTo.id}
                  selectedOption={assignTo.option}
                  onChange={(pid, opt) => setAssignTo({ id: pid, option: opt ?? null })}
                  fetchOptions={async (q) => (await searchProducts(q, { activeOnly: true })).filter((o) => o.payload?.requires_serial)}
                  placeholder="品名"
                />
              </label>
              <button className="btn" type="button" disabled={!assignTo.option || picked.size === 0} onClick={assign}>
                指定 {picked.size || ""}
              </button>
            </div>
          )}
          <table className="report-grid">
            <thead>
              <tr>
                {reviewing && <th />}
                <th>新入庫</th>
                <th>舊品名</th>
                <th>品號</th>
                <th className="num">成本</th>
                <th className="num">售價</th>
                <th>{reviewing ? "不入" : "結果"}</th>
              </tr>
            </thead>
            <tbody>
              {newGroups(newRows).map((g) => {
                const ids = g.rows.map((r) => r.id);
                const all = ids.every((one) => picked.has(one));
                return [
                  <tr key={`g-${g.key}`} className="report-row sc-group">
                    {reviewing && (
                      <td>
                        <input type="checkbox" checked={all} aria-label={g.label} onChange={() => togglePick(ids, !all)} />
                      </td>
                    )}
                    <td colSpan={6}>
                      {g.label} {g.rows.length}
                    </td>
                  </tr>,
                  ...g.rows.map((r) => {
                    const edit = newEditOf(r, newEdits);
                    const change = (next: Partial<NewEdit>) => setNewEdits((all2) => ({ ...all2, [r.id]: { ...edit, ...next } }));
                    return (
                      <tr key={r.id} className={picked.has(r.id) ? "report-row vo-picked" : "report-row"}>
                        {reviewing && (
                          <td>
                            <input type="checkbox" checked={picked.has(r.id)} aria-label={r.code} onChange={(e) => togglePick([r.id], e.target.checked)} />
                          </td>
                        )}
                        <td>{r.code}</td>
                        <td>{r.old_name}</td>
                        <td>{(reviewing ? edit.product : r.product)?.name ?? "—"}</td>
                        <td className="num">
                          {reviewing ? (
                            <input type="text" inputMode="decimal" className="sc-adjust" value={edit.cost} disabled={edit.skipped || !edit.product}
                              onChange={(e) => change({ cost: e.target.value })} />
                          ) : r.unit_cost !== null ? money(r.unit_cost) : ""}
                        </td>
                        <td className="num">
                          {reviewing ? (
                            edit.product?.unit && (
                              <input type="text" inputMode="numeric" className="sc-adjust" value={edit.price} disabled={edit.skipped}
                                onChange={(e) => change({ price: e.target.value })} />
                            )
                          ) : r.unit_price !== null ? money(r.unit_price) : ""}
                        </td>
                        <td>
                          {reviewing ? (
                            <input type="checkbox" checked={edit.skipped || !edit.product} disabled={!edit.product}
                              onChange={(e) => change({ skipped: e.target.checked })} />
                          ) : (
                            newResult(r)
                          )}
                        </td>
                      </tr>
                    );
                  }),
                ];
              })}
            </tbody>
          </table>
        </div>
      )}

      {detail.manager && (detail.extra_rows?.length ?? 0) > 0 && (
        <div className="report-table sr-table">
          <table className="report-grid">
            <thead>
              <tr>
                <th>多的碼</th>
                <th>帳上</th>
              </tr>
            </thead>
            <tbody>
              {(detail.extra_rows ?? []).map((e) => (
                <tr key={e.id} className="report-row">
                  <td>{e.code}</td>
                  <td>{extraText(e)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
