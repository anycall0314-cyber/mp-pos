import { useEffect, useMemo, useState } from "react";

import {
  useBrands,
  useBulkEditProducts,
  usePhoneSeriesList,
} from "@/api/hooks";
import type { Brand, PhoneSeries } from "@/api/types";
import { Banner } from "@/components/Banner";
import { DraftBanner } from "@/components/DraftBanner";
import { PhoneModelPicker } from "@/components/PhoneModelPicker";
import { useModalDraft } from "@/hooks/useModalDraft";

const DRAFT_KEY = "modal-draft:bulk-edit-products";

interface Props {
  open: boolean;
  productIds: number[];
  onClose: () => void;
  onSuccess: (count: number) => void;
}

type AccessoryType = "none" | "phone_specific" | "universal";
type LifecycleStatus =
  | "pending"
  | "active"
  | "replacing"
  | "discontinued"
  | "clearance";

/**
 * 批次修改既有商品 — 每個區塊有「啟用編輯」勾選,只有勾選的才會送出。
 * 不勾的欄位保留原值,不會被覆寫成空。
 */
export function BulkEditProductsModal({
  open,
  productIds,
  onClose,
  onSuccess,
}: Props) {
  const save = useBulkEditProducts();
  const [error, setError] = useState<string | null>(null);

  // 各區塊啟用旗標
  const [enPrice, setEnPrice] = useState(false);
  const [enKind, setEnKind] = useState(false);
  const [enLifecycle, setEnLifecycle] = useState(false);
  const [enAttrs, setEnAttrs] = useState(false);
  const [enHost, setEnHost] = useState(false);
  const [enCompat, setEnCompat] = useState(false);

  // 各區塊值
  const [listPrice, setListPrice] = useState("");
  const [safetyStock, setSafetyStock] = useState("");
  const [accessoryType, setAccessoryType] = useState<AccessoryType>("none");
  const [lifecycleStatus, setLifecycleStatus] =
    useState<LifecycleStatus>("active");
  const [requiresSerial, setRequiresSerial] = useState(false);
  const [allowsTelecomLine, setAllowsTelecomLine] = useState(false);
  const [allowsCommission, setAllowsCommission] = useState(false);
  const [countsCash, setCountsCash] = useState(true);
  const [countsMargin, setCountsMargin] = useState(true);
  const [brand, setBrand] = useState<number | "">("");
  const [series, setSeries] = useState<number | "">("");
  const [generation, setGeneration] = useState("");
  const [modelSuffix, setModelSuffix] = useState("");
  const brands = useBrands();
  const phoneSeries = usePhoneSeriesList(
    typeof brand === "number" ? brand : null,
  );
  const [compat, setCompat] = useState<Map<string, string>>(new Map());

  useEffect(() => {
    if (!open) return;
    setError(null);
    setEnPrice(false);
    setEnKind(false);
    setEnLifecycle(false);
    setEnAttrs(false);
    setEnHost(false);
    setEnCompat(false);
    setListPrice("");
    setSafetyStock("");
    setAccessoryType("none");
    setLifecycleStatus("active");
    setRequiresSerial(false);
    setAllowsTelecomLine(false);
    setAllowsCommission(false);
    setCountsCash(true);
    setCountsMargin(true);
    setBrand("");
    setSeries("");
    setGeneration("");
    setModelSuffix("");
    setCompat(new Map());
  }, [open]);

  // ── 草稿
  const draftState = useMemo(
    () => ({
      enPrice, enKind, enLifecycle, enAttrs, enHost, enCompat,
      listPrice, safetyStock, accessoryType, lifecycleStatus,
      requiresSerial, allowsTelecomLine, allowsCommission, countsCash, countsMargin,
      brand, series, generation, modelSuffix,
      compat: Array.from(compat.entries()),
    }),
    [
      enPrice, enKind, enLifecycle, enAttrs, enHost, enCompat,
      listPrice, safetyStock, accessoryType, lifecycleStatus,
      requiresSerial, allowsTelecomLine, allowsCommission, countsCash, countsMargin,
      brand, series, generation, modelSuffix, compat,
    ],
  );
  const draftHelper = useModalDraft({
    key: DRAFT_KEY,
    open,
    state: draftState,
    isEditMode: false,
    isEmpty: (s) =>
      !s.enPrice && !s.enKind && !s.enLifecycle && !s.enAttrs && !s.enHost && !s.enCompat,
  });
  function loadDraftToState() {
    const d = draftHelper.draft;
    if (!d) return;
    const s = d.state;
    setEnPrice(s.enPrice);
    setEnKind(s.enKind);
    setEnLifecycle(s.enLifecycle);
    setEnAttrs(s.enAttrs);
    setEnHost(s.enHost);
    setEnCompat(s.enCompat);
    setListPrice(s.listPrice);
    setSafetyStock(s.safetyStock);
    setAccessoryType(s.accessoryType);
    setLifecycleStatus(s.lifecycleStatus);
    setRequiresSerial(s.requiresSerial);
    setAllowsTelecomLine(s.allowsTelecomLine);
    setAllowsCommission(s.allowsCommission);
    setCountsCash(s.countsCash);
    setCountsMargin(s.countsMargin);
    setBrand(s.brand);
    setSeries(s.series);
    setGeneration(s.generation);
    setModelSuffix(s.modelSuffix);
    setCompat(new Map(s.compat));
    draftHelper.consumeDraft();
  }

  async function submit() {
    setError(null);
    const patch: Record<string, unknown> = {};
    if (enPrice) {
      if (listPrice.trim()) patch.list_price = listPrice;
      if (safetyStock.trim())
        patch.safety_stock = Number(safetyStock) || 0;
    }
    if (enKind) patch.accessory_type = accessoryType;
    if (enLifecycle) patch.lifecycle_status = lifecycleStatus;
    if (enAttrs) {
      patch.requires_serial = requiresSerial;
      patch.allows_telecom_line = allowsTelecomLine;
      patch.allows_commission = allowsCommission;
      patch.counts_cash = countsCash;
      patch.counts_margin = countsMargin;
    }
    if (enHost) {
      patch.brand = brand || null;
      patch.series = series || null;
      patch.generation = generation.trim() ? Number(generation) : null;
      patch.model_suffix = modelSuffix;
    }
    if (enCompat) {
      patch.related_host_keys = Array.from(compat.keys());
    }
    if (Object.keys(patch).length === 0) {
      setError("沒有勾選任何要修改的欄位");
      return;
    }
    if (
      !confirm(
        `將套用到 ${productIds.length} 筆商品。\n變更欄位:${Object.keys(patch).join("、")}\n確認?`,
      )
    )
      return;
    try {
      const res = await save.mutateAsync({ ids: productIds, patch });
      draftHelper.markSavedAndClear();
      onSuccess(res.updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  if (!open) return null;
  return (
    <div className="modal-overlay">{/* 遮罩點擊不關閉,只能用「取消」按鈕關 */}
      <div
        className="modal-card be-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-title">
          批次修改商品 · {productIds.length} 筆
        </div>
        <div className="modal-body be-body">
          {error && <Banner kind="error" message={error} />}
          {draftHelper.draft && (
            <DraftBanner
              savedAt={draftHelper.draft.savedAt}
              onLoad={loadDraftToState}
              onDiscard={() => draftHelper.discardDraft()}
            />
          )}
          <div className="be-hint">
            勾選要修改的區塊,未勾選的欄位保留原值。
          </div>

          {/* 區塊 1: 售價 / 安全庫存 */}
          <section className={"be-section" + (enPrice ? " on" : "")}>
            <label className="be-section-head">
              <input
                type="checkbox"
                checked={enPrice}
                onChange={(e) => setEnPrice(e.target.checked)}
              />
              <b>修改 售價 / 安全庫存</b>
            </label>
            {enPrice && (
              <div className="be-section-body">
                <label>
                  建議零售價
                  <input
                    type="number"
                    min="0"
                    value={listPrice}
                    onChange={(e) => setListPrice(e.target.value)}
                    placeholder="留空 = 不改"
                  />
                </label>
                <label>
                  安全庫存
                  <input
                    type="number"
                    min="0"
                    value={safetyStock}
                    onChange={(e) => setSafetyStock(e.target.value)}
                    placeholder="留空 = 不改"
                  />
                </label>
              </div>
            )}
          </section>

          {/* 區塊 2: 商品性質 */}
          <section className={"be-section" + (enKind ? " on" : "")}>
            <label className="be-section-head">
              <input
                type="checkbox"
                checked={enKind}
                onChange={(e) => setEnKind(e.target.checked)}
              />
              <b>修改 商品性質</b>
            </label>
            {enKind && (
              <div className="be-section-body">
                <div className="pf-tabs">
                  {(
                    [
                      ["none", "主機"],
                      ["phone_specific", "機型配件"],
                      ["universal", "通用配件"],
                    ] as const
                  ).map(([v, label]) => (
                    <button
                      key={v}
                      type="button"
                      className={
                        "pf-tab" + (accessoryType === v ? " active" : "")
                      }
                      onClick={() => setAccessoryType(v)}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </section>

          {/* 區塊 3: 商品狀態 */}
          <section className={"be-section" + (enLifecycle ? " on" : "")}>
            <label className="be-section-head">
              <input
                type="checkbox"
                checked={enLifecycle}
                onChange={(e) => setEnLifecycle(e.target.checked)}
              />
              <b>修改 商品狀態</b>
            </label>
            {enLifecycle && (
              <div className="be-section-body">
                <select
                  value={lifecycleStatus}
                  onChange={(e) =>
                    setLifecycleStatus(e.target.value as LifecycleStatus)
                  }
                >
                  <option value="active">主力現貨</option>
                  <option value="replacing">即將換代</option>
                  <option value="clearance">清倉處理</option>
                  <option value="discontinued">停產下架</option>
                  <option value="pending">待補齊</option>
                </select>
              </div>
            )}
          </section>

          {/* 區塊 4: 屬性 */}
          <section className={"be-section" + (enAttrs ? " on" : "")}>
            <label className="be-section-head">
              <input
                type="checkbox"
                checked={enAttrs}
                onChange={(e) => setEnAttrs(e.target.checked)}
              />
              <b>修改 屬性</b>
            </label>
            {enAttrs && (
              <div className="be-section-body be-attrs">
                <label>
                  <input
                    type="checkbox"
                    checked={requiresSerial}
                    onChange={(e) => setRequiresSerial(e.target.checked)}
                  />
                  需追蹤序號
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={allowsTelecomLine}
                    onChange={(e) => setAllowsTelecomLine(e.target.checked)}
                  />
                  可綁門號合約
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={allowsCommission}
                    onChange={(e) => setAllowsCommission(e.target.checked)}
                  />
                  可有業務員佣金
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={countsCash}
                    onChange={(e) => setCountsCash(e.target.checked)}
                  />
                  計入現金
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={countsMargin}
                    onChange={(e) => setCountsMargin(e.target.checked)}
                  />
                  計入毛利
                </label>
              </div>
            )}
          </section>

          {/* 區塊 5: 主機資訊 */}
          <section className={"be-section" + (enHost ? " on" : "")}>
            <label className="be-section-head">
              <input
                type="checkbox"
                checked={enHost}
                onChange={(e) => setEnHost(e.target.checked)}
              />
              <b>修改 主機資訊(品牌 / 系列 / 世代 / 後綴)</b>
            </label>
            {enHost && (
              <div className="be-section-body be-grid3">
                <label>
                  品牌
                  <select
                    value={brand}
                    onChange={(e) => {
                      const v = e.target.value
                        ? Number(e.target.value)
                        : "";
                      setBrand(v);
                      setSeries("");
                    }}
                  >
                    <option value="">不變更</option>
                    {(brands.data ?? []).map((b: Brand) => (
                      <option key={b.id} value={b.id}>
                        {b.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  產品系列
                  <select
                    value={series}
                    disabled={!brand}
                    onChange={(e) =>
                      setSeries(
                        e.target.value ? Number(e.target.value) : "",
                      )
                    }
                  >
                    <option value="">不變更</option>
                    {(phoneSeries.data ?? []).map((s: PhoneSeries) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  世代序號
                  <input
                    type="number"
                    min="0"
                    value={generation}
                    onChange={(e) => setGeneration(e.target.value)}
                  />
                </label>
                <label>
                  型號後綴
                  <input
                    value={modelSuffix}
                    onChange={(e) => setModelSuffix(e.target.value)}
                    placeholder="Pro Max / Plus / +"
                  />
                </label>
              </div>
            )}
          </section>

          {/* 區塊 6: 相容機型 — 覆寫 */}
          <section className={"be-section" + (enCompat ? " on" : "")}>
            <label className="be-section-head">
              <input
                type="checkbox"
                checked={enCompat}
                onChange={(e) => setEnCompat(e.target.checked)}
              />
              <b>修改 相容機型(覆寫)</b>
            </label>
            {enCompat && (
              <div className="be-section-body">
                <PhoneModelPicker
                  allowCreate
                  placeholder="搜尋機型加入相容清單…"
                  onPick={(m) => {
                    setCompat((prev) => {
                      if (prev.has(m.model_key)) return prev;
                      const next = new Map(prev);
                      next.set(m.model_key, m.model_name);
                      return next;
                    });
                  }}
                />
                {compat.size > 0 && (
                  <div
                    style={{
                      display: "flex",
                      flexWrap: "wrap",
                      gap: 6,
                      marginTop: 8,
                    }}
                  >
                    {Array.from(compat.entries()).map(([key, name]) => (
                      <span
                        key={key}
                        className="bcp-model-chip on"
                        style={{ cursor: "default" }}
                      >
                        {name}
                        <button
                          type="button"
                          onClick={() =>
                            setCompat((prev) => {
                              const next = new Map(prev);
                              next.delete(key);
                              return next;
                            })
                          }
                          style={{
                            marginLeft: 6,
                            background: "transparent",
                            border: 0,
                            color: "inherit",
                            cursor: "pointer",
                            fontSize: 14,
                            padding: 0,
                            lineHeight: 1,
                          }}
                          title="移除"
                        >
                          ×
                        </button>
                      </span>
                    ))}
                  </div>
                )}
                <div
                  style={{
                    color: "var(--text-dim)",
                    fontSize: 12,
                    marginTop: 6,
                  }}
                >
                  覆寫模式:被選的商品原有相容機型會被清空,改為以上清單
                  {compat.size === 0 && "(留空 = 清空所有相容關聯)"}
                </div>
              </div>
            )}
          </section>
        </div>

        <div className="modal-actions">
          <button className="btn" onClick={onClose}>
            取消
          </button>
          <button
            className="btn primary"
            onClick={submit}
            disabled={save.isPending}
          >
            {save.isPending
              ? "套用中…"
              : `套用至 ${productIds.length} 筆`}
          </button>
        </div>
      </div>
    </div>
  );
}
