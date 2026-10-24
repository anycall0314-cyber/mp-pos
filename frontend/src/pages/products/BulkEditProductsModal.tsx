import { useEffect, useMemo, useState } from "react";

import {
  useBrands,
  useBulkEditProducts,
  usePhoneSeriesList,
} from "@/api/hooks";
import { ApiHttpError } from "@/api/client";
import type { Brand, PhoneSeries } from "@/api/types";
import { useArm } from "@/components/workbench/useArm";
import { Banner } from "@/components/Banner";
import { ChoiceGroup, IconButton, SegmentedControl } from "@/components/ui";
import { DraftBanner } from "@/components/DraftBanner";
import { PhoneModelPicker } from "@/components/PhoneModelPicker";
import { useModalDraft } from "@/hooks/useModalDraft";
import { MoneyInput } from "@/components/MoneyInput";
import { bulkFailureLines } from "@/lib/bulkErrors";
import { ATTRS, TRI_CHOICES, type AttrKey, type Tri, attrPatch, attrSummary, attrsFromDraft, keepAll } from "@/lib/bulkEdit";
import { intStr } from "@/lib/money";
import { isManager } from "@/lib/roles";
import { PRODUCT_MODES, ruleProblem, rulePayload, valueUnit } from "@/lib/staffCost";
import { useCurrentUser } from "@/auth/AuthContext";
import { errorText } from "@/lib/errorText";

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
  // 刪除 / 套用這類按錯代價大的:再按一次才做(全站檢視 G1:不跳瀏覽器的確認框)
  const arm = useArm();
  const save = useBulkEditProducts();
  const [error, setError] = useState<string | null>(null);
  // 整批被退回時:哪一個商品、為什麼(伺服器逐個回報;例:用過的商品不能改「需追蹤序號」)
  const [failures, setFailures] = useState<string[]>([]);

  // 各區塊啟用旗標
  const [enPrice, setEnPrice] = useState(false);
  const [enKind, setEnKind] = useState(false);
  const [enLifecycle, setEnLifecycle] = useState(false);
  const [enAttrs, setEnAttrs] = useState(false);
  const [enHost, setEnHost] = useState(false);
  const [enCompat, setEnCompat] = useState(false);
  // 業務員成本怎麼算:只有管理員有這一段(伺服器也只收管理員送的)
  const canSetStaff = isManager(useCurrentUser()?.profile?.role);
  const [enStaff, setEnStaff] = useState(false);
  const [staffMode, setStaffMode] = useState("");
  const [staffValue, setStaffValue] = useState("");

  // 各區塊值
  const [listPrice, setListPrice] = useState("");
  const [safetyStock, setSafetyStock] = useState("");
  const [accessoryType, setAccessoryType] = useState<AccessoryType>("none");
  const [lifecycleStatus, setLifecycleStatus] =
    useState<LifecycleStatus>("active");
  // 每個屬性各自「不改 / 是 / 否」,預設不改(全站檢視 D9)
  const [attrs, setAttrs] = useState<Record<AttrKey, Tri>>(keepAll);
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
    setFailures([]);
    setEnPrice(false);
    setEnKind(false);
    setEnLifecycle(false);
    setEnAttrs(false);
    setEnHost(false);
    setEnCompat(false);
    setEnStaff(false);
    setStaffMode("");
    setStaffValue("");
    setListPrice("");
    setSafetyStock("");
    setAccessoryType("none");
    setLifecycleStatus("active");
    setAttrs(keepAll());
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
      attrs,
      brand, series, generation, modelSuffix,
      compat: Array.from(compat.entries()),
      enStaff, staffMode, staffValue,
    }),
    [
      enPrice, enKind, enLifecycle, enAttrs, enHost, enCompat,
      listPrice, safetyStock, accessoryType, lifecycleStatus,
      attrs,
      brand, series, generation, modelSuffix, compat,
      enStaff, staffMode, staffValue,
    ],
  );
  const draftHelper = useModalDraft({
    key: DRAFT_KEY,
    open,
    state: draftState,
    isEditMode: false,
    isEmpty: (s) =>
      !s.enPrice && !s.enKind && !s.enLifecycle && !s.enAttrs && !s.enHost && !s.enCompat && !s.enStaff,
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
    // 以前的草稿存的是五個勾(一起送的那種):一律當成不改
    setAttrs(attrsFromDraft((s as { attrs?: unknown }).attrs));
    setBrand(s.brand);
    setSeries(s.series);
    setGeneration(s.generation);
    setModelSuffix(s.modelSuffix);
    setCompat(new Map(s.compat));
    // 這一段是後來才加的:以前存的草稿沒有這三格
    setEnStaff(s.enStaff ?? false);
    setStaffMode(s.staffMode ?? "");
    setStaffValue(s.staffValue ?? "");
    draftHelper.consumeDraft();
  }

  async function submit() {
    setError(null);
    setFailures([]);
    const patch: Record<string, unknown> = {};
    if (enPrice) {
      if (listPrice.trim()) patch.list_price = intStr(listPrice);
      if (safetyStock.trim())
        patch.safety_stock = Number(safetyStock) || 0;
    }
    if (enKind) patch.accessory_type = accessoryType;
    if (enLifecycle) patch.lifecycle_status = lifecycleStatus;
    if (enAttrs) Object.assign(patch, attrPatch(attrs));
    if (enHost) {
      patch.brand = brand || null;
      patch.series = series || null;
      patch.generation = generation.trim() ? Number(generation) : null;
      patch.model_suffix = modelSuffix;
    }
    if (enCompat) {
      patch.related_host_keys = Array.from(compat.keys());
    }
    if (enStaff && canSetStaff) {
      const problem = ruleProblem(staffMode, staffValue);
      if (problem) {
        setError(`業務員成本:${problem}`);
        return;
      }
      Object.assign(patch, rulePayload(staffMode, staffValue));
    }
    if (Object.keys(patch).length === 0) {
      setError("沒有勾選任何要修改的欄位");
      return;
    }
    const changes = [
      enPrice && "售價 / 安全庫存",
      enStaff && canSetStaff && "業務員成本",
      enKind && "商品性質",
      enLifecycle && "販售狀態",
      ...(enAttrs ? attrSummary(attrs) : []),
      enHost && "主機資訊",
      enCompat && "相容機型",
    ].filter(Boolean);
    if (changes.length === 0) return;
    if (!arm.confirm("apply")) return;
    try {
      const res = await save.mutateAsync({ ids: productIds, patch });
      draftHelper.markSavedAndClear();
      onSuccess(res.updated);
    } catch (e) {
      setError(errorText(e));
      setFailures(e instanceof ApiHttpError ? bulkFailureLines(e.body) : []);
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
          {error && failures.length > 0 && (
            <ul className="be-failures">
              {failures.map((line, i) => (
                <li key={i}>{line}</li>
              ))}
            </ul>
          )}
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
                  售價
                  <MoneyInput
                    min="0"
                    value={listPrice}
                    onChange={setListPrice}
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

          {/* 業務員成本怎麼算(管理員才有) */}
          {canSetStaff && (
            <section className={"be-section" + (enStaff ? " on" : "")}>
              <label className="be-section-head">
                <input
                  type="checkbox"
                  checked={enStaff}
                  onChange={(e) => setEnStaff(e.target.checked)}
                />
                <b>修改 業務員成本</b>
              </label>
              {enStaff && (
                <div className="be-section-body">
                  <div className="be-hint">帶序號的商品不套用</div>
                  <label>
                    算法
                    <select value={staffMode} onChange={(e) => setStaffMode(e.target.value)}>
                      {PRODUCT_MODES.map(([value, label]) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </label>
                  {staffMode && (
                    <label>
                      數值({valueUnit(staffMode)})
                      <input
                        inputMode="decimal"
                        value={staffValue}
                        onChange={(e) => setStaffValue(e.target.value)}
                      />
                    </label>
                  )}
                </div>
              )}
            </section>
          )}

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
                <ChoiceGroup
                  label="商品性質"
                  layout="fill"
                  value={accessoryType}
                  onChange={setAccessoryType}
                  options={[
                    { value: "none", label: "主機" },
                    { value: "phone_specific", label: "機型配件" },
                    { value: "universal", label: "通用配件" },
                  ]}
                />
              </div>
            )}
          </section>

          {/* 區塊 3: 販售狀態 */}
          <section className={"be-section" + (enLifecycle ? " on" : "")}>
            <label className="be-section-head">
              <input
                type="checkbox"
                checked={enLifecycle}
                onChange={(e) => setEnLifecycle(e.target.checked)}
              />
              <b>修改 販售狀態</b>
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
                {ATTRS.map(([key, label]) => (
                  <div key={key} className="be-tri">
                    <span>{label}</span>
                    <SegmentedControl
                      label={label}
                      value={attrs[key]}
                      onChange={(v) => setAttrs((a) => ({ ...a, [key]: v }))}
                      options={TRI_CHOICES.map(([v, text]) => ({ value: v, label: text }))}
                    />
                  </div>
                ))}
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
                        <IconButton
                          className="compact"
                          label={`移除 ${name}`}
                          onClick={() =>
                            setCompat((prev) => {
                              const next = new Map(prev);
                              next.delete(key);
                              return next;
                            })
                          }
                        >
                          ×
                        </IconButton>
                      </span>
                    ))}
                  </div>
                )}
                <div
                  style={{
                    color: "var(--text-dim)",
                    fontSize: 14,
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
          {/* 送出中不給取消(關掉不會取消已經送出去的;全站控制項 F04) */}
          <button className="btn" type="button" onClick={onClose} disabled={save.isPending}>
            取消
          </button>
          <button
            className={`btn primary${arm.armed === "apply" ? " armed" : ""}`}
            onClick={submit}
            disabled={save.isPending}
            aria-busy={save.isPending || undefined}
          >
            {save.isPending
              ? "套用中…"
              : arm.armed === "apply"
                ? `再按一次套用至 ${productIds.length} 筆`
                : `套用至 ${productIds.length} 筆`}
          </button>
        </div>
      </div>
    </div>
  );
}
