import { useRef, useState } from "react";

import { api } from "@/api/client";
import { useSaveVendorMapping, useVendorMappings } from "@/api/hooks";
import type { Product, VendorLinkRow } from "@/api/types";
import { useCan } from "@/auth/AuthContext";
import { PhotoName, usePhotoPeek } from "@/components/photos/PhotoName";
import { ArmButton } from "@/components/workbench/ArmButton";
import { apiErrorText } from "@/components/workbench/errors";
import { toast } from "@/components/workbench/toast";
import {
  ACTION_LABEL,
  actionsOf,
  counts,
  filterRows,
  findText,
  itemTitle,
  linkFetched,
  oneAtATime,
  savedText,
  whyNot,
  type Linkable,
  type MappingRow,
} from "@/lib/vendorMapping";
import { FindFirstPanel } from "@/pages/products/FindFirstPanel";
import { ProductForm } from "@/pages/products/ProductForm";

/**
 * 品名連連看:這家廠商的每一個品項 ↔ 店裡的哪一個商品(owner 2026-10-10)。
 * 連好之後,這個品項到貨時入庫面板打開就帶好品號,只要確認數量。店裡還沒有的商品可以當場建(先找一次,確定沒有才建)。
 * 規則在 lib/vendorMapping.ts;品名、規格、一包幾個、那個商品能不能連,都由伺服器決定。
 */
export function MappingTab({ link }: { link: VendorLinkRow }) {
  const list = useVendorMappings(link.warehouse, link.provider);
  const save = useSaveVendorMapping();
  const mayCreate = useCan("edit_products");
  const [text, setText] = useState("");
  const [unlinkedOnly, setUnlinkedOnly] = useState(false);
  // 正在替哪一個廠商品項找店內商品(兩個面板共用;面板開著的期間不會換)
  const [target, setTarget] = useState<MappingRow | null>(null);
  const targetRef = useRef<MappingRow | null>(null);
  targetRef.current = target;
  const [finding, setFinding] = useState(false);
  const [formUsed, setFormUsed] = useState(false);
  const [formOpen, setFormOpen] = useState(false);
  const [prefill, setPrefill] = useState<{ name: string; barcode: string } | null>(null);
  // 一次只存一筆:哪一列正在存(那一列顯示「儲存」,每一列的按鈕都先不能按)。
  // 判斷用的是 `gate` 自己記的,不是這個 state(晚回來的回應手上的 state 是舊的)
  const [busy, setBusy] = useState<string | null>(null);
  const gate = useRef(oneAtATime(setBusy)).current;
  const peek = usePhotoPeek();

  const rows = list.data?.rows ?? [];
  const shown = filterRows(rows, { text, unlinkedOnly });
  const sum = counts(rows);

  /** 把 `row` 連到 `product`(null = 解除)。回有沒有存成。呼叫的人先經過 `gate`。 */
  async function store(row: MappingRow, product: number | null): Promise<boolean> {
    try {
      const got = await save.mutateAsync({ warehouse: link.warehouse, vendor: link.provider, key: row.key, product });
      toast(savedText(got, row.product), "ok");
      return true;
    } catch (e) {
      toast(apiErrorText(e), "err", { ms: 6000 });
      return false;
    }
  }

  function start(row: MappingRow) {
    if (gate.busy() !== null) return;
    setTarget(row);
    setFinding(true);
  }

  function closeAll() {
    setFinding(false);
    setFormOpen(false);
    setTarget(null);
  }

  /**
   * 找到 / 建好的店內商品 → 連到 `row`。**`row` 是按下去那一刻的那一列,由呼叫的人當下交進來**
   * (表單存好會馬上自己關掉、把「正在處理哪一列」清掉;這裡不能晚一點才去看)。連不了的講原因、面板留著(可以再挑別的)。
   */
  async function use(row: MappingRow | null, p: Linkable & { id: number }) {
    if (!row) return;
    const why = whyNot(p);
    if (why) {
      toast(why, "err", { ms: 6000 });
      return;
    }
    if (await gate.run(row.key, () => store(row, p.id))) closeAll();
  }

  return (
    <>
      {rows.length > 0 && (
        <div className="list-filterbar vo-filter">
          <input
            type="search"
            className="vo-search"
            aria-label="找品項"
            placeholder="找廠商品名 / 料號 / 店內品名"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <label className="vo-check">
            <input type="checkbox" checked={unlinkedOnly} onChange={(e) => setUnlinkedOnly(e.target.checked)} />
            只看沒連
          </label>
          <span className="list-filterbar-count">
            已連 {sum.linked} / {sum.total} 項
          </span>
        </div>
      )}
      <div className="report-table vo-table">
        {list.isLoading && <div className="md-empty">跟{link.provider_label}要商品清單…</div>}
        {list.isError && (
          <div className="md-empty">
            {apiErrorText(list.error)}
            <div>
              <button type="button" className="btn" onClick={() => list.refetch()}>
                重試
              </button>
            </div>
          </div>
        )}
        {list.data && rows.length === 0 && <div className="md-empty">{link.provider_label}沒有回任何商品</div>}
        {rows.length > 0 && shown.length === 0 && <div className="md-empty">沒有符合的品項</div>}
        {shown.length > 0 && (
          <table className="report-grid vo-grid vm-grid">
            <thead>
              <tr>
                <th>{link.provider_label}的品項</th>
                <th>店內商品</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {shown.map((row) => (
                <tr key={row.key} className={row.product ? "report-row" : "report-row vm-open"}>
                  <td className="vo-name">
                    {itemTitle(row)}
                    <div className="vo-sub">
                      {row.sku}　每包 {row.pack_qty} {row.unit || "個"}
                    </div>
                  </td>
                  <td className="vo-name">
                    {row.product ? (
                      <>
                        <PhotoName id={row.product.id} name={row.product.name} sku={row.product.sku} onPeek={peek.open} />
                        <div className="vo-sub">
                          {row.product.sku}
                          {!row.product.is_active && <span className="vo-test">已停用</span>}
                        </div>
                      </>
                    ) : (
                      <span className="vm-none">還沒連</span>
                    )}
                  </td>
                  <td className="vm-acts">
                    {actionsOf(row).map((act) =>
                      act === "unlink" ? (
                        <ArmButton
                          key={act}
                          className="btn"
                          label={ACTION_LABEL[act]}
                          armedLabel="確定"
                          disabled={busy !== null}
                          onConfirm={() => gate.run(row.key, () => store(row, null))}
                        />
                      ) : (
                        <button
                          key={act}
                          type="button"
                          className={act === "link" ? "btn primary" : "btn"}
                          disabled={busy !== null}
                          onClick={() => start(row)}
                        >
                          {busy === row.key ? "儲存" : ACTION_LABEL[act]}
                        </button>
                      ),
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <FindFirstPanel
        open={finding}
        initialText={target ? findText(target) : ""}
        from={{ supplierId: list.data?.supplier?.id ?? "" }}
        // 停用的也列出來(人才看得到已經有一個);按了由這一頁講不能連
        inactiveLabel="使用這款"
        peeking={peek.isOpen}
        onPeek={peek.open}
        onClose={closeAll}
        onUse={(p) => void use(targetRef.current, p)}
        onCreate={(kind, fill) => {
          if (kind === "phone") {
            toast("手機、平板要逐台刷序號,叫貨的品項連不到", "err", { ms: 6000 });
            return;
          }
          if (!mayCreate) {
            toast("這個帳號沒有開「商品建檔」,請管理員先建好這個商品", "err", { ms: 6000 });
            return;
          }
          setFinding(false);
          setPrefill(fill);
          setFormUsed(true);
          setFormOpen(true);
        }}
      />
      {formUsed && (
        <ProductForm
          open={formOpen}
          initial={null}
          prefill={prefill}
          // 這一頁的草稿自己一格,不跟商品管理、進貨開單頁共用
          draftKey="modal-draft:product-form-vendor-map"
          onPeek={peek.open}
          peeking={peek.isOpen}
          // 表單裡選「主機」會出現「新增手機型號」:手機連不到叫貨的品項,不帶人離開這一頁
          onPhoneWizard={() => toast("手機、平板要逐台刷序號,叫貨的品項連不到", "err", { ms: 6000 })}
          onClose={closeAll}
          onSaved={(p) => void use(targetRef.current, p)}
          onUseExisting={(id, note) => {
            if (note) toast(note.text, note.tone, { ms: 6000 });
            // 存檔被防重複擋下、選了「就是這個」:連的是既有的那一個(先查它現在的樣子)。
            // 是哪一列**現在就記下來**:表單下一步就自己關掉了,等查回來才去看的話不是沒有、就是人接著點的別列。
            // 查的這一段也算「正在存」(每一列的按鈕先不能按)
            const row = targetRef.current;
            if (!row) return;
            void gate.run(row.key, () =>
              linkFetched(row, {
                fetch: () => api<Product>(`/products/${id}/`),
                link: (r, p) => store(r, p.id),
                say: (t) => toast(t, "err", { ms: 6000 }),
                errorText: apiErrorText,
              }),
            );
          }}
        />
      )}
      {peek.panel}
    </>
  );
}
