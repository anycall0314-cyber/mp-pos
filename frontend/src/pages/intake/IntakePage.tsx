import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import {
  useCommitIntake,
  useCreateIntake,
  useIntakeBatch,
  useIntakeBatches,
  useMatchIntakeItem,
  useNewProductForIntakeItem,
  useRejectIntakeItem,
  useWarehouses,
} from "@/api/hooks";
import { searchCategories, searchProducts, searchSuppliers } from "@/api/search";
import type {
  IntakeBatchStatus,
  IntakeItem,
  IntakeMatchStatus,
} from "@/api/types";
import { Banner } from "@/components/Banner";
import { ComboBox } from "@/components/ComboBox";
import { Drawer } from "@/components/Drawer";
import { Field } from "@/components/Field";
import { Toolbar } from "@/components/Toolbar";

const STATUS_META: Record<IntakeMatchStatus, { label: string; cls: string }> = {
  auto_matched: { label: "自動對應", cls: "ok" },
  resolved: { label: "已對應", cls: "ok" },
  new_product: { label: "已建新品", cls: "ok" },
  needs_review: { label: "待選候選", cls: "warn" },
  conflict: { label: "屬性衝突", cls: "danger" },
  unknown: { label: "未知商品", cls: "danger" },
  rejected: { label: "已駁回", cls: "muted" },
};

const BATCH_STATUS_LABEL: Record<IntakeBatchStatus, string> = {
  open: "待確認",
  resolved: "可過帳",
  committed: "已過帳",
  cancelled: "已取消",
};

const RESOLVED_SET: IntakeMatchStatus[] = [
  "auto_matched",
  "resolved",
  "new_product",
  "rejected",
];

function money(v: string | number) {
  const n = Number(v);
  return Number.isFinite(n) ? Math.round(n).toLocaleString() : "—";
}

export function IntakePage() {
  const batchesQuery = useIntakeBatches("page_size=50");
  const [selectedBatchId, setSelectedBatchId] = useState<number | null>(null);
  const batchQuery = useIntakeBatch(selectedBatchId);
  const batch = batchQuery.data ?? null;

  const [selectedItemId, setSelectedItemId] = useState<number | null>(null);
  const selectedItem = useMemo(
    () => batch?.items.find((i) => i.id === selectedItemId) ?? null,
    [batch, selectedItemId],
  );

  // 建立批次表單
  const [rawText, setRawText] = useState("");
  const [supplierId, setSupplierId] = useState<number | "">("");
  const [warehouseId, setWarehouseId] = useState<number | "">("");
  const [vendorDocNo, setVendorDocNo] = useState("");
  const [formError, setFormError] = useState("");

  const warehouses = useWarehouses();
  const createIntake = useCreateIntake();
  const commitIntake = useCommitIntake();

  const [commitMsg, setCommitMsg] = useState<{ no: string; poId: number } | null>(
    null,
  );
  const [commitErr, setCommitErr] = useState("");

  async function submitIntake() {
    if (!rawText.trim()) {
      setFormError("請先貼上進貨單內容");
      return;
    }
    setFormError("");
    try {
      const b = await createIntake.mutateAsync({
        raw_text: rawText,
        supplier: supplierId === "" ? null : supplierId,
        warehouse: warehouseId === "" ? null : warehouseId,
        vendor_doc_no: vendorDocNo.trim(),
      });
      setSelectedBatchId(b.id);
      setSelectedItemId(b.items[0]?.id ?? null);
      setRawText("");
      setVendorDocNo("");
      setCommitMsg(null);
      setCommitErr("");
    } catch (e) {
      setFormError(e instanceof Error ? e.message : String(e));
    }
  }

  async function commit() {
    if (!batch) return;
    setCommitErr("");
    try {
      const b = await commitIntake.mutateAsync(batch.id);
      setCommitMsg({
        no: b.purchase_order_no ?? "",
        poId: b.committed_purchase_order_id ?? 0,
      });
    } catch (e) {
      setCommitErr(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="page">
      <Toolbar title="待確認入庫" />

      <div className="intake-create">
        {formError && <Banner kind="error" message={formError} />}
        <textarea
          className="intake-textarea"
          value={rawText}
          onChange={(e) => setRawText(e.target.value)}
          placeholder={
            "貼上進貨單內容,一行一項,例:\niPhone 15 Pro 256 黑 x2 @35000 序號=356..1,356..2\n保護貼 x10 @50"
          }
          rows={4}
        />
        <div className="intake-create-row">
          <div className="intake-create-field">
            <span className="intake-label">廠商(選填)</span>
            <ComboBox
              value={supplierId}
              onChange={(id) => setSupplierId(id)}
              fetchOptions={searchSuppliers}
              placeholder="選廠商"
            />
          </div>
          <div className="intake-create-field">
            <span className="intake-label">入庫倉(選填)</span>
            <select
              value={warehouseId}
              onChange={(e) =>
                setWarehouseId(e.target.value ? Number(e.target.value) : "")
              }
            >
              <option value="">未指定</option>
              {(warehouses.data ?? []).map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          </div>
          <div className="intake-create-field">
            <span className="intake-label">廠商單號(選填)</span>
            <input
              value={vendorDocNo}
              onChange={(e) => setVendorDocNo(e.target.value)}
              placeholder="防重複匯入"
            />
          </div>
          <button
            className="btn primary"
            onClick={submitIntake}
            disabled={createIntake.isPending}
          >
            送出識別
          </button>
        </div>
      </div>

      <div className="intake-batchbar">
        <span className="intake-label">批次</span>
        <select
          value={selectedBatchId ?? ""}
          onChange={(e) => {
            setSelectedBatchId(e.target.value ? Number(e.target.value) : null);
            setSelectedItemId(null);
            setCommitMsg(null);
            setCommitErr("");
          }}
        >
          <option value="">選擇批次…</option>
          {(batchesQuery.data ?? []).map((b) => (
            <option key={b.id} value={b.id}>
              #{b.id} {b.supplier_name || "未指定廠商"} ·{" "}
              {BATCH_STATUS_LABEL[b.status]}
            </option>
          ))}
        </select>
        {batch && (
          <>
            <span className="intake-batchmeta">
              {batch.supplier_name || "未指定廠商"} /{" "}
              {batch.warehouse_name || "未指定倉"} ·{" "}
              {BATCH_STATUS_LABEL[batch.status]}
            </span>
            <button
              className="btn primary"
              onClick={commit}
              disabled={batch.status !== "resolved" || commitIntake.isPending}
              title={
                batch.status !== "resolved"
                  ? "還有明細未確認,無法過帳"
                  : "過帳成進貨單"
              }
            >
              過帳
            </button>
          </>
        )}
      </div>

      {commitMsg && (
        <div className="intake-commit-ok">
          已建立進貨單 {commitMsg.no}
          {commitMsg.poId ? (
            <Link className="btn small" to={`/purchases/${commitMsg.poId}`}>
              檢視這張進貨單
            </Link>
          ) : null}
        </div>
      )}
      {commitErr && <Banner kind="error" message={commitErr} />}

      {batch ? (
        <div className="md-layout intake-work">
          <section className="md-master">
            <div className="md-table">
              <table>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>原始文字</th>
                    <th>數量</th>
                    <th>狀態</th>
                    <th>信心</th>
                  </tr>
                </thead>
                <tbody>
                  {batch.items.map((it) => {
                    const meta = STATUS_META[it.match_status];
                    const dim = RESOLVED_SET.includes(it.match_status);
                    return (
                      <tr
                        key={it.id}
                        className={[
                          it.id === selectedItemId ? "selected" : "",
                          dim ? "intake-row-done" : "",
                        ]
                          .filter(Boolean)
                          .join(" ")}
                        onClick={() => setSelectedItemId(it.id)}
                      >
                        <td>{it.line_no}</td>
                        <td>{it.raw_text}</td>
                        <td className="num">{it.raw_qty}</td>
                        <td>
                          <span className={`intake-badge ${meta.cls}`}>
                            {meta.label}
                          </span>
                        </td>
                        <td className="num">{it.match_confidence}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
          <section className="md-detail">
            {selectedItem ? (
              <ItemDetail item={selectedItem} />
            ) : (
              <div className="md-empty" style={{ marginTop: 40 }}>
                從左側選一行來處理
              </div>
            )}
          </section>
        </div>
      ) : (
        <div className="md-empty" style={{ marginTop: 40 }}>
          貼一張進貨單送出識別,或從上方選一個批次
        </div>
      )}
    </div>
  );
}

function ItemDetail({ item }: { item: IntakeItem }) {
  const matchItem = useMatchIntakeItem();
  const rejectItem = useRejectIntakeItem();
  const newProduct = useNewProductForIntakeItem();

  const [otherProduct, setOtherProduct] = useState<number | "">("");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [np, setNp] = useState({
    name: "",
    category: "" as number | "",
    capacity: "",
    color: "",
    region_version: "",
    requires_serial: true,
  });
  const [npError, setNpError] = useState("");

  const busy = matchItem.isPending || rejectItem.isPending || newProduct.isPending;
  const meta = STATUS_META[item.match_status];

  function openNewProduct() {
    setNp({
      name: item.raw_text,
      category: "",
      capacity: "",
      color: "",
      region_version: "",
      requires_serial: true,
    });
    setNpError("");
    setDrawerOpen(true);
  }

  async function submitNewProduct() {
    if (np.category === "") {
      setNpError("請選類別");
      return;
    }
    try {
      await newProduct.mutateAsync({
        id: item.id,
        name: np.name.trim() || undefined,
        category: np.category,
        capacity: np.capacity.trim(),
        color: np.color.trim(),
        region_version: np.region_version.trim(),
        requires_serial: np.requires_serial,
      });
      setDrawerOpen(false);
    } catch (e) {
      setNpError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="intake-item-detail">
      <h3 className="pc-detail-title">{item.raw_text}</h3>
      <dl>
        <dt>狀態</dt>
        <dd>
          <span className={`intake-badge ${meta.cls}`}>{meta.label}</span>
        </dd>
        <dt>數量</dt>
        <dd className="num">{item.raw_qty}</dd>
        <dt>進價</dt>
        <dd className="num">{money(item.raw_unit_price)}</dd>
        <dt>序號</dt>
        <dd>{item.raw_serials.length ? item.raw_serials.join("、") : "—"}</dd>
        {item.matched_product && (
          <>
            <dt>已對應</dt>
            <dd>
              {item.matched_product_sku} {item.matched_product_name}
            </dd>
          </>
        )}
      </dl>

      {item.candidates.length > 0 && (
        <div className="intake-candidates">
          <div className="intake-subhead">候選商品</div>
          {item.candidates.map((c) => (
            <div
              key={c.product_id}
              className={`intake-candidate${c.conflict ? " conflict" : ""}`}
            >
              <div className="intake-candidate-main">
                <div className="intake-candidate-name">
                  {c.name}
                  {(c.capacity || c.color) && (
                    <span className="intake-candidate-attr">
                      {" "}
                      {[c.capacity, c.color].filter(Boolean).join(" / ")}
                    </span>
                  )}
                </div>
                <div className="intake-candidate-sub">
                  {c.sku} · 分數 {c.score}
                  {c.conflict ? (
                    <span className="intake-conflict-tag"> · {c.reason}</span>
                  ) : (
                    <span className="intake-candidate-reason"> · {c.reason}</span>
                  )}
                </div>
              </div>
              <button
                className={c.conflict ? "btn small" : "btn small primary"}
                disabled={busy}
                onClick={() =>
                  matchItem.mutate({ id: item.id, product: c.product_id })
                }
              >
                選這個
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="intake-actions">
        <div className="intake-otherpick">
          <span className="intake-label">改對應其他商品</span>
          <ComboBox
            value={otherProduct}
            onChange={(id) => {
              if (id !== "") {
                matchItem.mutate({ id: item.id, product: id });
                setOtherProduct("");
              }
            }}
            fetchOptions={(q) => searchProducts(q, { activeOnly: true })}
            placeholder="搜尋商品品名 / 品號"
          />
        </div>
        <div className="intake-action-btns">
          <button className="btn" onClick={openNewProduct} disabled={busy}>
            建新品
          </button>
          <button
            className="btn"
            onClick={() => rejectItem.mutate(item.id)}
            disabled={busy}
          >
            駁回
          </button>
        </div>
      </div>

      <Drawer
        open={drawerOpen}
        title="建立新商品並對應"
        onClose={() => setDrawerOpen(false)}
      >
        {npError && <Banner kind="error" message={npError} />}
        <Field label="品名" required>
          <input
            value={np.name}
            onChange={(e) => setNp((s) => ({ ...s, name: e.target.value }))}
            placeholder="預設帶入原始文字"
          />
        </Field>
        <Field label="類別" required>
          <ComboBox
            value={np.category}
            onChange={(id) => setNp((s) => ({ ...s, category: id }))}
            fetchOptions={searchCategories}
            placeholder="選類別"
          />
        </Field>
        <Field label="容量">
          <input
            value={np.capacity}
            onChange={(e) => setNp((s) => ({ ...s, capacity: e.target.value }))}
            placeholder="例:256GB"
          />
        </Field>
        <Field label="顏色">
          <input
            value={np.color}
            onChange={(e) => setNp((s) => ({ ...s, color: e.target.value }))}
            placeholder="例:黑"
          />
        </Field>
        <Field label="地區版本">
          <input
            value={np.region_version}
            onChange={(e) =>
              setNp((s) => ({ ...s, region_version: e.target.value }))
            }
            placeholder="例:台版"
          />
        </Field>
        <label className="checkbox" style={{ marginTop: 8 }}>
          <input
            type="checkbox"
            checked={np.requires_serial}
            onChange={(e) =>
              setNp((s) => ({ ...s, requires_serial: e.target.checked }))
            }
          />
          需追蹤序號(手機 / 平板打勾;配件取消)
        </label>
        <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
          <button
            className="btn primary"
            onClick={submitNewProduct}
            disabled={newProduct.isPending}
          >
            建立並對應
          </button>
          <button className="btn" onClick={() => setDrawerOpen(false)}>
            取消
          </button>
        </div>
      </Drawer>
    </div>
  );
}
