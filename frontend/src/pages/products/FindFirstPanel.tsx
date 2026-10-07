import { useEffect, useRef, useState } from "react";

import { findProductsBeforeCreate } from "@/api/search";
import type { Product } from "@/api/types";
import { useCurrentUser } from "@/auth/AuthContext";
import { Drawer } from "@/components/Drawer";
import { MiniThumb } from "@/components/photos/PhotoName";
import type { PeekTarget } from "@/components/photos/ProductPhotoPanel";
import {
  ask,
  askable,
  createPrefill,
  fail,
  type FindState,
  type FoundRow,
  IDLE,
  mergeRows,
  reset,
  rowFacts,
  rowWhy,
  searchText,
  settle,
  stillUsable,
  stockScope,
  viewOf,
} from "@/lib/findFirst";

interface Props {
  open: boolean;
  onClose: () => void;
  /** 已經有了:用這一款,不新增 */
  onUse: (p: Product) => void;
  /** 找過、確定沒有:建新的。prefill = 找的時候打的字(是條碼就在條碼那一格) */
  onCreate: (kind: "phone" | "other", prefill: { name: string; barcode: string }) => void;
  onPeek: (t: PeekTarget) => void;
  /** 照片面板開著:Esc / 點旁邊是關照片面板,這個框不跟著收 */
  peeking: boolean;
  /** 打開時先帶進來的字(進貨開單頁「找不到」的那一串):有字就自動先找一次 */
  initialText?: string;
  /** 從單據裡開的:這張單的廠商(它的料號 / 叫法也找) */
  from?: { supplierId?: number | "" };
  /** 已停用的那一列按鈕上的字。商品管理是「查看這款」(過去看、管理員可以恢復);單據裡沒有地方可以「過去看」,由頁面決定怎麼講 */
  inactiveLabel?: string;
}

/**
 * 按「新增商品」先出現的框:用自己的說法找一次,有就用那一款,確定沒有才建。
 * 規則(什麼時候可以選、什麼時候可以往下建)在 lib/findFirst。
 */
export function FindFirstPanel({
  open,
  onClose,
  onUse,
  onCreate,
  onPeek,
  peeking,
  initialText,
  from,
  inactiveLabel = "查看這款",
}: Props) {
  const scope = stockScope(useCurrentUser()?.profile);
  const [input, setInput] = useState("");
  const [state, setState] = useState<FindState<Product>>(IDLE);
  // 回應回來的時候要對「現在」的狀態算,不是對送出去那一刻的
  const now = useRef<FindState<Product>>(IDLE);
  function apply(step: (s: FindState<Product>) => FindState<Product>) {
    now.current = step(now.current);
    setState(now.current);
  }

  // 每次打開都重新開始(關掉之前送出去的那一次回來也不算);有帶字進來就先找一次
  useEffect(() => {
    const start = open ? (initialText ?? "") : "";
    setInput(start);
    apply(reset);
    if (open && askable(start)) run(start);
    // 只跟著開關走
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // 注音 / 倉頡選字:選字那一下的 Enter 不是「找」。選字結束的事件與那一下 Enter 的先後各家瀏覽器不一樣,
  // 所以選字結束後晚一拍才放掉(不去攔按鍵,免得把選好的字吃掉)
  const composing = useRef(false);

  /** text = 要找的字(不給就是框裡現在的字) */
  function run(text: string = input) {
    if (!askable(text)) return;
    apply((s) => ask(s, text));
    const sent = now.current;
    if (sent.phase !== "loading") return;
    // 條碼送整串數字(照包裝打的 4712-3456-7890 也找得到);畫面上「現在找的是哪一句」仍然是人打的那一句
    const query = searchText(sent.asked);
    findProductsBeforeCreate(query, scope, from)
      .then((r) => mergeRows(r.resolved, r.plain, query))
      .then(
        (rows) => apply((s) => settle(s, sent.seq, rows)),
        // 整理回應時出錯也算沒查成功(不能停在「尋找中…」)
        (e) => apply((s) => fail(s, sent.seq, e instanceof Error ? e.message : String(e))),
      );
  }

  const view = viewOf(state, input);
  // 照片面板開著的時候,這個抽屜整個不能動(`Drawer` 的 `frozen`:頁首的 ×、內容、頁尾都是,Tab 也進不來):
  // 不然可以在背後改字 / 關掉重開,照片面板上的「使用此商品」卻還是先前那一筆
  const canCreate = view.canCreate && !peeking;
  /** 現在的開關與框裡的字(給「使用此商品」按下去那一刻核對用) */
  const live = useRef({ open, input });
  live.current = { open, input };
  const prefill = () => createPrefill(state.phase === "done" ? state.asked : "");

  function peek(row: FoundRow<Product>) {
    const p = row.product;
    const given = state.seq;
    onPeek({
      id: p.id,
      name: p.name,
      sku: p.sku,
      // 停用的不給「使用此商品」:它要先恢復才能用(按「查看這款」過去看)
      onUse:
        view.canUse && p.is_active
          ? () => {
              // 這顆按鈕是點開照片那一刻給的:按下去再核對一次(框還開著、還是同一次查詢、字沒改過)
              const ok = stillUsable(now.current, live.current.input, {
                seq: given,
                open: live.current.open,
              });
              if (ok) onUse(p);
            }
          : undefined,
    });
  }

  return (
    <Drawer
      open={open}
      title="先找有沒有建過"
      width={560}
      onClose={onClose}
      lockBackdrop={peeking}
      frozen={peeking}
      footer={
        <>
          {/* 有候選的時候先講一句:下面兩顆是「上面都不是」才按的 */}
          {canCreate && view.rows.length > 0 && <span className="ff-none">以上都不是</span>}
          <button
            type="button"
            className="btn"
            disabled={!canCreate}
            title={canCreate ? undefined : view.note || "先找一次"}
            onClick={() => onCreate("phone", prefill())}
          >
            建立手機平板
          </button>
          <button
            type="button"
            className="btn"
            disabled={!canCreate}
            title={canCreate ? undefined : view.note || "先找一次"}
            onClick={() => onCreate("other", prefill())}
          >
            建立其他商品
          </button>
        </>
      }
    >
      <form
        className="ff-search"
        onSubmit={(e) => {
          e.preventDefault();
          if (composing.current) return;
          run();
        }}
      >
        <input
          autoFocus
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onCompositionStart={() => {
            composing.current = true;
          }}
          onCompositionEnd={() => {
            window.setTimeout(() => {
              composing.current = false;
            }, 0);
          }}
          placeholder="品名或條碼"
          aria-label="品名或條碼"
        />
        {/* 按鈕直接找(不經過上面「選字中不找」那一關:會按到按鈕,字就是選好了) */}
        <button
          type="button"
          className="btn primary"
          disabled={!askable(input)}
          onClick={() => run()}
        >
          尋找
        </button>
      </form>
      {view.note && (
        <div className="ff-note" role="status">
          {view.note}
        </div>
      )}
      <div className={view.stale ? "ff-list stale" : "ff-list"}>
        {view.rows.map((row) => {
          const p = row.product;
          return (
            <div key={p.id} className="ff-row">
              <MiniThumb src={p.photo_thumb} onClick={() => peek(row)} />
              <div className="ff-row-main">
                <div>
                  <button
                    type="button"
                    className="ph-name"
                    title="看照片與規格"
                    onClick={() => peek(row)}
                  >
                    {p.name}
                  </button>
                  {!p.is_active && <span className="intake-inactive-tag">已停用</span>}
                </div>
                <div className="ff-row-sub">{rowFacts(row)}</div>
                <div className="ff-row-sub">{rowWhy(row)}</div>
              </div>
              <button
                type="button"
                className="btn small primary"
                disabled={!view.canUse}
                onClick={() => onUse(p)}
              >
                {p.is_active ? "使用這款" : inactiveLabel}
              </button>
            </div>
          );
        })}
      </div>
    </Drawer>
  );
}
