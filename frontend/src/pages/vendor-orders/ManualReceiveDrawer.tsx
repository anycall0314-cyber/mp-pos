import { useEffect, useRef, useState } from "react";

import { useManualReceiving, useReceiveVendorOrder, useSaveVendorIssue } from "@/api/hooks";
import { ApiHttpError } from "@/api/client";
import { searchProducts } from "@/api/search";
import type { VendorOrder } from "@/api/types";
import { Banner } from "@/components/Banner";
import { ComboBox } from "@/components/ComboBox";
import { Drawer } from "@/components/Drawer";
import { apiErrorText } from "@/components/workbench/errors";
import { QtyInput } from "@/components/workbench/QtyInput";
import { toast } from "@/components/workbench/toast";
import { money } from "@/lib/money";
import {
  addExtra,
  addable,
  fillAll,
  manualBlocked,
  manualPendingFrom,
  manualPendingOf,
  manualSummary,
  priceOf,
  removeExtra,
  shownLines,
  startManualDraft,
  withManualQty,
  withPrice,
  type ManualDraft,
  type ManualLine,
  type ManualPending,
} from "@/lib/vendorManual";
import {
  MAX_QTY,
  chosen,
  lineTitle,
  newReceiveKey,
  pendingSlot,
  receiveOutcome,
  withProduct,
  withRepick,
} from "@/lib/vendorReceive";

function readPending(orderId: number): ManualPending | null {
  try {
    return manualPendingFrom(sessionStorage.getItem(pendingSlot(orderId)));
  } catch {
    return null;
  }
}

function writePending(orderId: number, pending: ManualPending | null) {
  try {
    if (pending) sessionStorage.setItem(pendingSlot(orderId), JSON.stringify(pending));
    else sessionStorage.removeItem(pendingSlot(orderId));
  } catch {
    /* 存不了就算了:這個面板開著的期間鑰匙還是同一把 */
  }
}

/** 只能入到按數量管的一般商品(伺服器也會擋)。 */
async function pickable(query: string) {
  const found = await searchProducts(query, { activeOnly: true, excludeSecondhand: true });
  return found.map((o) => ({
    ...o,
    disabled: o.disabled || o.payload?.requires_serial === true || o.payload?.is_virtual === true,
  }));
}

/**
 * 半自動廠商的到貨入庫:照**店家叫的這張單**列(廠商沒有系統可以問)。
 * 數量不預先帶(有「全部到齊」);實際單價入庫的人填(先帶參考價);可以填這一次的運費;可以加這張單沒叫的品項(換款、多送)。
 * 比叫的多只提醒、不擋。規則在 lib/vendorManual.ts;「還不知道結果的那一次」跟全自動同一套(先記才送、解決之前只能再送一次)。
 */
export function ManualReceiveDrawer({ order, onClose }: { order: VendorOrder; onClose: () => void }) {
  const plan = useManualReceiving(order.id);
  const receive = useReceiveVendorOrder();
  const saveIssue = useSaveVendorIssue();
  const requestKey = useRef(newReceiveKey());
  const [draft, setDraft] = useState<ManualDraft | null>(null);
  const [refused, setRefused] = useState("");
  const [pending, setPending] = useState<ManualPending | null>(() => readPending(order.id));
  const busy = receive.isPending || saveIssue.isPending;
  const locked = busy || pending !== null;
  const data = plan.data;

  useEffect(() => {
    if (data && draft === null) setDraft(startManualDraft(data, requestKey.current));
  }, [data, draft]);

  const sum = data && draft ? manualSummary(data, draft) : null;

  async function send(what: ManualPending, resend: boolean) {
    if (busy) return;
    writePending(order.id, what);
    setPending(what);
    setRefused("");
    let status: number | null = null;
    let message = "";
    try {
      const got = await receive.mutateAsync({
        order: order.id,
        request_key: what.requestKey,
        lines: what.lines,
        issue_note: what.note,
        freight: what.freight,
      });
      const mine = got.order.receipts.find((r) => r.id === got.receipt);
      writePending(order.id, null);
      toast(`已入庫 ${mine?.qty ?? what.pieces} 個${mine ? `,進貨單 ${mine.purchase_order_no}` : ""}`, "ok");
      onClose();
      return;
    } catch (e) {
      status = e instanceof ApiHttpError ? e.status : null;
      message = apiErrorText(e);
    }
    if (receiveOutcome(status, resend) === "refused") {
      writePending(order.id, null);
      setPending(null);
      setRefused(message);
      plan.refetch();
    } else {
      setRefused(`還不知道有沒有入庫(${message}),請按「再送一次」`);
    }
  }

  function submit() {
    if (!data || !draft || !sum || locked) return;
    const why = manualBlocked(sum);
    if (why) {
      setRefused(why);
      return;
    }
    send(manualPendingOf(draft, sum), false);
  }

  async function noteOnly() {
    if (!draft || locked) return;
    try {
      await saveIssue.mutateAsync({ order: order.id, note: draft.note });
      toast("已記下", "ok");
      onClose();
    } catch (e) {
      setRefused(apiErrorText(e));
    }
  }

  function productCell(line: ManualLine) {
    if (!draft) return null;
    const picked = chosen(line, draft);
    if (line.product && !draft.repick[line.key]) {
      return (
        <span className="vr-fixed">
          入到 {line.product.name}
          <button type="button" className="btn-link" disabled={locked} onClick={() => setDraft(withRepick(draft, line))}>
            改
          </button>
        </span>
      );
    }
    return (
      <ComboBox
        value={picked?.id ?? ""}
        selectedOption={picked ? { id: picked.id, label: picked.label } : null}
        onChange={(id, opt) => setDraft(withProduct(draft, line.key, id === "" || !opt ? null : { id, label: opt.label }))}
        fetchOptions={pickable}
        disabled={locked}
        placeholder="入到哪個品號(品名 / 品號)"
      />
    );
  }

  const more = data && draft ? addable(data, draft) : [];

  return (
    <Drawer
      open
      title={`到貨入庫 ${order.vendor_order_no}`}
      onClose={() => !busy && onClose()}
      lockBackdrop
      width={780}
      footer={
        <>
          <button type="button" className="btn" disabled={locked || !draft} onClick={noteOnly}>
            {saveIssue.isPending ? "儲存中…" : "只記問題"}
          </button>
          {pending ? (
            <button type="button" className="btn primary" disabled={busy} onClick={() => send(pending, true)}>
              {receive.isPending ? "入庫中…" : "再送一次"}
            </button>
          ) : (
            <button type="button" className="btn primary" disabled={busy || !sum || sum.pieces === 0} onClick={submit}>
              {receive.isPending ? "入庫中…" : "確認入庫"}
            </button>
          )}
        </>
      }
    >
      {plan.isLoading && <div className="md-empty">載入這張單…</div>}
      {plan.isError && <Banner kind="error" message={apiErrorText(plan.error)} />}
      {pending && !receive.isPending && !refused && (
        <Banner kind="error" message={`上一次的入庫(${pending.pieces} 個)還不知道有沒有成功,請按「再送一次」`} />
      )}
      {refused && <Banner kind="error" message={refused} />}
      {data && draft && sum && (
        <>
          <div className="vr-head">
            <span>{order.provider_label}</span>
            {data.payment_method === "貨到付款" && <span>貨到付款:記現金</span>}
            <span className="vr-fill">
              <button type="button" className="btn" disabled={locked} onClick={() => setDraft(fillAll(data, draft))}>
                全部到齊
              </button>
            </span>
          </div>
          <table className="report-grid vo-confirm vr-grid">
            <thead>
              <tr>
                <th>品名 / 我的品號</th>
                <th className="num">叫</th>
                <th className="num">已入</th>
                <th className="num">這次</th>
                <th className="num">實際單價</th>
              </tr>
            </thead>
            <tbody>
              {shownLines(data, draft).map((line) => {
                const qty = draft.qty[line.key] ?? 0;
                const extra = draft.added.includes(line.key);
                const priceBad = qty > 0 && priceOf(draft.price[line.key]) === null;
                return (
                  <tr key={line.key} className={qty > 0 ? "vo-picked" : undefined}>
                    <td className="vo-name">
                      {lineTitle(line)}
                      {extra && (
                        <button type="button" className="btn-link vm-drop" disabled={locked} onClick={() => setDraft(removeExtra(draft, line.key))}>
                          拿掉
                        </button>
                      )}
                      <div className="vo-sub">{line.sku}</div>
                      <div className="vr-map">{productCell(line)}</div>
                    </td>
                    <td className="num">{line.qty}</td>
                    <td className="num">{line.received_qty}</td>
                    <td className="num">
                      <QtyInput
                        className="vo-qty"
                        aria-label={`${lineTitle(line)} 這次入庫`}
                        value={qty}
                        min={0}
                        max={MAX_QTY}
                        disabled={locked}
                        onCommit={(n) => setDraft(withManualQty(draft, line.key, n))}
                      />
                      {qty > line.remaining_qty && qty > 0 && <div className="vo-sub vo-diff">比叫的多</div>}
                    </td>
                    <td className="num">
                      <input
                        className={`vo-qty vm-price${priceBad ? " bad" : ""}`}
                        aria-label={`${lineTitle(line)} 實際單價`}
                        inputMode="decimal"
                        value={draft.price[line.key] ?? ""}
                        disabled={locked}
                        placeholder="單價"
                        onChange={(e) => setDraft(withPrice(draft, line.key, e.target.value))}
                      />
                    </td>
                  </tr>
                );
              })}
              <tr className="vo-confirm-total">
                <td colSpan={3}>這次入庫</td>
                <td className="num">{sum.pieces}</td>
                <td className="num">
                  <b>${money(sum.amount)}</b>
                </td>
              </tr>
            </tbody>
          </table>
          <div className="vo-form">
            {more.length > 0 && (
              <label>
                加一項
                <select
                  value=""
                  disabled={locked}
                  onChange={(e) => e.target.value && setDraft(addExtra(data, draft, e.target.value))}
                >
                  <option value="">這張單沒叫的…</option>
                  {more.map((l) => (
                    <option key={l.key} value={l.key}>
                      {lineTitle(l)}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label>
              運費{data.freight_into_cost ? "(算進成本)" : "(不算成本)"}
              <input
                inputMode="numeric"
                value={draft.freight}
                disabled={locked}
                placeholder="0"
                onChange={(e) => setDraft({ ...draft, freight: e.target.value })}
              />
            </label>
            <label className="vo-form-wide">
              到貨問題
              <input
                value={draft.note}
                maxLength={300}
                disabled={locked}
                placeholder="送錯、少到…"
                onChange={(e) => setDraft({ ...draft, note: e.target.value })}
              />
            </label>
          </div>
        </>
      )}
    </Drawer>
  );
}
