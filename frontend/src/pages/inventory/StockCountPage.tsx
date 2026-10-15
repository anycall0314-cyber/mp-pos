import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { useStockCount, useStockCountDo } from "@/api/hooks";
import type { Product } from "@/api/types";
import { searchProducts } from "@/api/search";
import { Banner, errorMessageOf } from "@/components/Banner";
import { ComboBox, type ComboOption } from "@/components/ComboBox";
import { Toolbar } from "@/components/Toolbar";
import { ArmButton } from "@/components/workbench/ArmButton";
import { ScanBox, type ScanBoxApi, type ScanOption } from "@/components/workbench/ScanBox";
import { isNegative } from "@/lib/fixedReports";
import { qrMatrix, qrPath } from "@/lib/qr";
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
  phoneCountUrl,
  phoneStatusText,
  pickProblem,
  progressText,
  recordedQty,
  sameCode,
  scopeText,
  signed,
  type CountUnknown,
  type LineEdit,
  type MissingEdit,
  type NewEdit,
} from "@/lib/stockCount";

/** 手機盤點的 QR Code(手機相機一掃就開 /m/count#憑證) */
function PairQr({ text }: { text: string }) {
  const m = qrMatrix(text);
  return (
    <svg className="ph-qr" viewBox={`0 0 ${m.length} ${m.length}`} role="img" aria-label="手機盤點 QR Code" shapeRendering="crispEdges">
      <rect width={m.length} height={m.length} fill="#fff" />
      <path d={qrPath(m)} fill="#000" />
    </svg>
  );
}

/**
 * 一張盤點單。盤點中:配件輸入數到的數量、手機逐台刷,送出。
 * 配件那一格是工作台的掃碼框:條碼槍刷舊貼紙(舊品號 = 條碼)完全相同才直接選,選好游標跳到數量;刷了沒選到的記在「沒加入」,送出前要處理掉。
 * 手機走動盤點(2026-10-15):「手機盤點」寫稱呼、產生 QR Code(一支手機一個);手機刷進來的數量每 4 秒重抓。
 * 打「數到幾個」存的時候一起送選到那一刻看到的數字,手機在那之後又加過就擋下來、照最新的重新帶(紅隊:不能默默蓋掉手機加的)。
 * 手機刷到、系統不認得的碼列在「沒對到的碼」:指定配件(刷了幾次就加幾個)或寫原因不入,處理好才能送出。
 * 待核准:管理員看差異(帳上、數到、差多少、金額),每一列可以改調整量或先不調,核准才動庫存。
 * 帳上數量、差異、金額只有管理員的回應裡有;盤的人的畫面沒有那幾欄(伺服器沒給)。
 * 系統不認得的碼(第一次盤點入庫):管理員照舊品名分組勾、指定品號,填成本(舊系統的先帶出來)才入庫;沒指定的不入。
 */
export function StockCountPage() {
  const id = Number(useParams().id);
  const { data: detail, isLoading, isError, error, refetch } = useStockCount(id);
  const run = useStockCountDo(id);
  const [code, setCode] = useState("");
  /** 配件那一格選到、還沒記下的商品。另外留一份當下的(`accessoryNow`):掃碼框排隊處理完、送出前要馬上讀,不能等畫面重畫(複審 P1) */
  const [accessory, setAccessoryState] = useState<Product | null>(null);
  const accessoryNow = useRef<Product | null>(null);
  const setAccessory = (p: Product | null) => {
    accessoryNow.current = p;
    setAccessoryState(p);
  };
  const [qty, setQty] = useState("");
  /** 選到配件那一刻,這張單上它數到幾個(null = 還沒有這一列):存的時候一起送,手機在那之後又加過就擋下來(紅隊) */
  const seenQty = useRef<number | null>(null);
  const [phonesDone, setPhonesDone] = useState(false);
  // 手機走動盤點:發 QR Code 的那一塊
  const [phoneOpen, setPhoneOpen] = useState(false);
  const [phoneLabel, setPhoneLabel] = useState("");
  const [pair, setPair] = useState<{ id: number; label: string; token: string } | null>(null);
  // 沒對到的碼:每一筆要指定的配件、不入的原因
  const [unknownPick, setUnknownPick] = useState<Record<number, ComboOption<Product> | undefined>>({});
  const [unknownReason, setUnknownReason] = useState<Record<number, string>>({});
  const [lineEdits, setLineEdits] = useState<Record<number, LineEdit | undefined>>({});
  const [missingEdits, setMissingEdits] = useState<Record<number, MissingEdit | undefined>>({});
  const [newEdits, setNewEdits] = useState<Record<number, NewEdit | undefined>>({});
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [assignTo, setAssignTo] = useState<{ id: number | ""; option: ComboOption<Product> | null }>({ id: "", option: null });
  const [note, setNote] = useState("");
  const scanRef = useRef<HTMLInputElement>(null);
  const qtyRef = useRef<HTMLInputElement>(null);
  const scanApi = useRef<ScanBoxApi | null>(null);
  // 選到配件:游標到數量、整格反白(這張單記過的話先放原本的數量,直接打就換掉)
  useEffect(() => {
    if (!accessory) return;
    qtyRef.current?.focus();
    qtyRef.current?.select();
  }, [accessory]);

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
    const item = accessoryNow.current;
    if (!item) return;
    const n = countedQty(qty);
    if (n === null) {
      // 沒打數量就刷了下一張貼紙:那一串字進了數量這一格,沒有刷進去
      if (qty.trim()) {
        setNote(`先打數量,「${qty.trim()}」要再刷一次`);
        setQty("");
      }
      return;
    }
    const done = await call("lines/", { product: item.id, counted_qty: n, seen: seenQty.current });
    if (done) {
      setAccessory(null);
      setQty("");
      scanRef.current?.focus();
      return;
    }
    // 沒存成(多半是手機剛加過):照最新的數字重新帶,人看過再按一次
    const fresh = (await refetch()).data;
    if (fresh && accessoryNow.current?.id === item.id) {
      seenQty.current = fresh.line_rows.find((r) => r.product.id === item.id)?.counted_qty ?? null;
      setQty(recordedQty(fresh.line_rows, item.id));
    }
  }

  async function newPhone() {
    const label = phoneLabel.trim();
    if (!label) {
      setNote("請寫這支手機是誰在用");
      return;
    }
    const done = await call("phones/", { label });
    if (done?.pair) {
      setPair({ id: done.pair.id, label: done.pair.label, token: done.pair.token });
      setPhoneLabel("");
    }
  }

  async function resolveUnknown(row: CountUnknown, skip: boolean) {
    const product = unknownPick[row.id]?.payload;
    const reason = (unknownReason[row.id] ?? "").trim();
    if (!skip && !product) return;
    if (skip && !reason) {
      setNote("不入要寫原因");
      return;
    }
    await call(`unknowns/${row.id}/`, skip ? { skip: true, reason } : { product: product!.id });
  }

  async function searchAccessories(q: string): Promise<ScanOption<Product>[]> {
    const found = await searchProducts(q, { activeOnly: true });
    return found.flatMap((o) => (o.payload ? [{ key: o.id, code: o.payload.sku, label: o.label, payload: o.payload }] : []));
  }

  function pickAccessory(o: ScanOption<Product>): string | null {
    const why = pickProblem(accessoryNow.current, o.payload);
    if (why) return why;
    setNote("");
    setAccessory(o.payload);
    seenQty.current = detail?.line_rows.find((r) => r.product.id === o.payload.id)?.counted_qty ?? null;
    setQty(detail ? recordedQty(detail.line_rows, o.payload.id) : "");
    return null;
  }

  async function submit() {
    // 等掃碼框排隊的碼處理完,再讀「現在」選著的(不是按下去那一刻畫面上的)
    await scanApi.current?.idle();
    const pending = accessoryNow.current;
    const blocked = scanApi.current?.blocker() ?? (pending ? `「${pending.name}」還沒記下` : null);
    if (blocked) {
      setNote(blocked);
      return;
    }
    await call("submit/", { phones_done: phonesDone });
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
            <input type="checkbox" checked={phonesDone} onChange={(e) => setPhonesDone(e.target.checked)} />
            手機全部刷完
          </label>
          <button className="btn sc-phone-btn" type="button" aria-expanded={phoneOpen} onClick={() => setPhoneOpen((v) => !v)}>
            手機盤點
          </button>
        </div>
      )}
      {counting && phoneOpen && (
        <div className="list-filterbar sr-filter sc-phones">
          <label>
            稱呼
            <input type="text" value={phoneLabel} maxLength={20} placeholder="小王、櫃2" onChange={(e) => setPhoneLabel(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.nativeEvent.isComposing) void newPhone();
              }} />
          </label>
          <button className="btn" type="button" disabled={!phoneLabel.trim() || run.isPending} onClick={() => void newPhone()}>
            產生 QR Code
          </button>
          {pair && (detail.phones ?? []).some((p) => p.id === pair.id && p.status === "waiting") && (
            <div className="sc-qr">
              <PairQr text={phoneCountUrl(window.location.origin, pair.token)} />
              <span>{pair.label}</span>
            </div>
          )}
          {(detail.phones ?? []).map((p) => (
            <span key={p.id} className="sc-phone">
              {p.label} {phoneStatusText(p.status)}
              <button type="button" className="wb-link" onClick={() => void call(`phones/${p.id}/`, undefined, "DELETE")}>
                結束
              </button>
            </span>
          ))}
        </div>
      )}
      {counting && (
        <div className="list-filterbar sr-filter sc-scanrow">
          <label className="sc-scan">
            配件
            <ScanBox<Product>
              inputRef={scanRef}
              apiRef={scanApi}
              placeholder="品名 / 條碼"
              search={searchAccessories}
              isExact={(o, q) => sameCode(o.payload, q)}
              onPick={pickAccessory}
            />
          </label>
          {accessory && (
            <span className="sr-only-one">
              {accessory.sku} {accessory.name}
              <button type="button" aria-label="清掉" onClick={() => setAccessory(null)}>
                ×
              </button>
            </span>
          )}
          <label>
            數量
            <input
              ref={qtyRef}
              type="text"
              inputMode="numeric"
              value={qty}
              onChange={(e) => setQty(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.nativeEvent.isComposing) void saveLine();
              }}
            />
          </label>
          <button className="btn" type="button" disabled={!accessory || countedQty(qty) === null || run.isPending} onClick={() => void saveLine()}>
            記下
          </button>
          <span className="sc-submit">
            <ArmButton label="送出" className="btn primary" onConfirm={submit} />
          </span>
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
        {(detail.unknown_rows ?? []).length > 0 && (
          <table className="report-grid sc-unknowns">
            <thead>
              <tr>
                <th>沒對到的碼</th>
                <th className="num">次數</th>
                <th>刷的人</th>
                <th>處理</th>
              </tr>
            </thead>
            <tbody>
              {(detail.unknown_rows ?? []).map((u) => (
                <tr key={u.id} className="report-row">
                  <td>{u.code}</td>
                  <td className="num">{u.times}</td>
                  <td>{u.label}</td>
                  <td>
                    {u.resolved ? (
                      u.product ? `${u.product.sku} ${u.product.name}` : `不入:${u.reason}`
                    ) : counting ? (
                      <div className="sc-unknown-do">
                        <ComboBox<Product>
                          value={unknownPick[u.id]?.id ?? ""}
                          selectedOption={unknownPick[u.id] ?? null}
                          onChange={(_pid, opt) => setUnknownPick((all) => ({ ...all, [u.id]: opt ?? undefined }))}
                          fetchOptions={async (q) => (await searchProducts(q, { activeOnly: true })).filter((o) => o.payload && !o.payload.requires_serial && !o.payload.is_virtual)}
                          placeholder="品名 / 條碼"
                        />
                        <button className="btn" type="button" disabled={!unknownPick[u.id] || run.isPending} onClick={() => void resolveUnknown(u, false)}>
                          指定
                        </button>
                        <input type="text" maxLength={100} placeholder="原因" value={unknownReason[u.id] ?? ""}
                          onChange={(e) => setUnknownReason((all) => ({ ...all, [u.id]: e.target.value }))} />
                        <button className="btn" type="button" disabled={!(unknownReason[u.id] ?? "").trim() || run.isPending} onClick={() => void resolveUnknown(u, true)}>
                          不入
                        </button>
                      </div>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
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
