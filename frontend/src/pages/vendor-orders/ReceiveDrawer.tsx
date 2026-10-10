import { useEffect, useRef, useState } from "react";

import { useReceiveVendorOrder, useSaveVendorIssue, useVendorReceiving } from "@/api/hooks";
import { ApiHttpError } from "@/api/client";
import { searchProducts } from "@/api/search";
import type { VendorOrder } from "@/api/types";
import { useCurrentUser } from "@/auth/AuthContext";
import { Banner } from "@/components/Banner";
import { ComboBox } from "@/components/ComboBox";
import { Drawer } from "@/components/Drawer";
import { apiErrorText } from "@/components/workbench/errors";
import { QtyInput } from "@/components/workbench/QtyInput";
import { toast } from "@/components/workbench/toast";
import { money } from "@/lib/money";
import { isManager } from "@/lib/roles";
import {
  MAX_QTY,
  blocked,
  fill,
  lineState,
  lineTitle,
  newReceiveKey,
  pendingFrom,
  pendingOf,
  pendingSlot,
  pendingText,
  receiveOutcome,
  startDraft,
  summarize,
  withProduct,
  withQty,
  type PendingReceive,
  type ReceiveDraft,
  type ReceiveLine,
} from "@/lib/vendorReceive";

/** 還不知道結果的那一次記在這個分頁裡(重新整理還在);讀寫不了(無痕、被擋)就當成沒有。 */
function readPending(orderId: number): PendingReceive | null {
  try {
    return pendingFrom(sessionStorage.getItem(pendingSlot(orderId)));
  } catch {
    return null;
  }
}

function writePending(orderId: number, pending: PendingReceive | null) {
  try {
    if (pending) sessionStorage.setItem(pendingSlot(orderId), pendingText(pending));
    else sessionStorage.removeItem(pendingSlot(orderId));
  } catch {
    /* 存不了就算了:這個面板開著的期間鑰匙還是同一把 */
  }
}

/** 只能入到按數量管的一般商品:要逐台刷序號的、虛擬的看得到但不能選(伺服器也會擋)。 */
async function pickable(query: string) {
  const found = await searchProducts(query, { activeOnly: true, excludeSecondhand: true });
  return found.map((o) => ({
    ...o,
    disabled: o.disabled || o.payload?.requires_serial === true || o.payload?.is_virtual === true,
  }));
}

/**
 * 到貨入庫:照廠商這張單**現在**的明細開一張進貨單。
 * 單價是廠商的、運費算不算進成本是門市的設定,這裡都改不到;這裡只決定「這一次每一行入幾個、入到哪個品號」。
 * 規則在 lib/vendorReceive.ts;能不能入、最多幾個由伺服器照廠商當下的單再算一次。
 * 按了確認、沒有拿到答覆的那一次記在瀏覽器裡:解決之前(同一把鑰匙再送一次)這張單不能開新的一次入庫。
 */
export function ReceiveDrawer({ order, onClose }: { order: VendorOrder; onClose: () => void }) {
  const manager = isManager(useCurrentUser()?.profile?.role);
  const plan = useVendorReceiving(order.id);
  const receive = useReceiveVendorOrder();
  const saveIssue = useSaveVendorIssue();
  // 這一次入庫的鑰匙:面板開著就不換(沒有答覆時再按一次,不會入兩次)
  const requestKey = useRef(newReceiveKey());
  const [draft, setDraft] = useState<ReceiveDraft | null>(null);
  const [refused, setRefused] = useState("");
  const [repick, setRepick] = useState<Record<string, boolean>>({});
  // 上一次按了確認、還不知道結果的那一次(可能是這個面板上一次打開時按的):解決之前只能「再送一次」
  const [pending, setPending] = useState<PendingReceive | null>(() => readPending(order.id));
  const busy = receive.isPending || saveIssue.isPending;
  const locked = busy || pending !== null;
  const data = plan.data;

  useEffect(() => {
    if (data && draft === null) setDraft(startDraft(data, requestKey.current));
  }, [data, draft]);

  const sum = data && draft ? summarize(data, draft) : null;
  const fee = data ? Number(data.shipping_fee) : 0;

  /**
   * 送出一次入庫。**先記下來才送**:回應沒回來、重新整理、關掉再開,都還認得是同一次。
   * `resend` = 這是在確認上一次(沒有答覆的那一次):被擋不一定代表上一次沒入,規則在 `receiveOutcome`。
   */
  async function send(what: PendingReceive, resend: boolean) {
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
      // 明確沒有入:不用再記;重抓廠商現在的單(數量可能變了)
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
    const why = blocked(sum);
    if (why) {
      setRefused(why);
      return;
    }
    send(pendingOf(draft, sum), false);
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

  function productCell(line: ReceiveLine) {
    if (!draft) return null;
    const picked = draft.product[line.key];
    // 對過的料號:店員改不了(怕手滑入到別的膜上);管理員按「改」才打開
    if (line.product && !repick[line.key]) {
      return (
        <span className="vr-fixed">
          入到 {line.product.name}
          {manager && (
            <button type="button" className="btn-link" disabled={locked} onClick={() => setRepick({ ...repick, [line.key]: true })}>
              改
            </button>
          )}
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

  return (
    <Drawer
      open
      title={`到貨入庫 ${order.vendor_order_no}`}
      onClose={() => !busy && onClose()}
      lockBackdrop
      width={760}
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
      {plan.isLoading && <div className="md-empty">跟{order.provider_label}要這張單的明細…</div>}
      {plan.isError && <Banner kind="error" message={apiErrorText(plan.error)} />}
      {pending && !receive.isPending && !refused && (
        <Banner kind="error" message={`上一次的入庫(${pending.pieces} 個)還不知道有沒有成功,請按「再送一次」`} />
      )}
      {refused && <Banner kind="error" message={refused} />}
      {data && draft && sum && (
        <>
          <div className="vr-head">
            <span>{[data.vendor_status, data.vendor_logistics_status, data.vendor_tracking_no].filter(Boolean).join(" · ")}</span>
            {fee > 0 && (
              <span>
                運費 ${money(fee)}
                {data.freight_into_cost ? `(算進成本,還有 $${money(data.freight_left)})` : "(不算成本)"}
              </span>
            )}
            {data.payment_method === "貨到付款" && <span>貨到付款:記現金</span>}
            <span className="vr-fill">
              <button type="button" className="btn" disabled={locked} onClick={() => setDraft(fill(data, draft, "shipped"))}>
                帶已出的
              </button>
              <button type="button" className="btn" disabled={locked} onClick={() => setDraft(fill(data, draft, "remaining"))}>
                帶未入的
              </button>
            </span>
          </div>
          <table className="report-grid vo-confirm vr-grid">
            <thead>
              <tr>
                <th>品名 / 我的品號</th>
                <th className="num">叫</th>
                <th className="num">已出</th>
                <th className="num">已入</th>
                <th className="num">這次</th>
                <th className="num">單價</th>
              </tr>
            </thead>
            <tbody>
              {data.lines.map((line) => {
                const qty = draft.qty[line.key] ?? 0;
                const state = lineState(line, qty);
                const room = Math.max(line.remaining_qty, 0);
                return (
                  <tr key={line.key} className={qty > 0 ? "vo-picked" : undefined}>
                    <td className="vo-name">
                      {lineTitle(line)}
                      {line.is_reissue && <span className="vo-test">免費補發</span>}
                      <div className="vo-sub">{line.sku}</div>
                      {/* 品號放在品名底下(不是另一欄):窄的平板一樣整行看得到,不用左右捲 */}
                      <div className="vr-map">{productCell(line)}</div>
                    </td>
                    <td className="num">{line.qty}</td>
                    <td className="num">{line.shipped_qty}</td>
                    <td className="num">{line.received_qty}</td>
                    <td className="num">
                      <QtyInput
                        className="vo-qty"
                        aria-label={`${lineTitle(line)} 這次入庫`}
                        value={qty}
                        min={0}
                        max={Math.min(room, MAX_QTY)}
                        disabled={locked || room === 0}
                        onCommit={(n) => setDraft(withQty(draft, line.key, n))}
                        onRejected={() => toast(`${lineTitle(line)} 最多還能入 ${room} 個`, "err")}
                      />
                      {state === "early" && <div className="vo-sub vo-diff">比已出的多</div>}
                      {state === "over" && <div className="vo-sub vo-diff">最多 {room}</div>}
                    </td>
                    <td className="num">{line.is_reissue ? "0" : money(line.unit_price)}</td>
                  </tr>
                );
              })}
              <tr className="vo-confirm-total">
                <td colSpan={4}>這次入庫</td>
                <td className="num">{sum.pieces}</td>
                <td className="num">
                  <b>${money(sum.amount)}</b>
                </td>
              </tr>
            </tbody>
          </table>
          <div className="vo-form">
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
