import { useEffect, useMemo, useState } from "react";

const DRAFT_KEY = "modal-draft:expander";

import {
  BulkProductRow,
  useBrands,
  useBulkCreateProducts,
  usePhoneSeriesList,
} from "@/api/hooks";
import { ApiHttpError } from "@/api/client";
import { searchCategories } from "@/api/search";
import type { Brand, Category, PhoneSeries } from "@/api/types";
import { Banner } from "@/components/Banner";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { DraftBanner } from "@/components/DraftBanner";
import { Checkbox, Field } from "@/components/Field";
import { PhoneModelPicker } from "@/components/PhoneModelPicker";
import { useModalDraft } from "@/hooks/useModalDraft";
import { MoneyInput } from "@/components/MoneyInput";
import { intStr } from "@/lib/money";

import {
  BulkDuplicateRows,
  type FlaggedRow,
  flaggedRows,
} from "./BulkDuplicateRows";
import { defaultRequiresSerial, stockModeLabel } from "@/lib/productDefaults";

interface Props {
  open: boolean;
  onClose: () => void;
  onSuccess: (count: number) => void;
  /**
   * 預設情境:
   * - "phone"(預設):建主機,軸 = 容量 × 顏色
   * - "accessory":建機型專屬配件(imos / HODA 各品牌變體),
   *   軸 = 功能 × 顏色,accessory_type 預設 phone_specific,
   *   requiresSerial 預設 false
   */
  mode?: "phone" | "accessory";
}

interface Combo {
  key: string;
  name: string;
  spec: string;
  list_price: string;
  selected: boolean;
}

type AccessoryType = "none" | "phone_specific" | "universal";

function splitList(s: string): string[] {
  return s
    .split(/[,，\n]/g)
    .map((x) => x.trim())
    .filter(Boolean);
}

/** 從型號名稱末段數字推 generation,例:三星 S26 → 26;iPhone 15 Pro → 15。 */
function deriveGeneration(model: string): string {
  const m = model.match(/(\d{1,3})(?:\s*(?:Pro|Plus|Ultra|Max|Mini|FE)\b)?\s*$/i);
  return m?.[1] ?? "";
}

export function ProductExpanderModal({
  open,
  onClose,
  onSuccess,
  mode = "phone",
}: Props) {
  const isAccessoryMode = mode === "accessory";
  const [model, setModel] = useState("");
  const [category, setCategory] = useState<number | "">("");
  const [categoryOpt, setCategoryOpt] = useState<ComboOption<Category> | null>(
    null,
  );

  // 商品性質(整合進主流程,決定後續欄位 + 屬性預設)
  const [accessoryType, setAccessoryType] = useState<AccessoryType>(
    isAccessoryMode ? "phone_specific" : "none",
  );

  // 主機資訊(Phase 1: brand/series 改用 FK id)
  const [brandId, setBrandId] = useState<number | "">("");
  const [seriesId, setSeriesId] = useState<number | "">("");
  const [generation, setGeneration] = useState("");
  const [modelSuffix, setModelSuffix] = useState("");
  const [genTouched, setGenTouched] = useState(false);
  const brands = useBrands();
  const phoneSeries = usePhoneSeriesList(
    typeof brandId === "number" ? brandId : null,
  );

  // 相容機型(機型配件用):key → name
  const [compat, setCompat] = useState<Map<string, string>>(new Map());

  const [axis1Label, setAxis1Label] = useState(
    isAccessoryMode ? "功能" : "容量",
  );
  const [axis2Label, setAxis2Label] = useState("顏色");
  const [axis1Text, setAxis1Text] = useState("");
  const [axis2Text, setAxis2Text] = useState("");
  const [pricesText, setPricesText] = useState("");

  // 屬性(可隨商品性質自動調整,但仍允許使用者覆蓋)
  // accessory mode 預設不需追蹤序號
  const [requiresSerial, setRequiresSerial] = useState(
    defaultRequiresSerial(isAccessoryMode ? "phone_specific" : "none"),
  );
  // 人自己動過「需追蹤序號」:之後換商品性質不再替他改。放在狀態裡、跟著草稿存
  // (存草稿再載回來還要記得;用「現在的值跟預設一不一樣」去猜會猜錯:自己勾了序號、切到主機,主機的預設本來就是追)
  const [serialTouched, setSerialTouched] = useState(false);
  const [allowsTelecomLine, setAllowsTelecomLine] = useState(false);
  const [allowsCommission, setAllowsCommission] = useState(false);

  const [combos, setCombos] = useState<Combo[]>([]);
  const [error, setError] = useState<string | null>(null);

  const mutation = useBulkCreateProducts();
  // 被防重複關卡擋下的列,以及每一列各自寫的差異(以品名為鍵)
  const [flagged, setFlagged] = useState<FlaggedRow[]>([]);
  const [reasons, setReasons] = useState<Record<string, string>>({});

  const axis1Values = useMemo(() => splitList(axis1Text), [axis1Text]);
  const axis2Values = useMemo(() => splitList(axis2Text), [axis2Text]);
  const prices = useMemo(() => splitList(pricesText), [pricesText]);

  // ── 草稿:打包要保存的欄位
  const draftState = useMemo(
    () => ({
      model,
      accessoryType,
      brandId,
      seriesId,
      generation,
      modelSuffix,
      axis1Label,
      axis2Label,
      axis1Text,
      axis2Text,
      pricesText,
      requiresSerial,
      serialTouched,
      allowsTelecomLine,
      allowsCommission,
      compat: Array.from(compat.entries()),
    }),
    [
      model,
      accessoryType,
      brandId,
      seriesId,
      generation,
      modelSuffix,
      axis1Label,
      axis2Label,
      axis1Text,
      axis2Text,
      pricesText,
      requiresSerial,
      serialTouched,
      allowsTelecomLine,
      allowsCommission,
      compat,
    ],
  );
  const draftHelper = useModalDraft({
    key: DRAFT_KEY,
    open,
    state: draftState,
    isEditMode: false,
    isEmpty: (s) =>
      !s.model.trim() &&
      !s.axis1Text.trim() &&
      !s.axis2Text.trim() &&
      !s.pricesText.trim() &&
      s.compat.length === 0 &&
      !s.brandId &&
      !s.seriesId,
  });
  function loadDraftToState() {
    const d = draftHelper.draft;
    if (!d) return;
    const s = d.state;
    setModel(s.model);
    setAccessoryType(s.accessoryType);
    setBrandId(s.brandId);
    setSeriesId(s.seriesId);
    setGeneration(s.generation);
    setModelSuffix(s.modelSuffix);
    setAxis1Label(s.axis1Label);
    setAxis2Label(s.axis2Label);
    setAxis1Text(s.axis1Text);
    setAxis2Text(s.axis2Text);
    setPricesText(s.pricesText);
    setRequiresSerial(s.requiresSerial);
    // 這一版之前存的草稿沒有記「人動過沒有」:那一格跟這種商品的預設不一樣才當成動過
    setSerialTouched(
      (s as { serialTouched?: boolean }).serialTouched ??
        s.requiresSerial !== defaultRequiresSerial(s.accessoryType),
    );
    setAllowsTelecomLine(s.allowsTelecomLine);
    setAllowsCommission(s.allowsCommission);
    setCompat(new Map(s.compat));
    draftHelper.consumeDraft();
  }

  // 商品性質改變時,自動帶屬性 + 軸標籤預設
  function changeAccessoryType(next: AccessoryType) {
    // 再點一次已經選中的那一種:什麼都不做(不然會把下面勾好的屬性重設一次)
    if (next === accessoryType) return;
    setAccessoryType(next);
    // 序號預設跟一般「新增商品」用同一份(lib/productDefaults):主機逐件、配件按數量。
    // 人自己動過「需追蹤序號」之後就不替他改(例如要逐件追的高價配件)
    if (!serialTouched) setRequiresSerial(defaultRequiresSerial(next));
    if (next === "none") {
      setAxis1Label("容量");
      setAxis2Label("顏色");
    } else if (next === "phone_specific") {
      setAxis1Label("功能");
      setAxis2Label("顏色");
    } else {
      setAxis1Label("規格");
      setAxis2Label("樣式");
    }
  }

  // 型號變動時自動猜世代(只在未手動修改時)
  useEffect(() => {
    if (genTouched) return;
    setGeneration(deriveGeneration(model));
  }, [model, genTouched]);

  const previewCombos = useMemo<Combo[]>(() => {
    const m = model.trim();
    if (!m) return [];
    const slot1: { val: string; price: string }[] =
      axis1Values.length === 0
        ? [{ val: "", price: prices[0] ?? "0" }]
        : axis1Values.map((v, i) => ({
            val: v,
            price: prices[i] ?? prices[prices.length - 1] ?? "0",
          }));
    const slot2 = axis2Values.length === 0 ? [""] : axis2Values;

    const result: Combo[] = [];
    for (const s1 of slot1) {
      for (const s2 of slot2) {
        const parts = [m, s1.val, s2].filter(Boolean);
        const name = parts.join(" ");
        result.push({
          key: name,
          name,
          spec: [s1.val, s2].filter(Boolean).join(" / "),
          list_price: s1.price,
          selected: true,
        });
      }
    }
    return result;
  }, [model, axis1Values, axis2Values, prices]);

  useEffect(() => {
    setCombos((prev) => {
      const prevMap = new Map(prev.map((c) => [c.key, c]));
      return previewCombos.map((p) => {
        const existed = prevMap.get(p.key);
        return existed
          ? { ...p, selected: existed.selected, list_price: existed.list_price }
          : p;
      });
    });
  }, [previewCombos]);

  function toggleSelect(key: string, sel: boolean) {
    setCombos((prev) =>
      prev.map((c) => (c.key === key ? { ...c, selected: sel } : c)),
    );
  }

  function toggleAll(sel: boolean) {
    setCombos((prev) => prev.map((c) => ({ ...c, selected: sel })));
  }

  function patchPrice(key: string, v: string) {
    setCombos((prev) =>
      prev.map((c) => (c.key === key ? { ...c, list_price: v } : c)),
    );
  }

  function applyPriceToAll(v: string) {
    setCombos((prev) => prev.map((c) => ({ ...c, list_price: v })));
  }

  function reset() {
    setModel("");
    setCategory("");
    setCategoryOpt(null);
    setAccessoryType(isAccessoryMode ? "phone_specific" : "none");
    setBrandId("");
    setSeriesId("");
    setGeneration("");
    setModelSuffix("");
    setGenTouched(false);
    setAxis1Label(isAccessoryMode ? "功能" : "容量");
    setAxis2Label("顏色");
    setAxis1Text("");
    setAxis2Text("");
    setPricesText("");
    setRequiresSerial(defaultRequiresSerial(isAccessoryMode ? "phone_specific" : "none"));
    setSerialTouched(false);
    setAllowsTelecomLine(false);
    setAllowsCommission(false);
    setCompat(new Map());
    setCombos([]);
    setError(null);
    setFlagged([]);
    setReasons({});
  }

  async function handleCreate() {
    setError(null);
    if (!category) {
      setError("請選類別");
      return;
    }
    const toCreate = combos.filter((c) => c.selected);
    if (toCreate.length === 0) {
      setError("沒有勾選任何商品");
      return;
    }
    setFlagged([]);
    const items: BulkProductRow[] = toCreate.map((c) => ({
      name: c.name,
      spec: c.spec,
      list_price: intStr(c.list_price),
      ...(reasons[c.name]?.trim()
        ? { distinct_reason: reasons[c.name].trim() }
        : {}),
    }));
    try {
      const res = await mutation.mutateAsync({
        common: {
          category: Number(category),
          accessory_type: accessoryType,
          warehouse_type: "product",
          requires_serial: requiresSerial,
          allows_telecom_line: allowsTelecomLine,
          allows_commission: allowsCommission,
          // 僅主機帶 brand/series/generation/suffix(用 FK id)
          ...(accessoryType === "none" && {
            brand: brandId || null,
            series: seriesId || null,
            generation: generation.trim() ? Number(generation) : null,
            model_suffix: modelSuffix,
          }),
          // 機型配件 → 帶相容機型 keys(套用至所有展開 SKU)
          ...(accessoryType === "phone_specific" && {
            related_host_keys: Array.from(compat.keys()),
          }),
          is_active: true,
        },
        items,
      });
      draftHelper.markSavedAndClear();
      onSuccess(res.count);
      reset();
    } catch (e: unknown) {
      if (e instanceof ApiHttpError && e.body && typeof e.body === "object") {
        setFlagged(flaggedRows((e.body as { errors?: unknown }).errors));
      }
      setError(e instanceof Error ? e.message : "建立失敗");
    }
  }

  if (!open) return null;

  const selectedCount = combos.filter((c) => c.selected).length;
  const list = combos.length > 0 ? combos : previewCombos;
  const isHost = accessoryType === "none";

  return (
    <div className="modal-overlay">{/* 遮罩點擊不關閉,只能用「取消」按鈕關 */}
      <div
        className="modal-card expander-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="modal-title">
          {isAccessoryMode ? "新增配件(同款多規格展開)" : "型號展開新增"}
        </div>

        {error && <Banner kind="error" message={error} />}
        <BulkDuplicateRows
          rows={flagged}
          reasons={reasons}
          onChange={(name, v) => setReasons((s) => ({ ...s, [name]: v }))}
        />
        {draftHelper.draft && (
          <DraftBanner
            savedAt={draftHelper.draft.savedAt}
            onLoad={loadDraftToState}
            onDiscard={() => draftHelper.discardDraft()}
          />
        )}

        <div className="modal-body">
          {/* 商品性質 — 決定後續欄位顯示 + 屬性預設 */}
          <Field
            label="商品性質"
            required
            hint={`庫存:${stockModeLabel(requiresSerial)}`}
          >
            <div className="pf-tabs">
              {(
                [
                  ["none", "主機", "手機 / 平板"],
                  ["phone_specific", "機型配件", "殼 / 保護貼"],
                  ["universal", "通用配件", "充電線 / 耳機"],
                ] as const
              ).map(([v, label, sub]) => (
                <button
                  key={v}
                  type="button"
                  className={`pf-tab${accessoryType === v ? " active" : ""}`}
                  onClick={() => changeAccessoryType(v)}
                >
                  {label}
                  <span className="pf-tab-sub">{sub}</span>
                </button>
              ))}
            </div>
          </Field>

          <Field label="型號名稱" required>
            <input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder={
                isHost
                  ? "例:iPhone 16 PRO / 三星 S26"
                  : "例:iPhone 18 手機殼"
              }
            />
          </Field>

          {/* 主機才顯示「主機資訊」 — 一次填寫,所有展開的 SKU 都帶 */}
          {isHost && (
            <div className="fieldset">
              <legend>主機資訊(這次建立的每一個品項都一樣)</legend>
              <div className="field-row">
                <Field label="品牌" required>
                  <select
                    value={brandId}
                    onChange={(e) => {
                      const v = e.target.value
                        ? Number(e.target.value)
                        : "";
                      setBrandId(v);
                      setSeriesId("");
                    }}
                  >
                    <option value="">請選擇品牌</option>
                    {(brands.data ?? []).map((b: Brand) => (
                      <option key={b.id} value={b.id}>
                        {b.name}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field
                  label="產品系列"
                  required
                  hint={brandId ? "從此品牌挑選" : "請先選品牌"}
                >
                  <select
                    value={seriesId}
                    disabled={!brandId}
                    onChange={(e) =>
                      setSeriesId(
                        e.target.value ? Number(e.target.value) : "",
                      )
                    }
                  >
                    <option value="">請選擇系列</option>
                    {(phoneSeries.data ?? []).map((s: PhoneSeries) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field
                  label="世代序號"
                  hint={
                    genTouched
                      ? "已手動修正"
                      : "同系列第幾代;例:iPhone 15 → 15"
                  }
                >
                  <input
                    type="number"
                    step="1"
                    min="0"
                    value={generation}
                    onChange={(e) => {
                      setGenTouched(true);
                      setGeneration(e.target.value);
                    }}
                  />
                </Field>
              </div>
              <Field
                label="型號後綴(選填)"
                hint="Pro / Pro Max / Plus / Ultra / +;留空 = 標準款"
              >
                <input
                  value={modelSuffix}
                  onChange={(e) => setModelSuffix(e.target.value)}
                  placeholder="Pro Max"
                />
              </Field>
            </div>
          )}

          {/* 機型配件 → 多選相容機型,套用至所有展開 SKU */}
          {accessoryType === "phone_specific" && (
            <Field
              label="相容機型(這次建立的每一個品項都一樣)"
              hint="搜尋並選取多個機型;找不到可直接輸入新增"
            >
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
                          fontSize: 16,
                          padding: 0,
                          lineHeight: 1,
                        }}
                        title="移除"
                      >
                        ×
                      </button>
                    </span>
                  ))}
                  <span style={{ alignSelf: "center", fontSize: 14, color: "var(--text-dim)" }}>
                    共 {compat.size} 款
                  </span>
                </div>
              )}
            </Field>
          )}

          <Field label="類別" required>
            <ComboBox<Category>
              value={category}
              selectedOption={categoryOpt}
              onChange={(id, opt) => {
                setCategory(id);
                setCategoryOpt(opt ?? null);
              }}
              fetchOptions={searchCategories}
              placeholder="搜尋類別(代碼/名稱)"
            />
          </Field>

          <div className="field-row">
            <Field label="軸 1 標籤">
              <input
                value={axis1Label}
                onChange={(e) => setAxis1Label(e.target.value)}
                placeholder="容量 / 功能 / 規格"
              />
            </Field>
            <Field label={`${axis1Label || "軸 1"} 值(逗號分隔,可留空)`}>
              <input
                value={axis1Text}
                onChange={(e) => setAxis1Text(e.target.value)}
                placeholder="例:256G, 512G / 一般版, 防摔版, MagSafe"
              />
            </Field>
            <Field
              label={`售價(對應${axis1Label || "軸 1"})`}
              hint={
                pricesText.trim()
                  ? "可在下方表格逐筆覆寫"
                  : "留空 = 建議零售價填 0,建議至少統一輸入一個"
              }
            >
              <input
                value={pricesText}
                onChange={(e) => setPricesText(e.target.value)}
                placeholder="例:29900, 26900"
              />
            </Field>
          </div>

          <div className="field-row">
            <Field label="軸 2 標籤">
              <input
                value={axis2Label}
                onChange={(e) => setAxis2Label(e.target.value)}
                placeholder="顏色 / 樣式 / 大小"
              />
            </Field>
            <Field label={`${axis2Label || "軸 2"} 值(逗號分隔,可留空)`}>
              <input
                value={axis2Text}
                onChange={(e) => setAxis2Text(e.target.value)}
                placeholder="例:金, 紫, 黑, 白 / 透明, 霧面"
              />
            </Field>
          </div>

          <div className="fieldset">
            <legend>屬性(套用到所有展開商品)</legend>
            <Checkbox
              checked={requiresSerial}
              onChange={(v) => {
                if (v !== requiresSerial) setSerialTouched(true);
                setRequiresSerial(v);
              }}
              label="需追蹤序號(手機/平板=勾)"
            />
            <Checkbox
              checked={allowsTelecomLine}
              onChange={setAllowsTelecomLine}
              label="可綁門號合約"
            />
            <Checkbox
              checked={allowsCommission}
              onChange={setAllowsCommission}
              label="可有業務員佣金"
            />
          </div>

          {list.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  marginBottom: 6,
                  flexWrap: "wrap",
                }}
              >
                <strong style={{ flex: 1, minWidth: 200 }}>
                  預覽:展開 {list.length} 筆,勾選 {selectedCount} 筆
                </strong>
                <MoneyInput
                  placeholder="統一售價"
                  style={{ width: 110 }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      applyPriceToAll(
                        (e.target as HTMLInputElement).value || "0",
                      );
                      (e.target as HTMLInputElement).value = "";
                    }
                  }}
                  title="輸入後按 Enter 套用至所有列"
                />
                <button
                  className="btn"
                  type="button"
                  onClick={() => toggleAll(true)}
                >
                  全選
                </button>
                <button
                  className="btn"
                  type="button"
                  onClick={() => toggleAll(false)}
                >
                  全不選
                </button>
              </div>
              <div
                style={{
                  maxHeight: 320,
                  overflow: "auto",
                  border: "1px solid var(--border)",
                  borderRadius: 3,
                }}
              >
                <table className="line-table">
                  <thead>
                    <tr>
                      <th style={{ width: 32 }}></th>
                      <th>品名</th>
                      <th style={{ width: 140 }}>規格</th>
                      <th className="num" style={{ width: 110 }}>
                        建議售價
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {list.map((c) => (
                      <tr key={c.key}>
                        <td>
                          <input
                            type="checkbox"
                            checked={c.selected}
                            onChange={(e) =>
                              toggleSelect(c.key, e.target.checked)
                            }
                          />
                        </td>
                        <td>{c.name}</td>
                        <td style={{ color: "var(--text-dim)", fontSize: 14 }}>
                          {c.spec || "—"}
                        </td>
                        <td className="num">
                          <MoneyInput
                            value={c.list_price}
                            onChange={(v) =>
                              patchPrice(c.key, v)
                            }
                            style={{ width: 90, textAlign: "right" }}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>

        <div className="modal-actions">
          <button className="btn" type="button" onClick={onClose}>
            取消
          </button>
          <button
            className="btn primary"
            type="button"
            onClick={handleCreate}
            disabled={mutation.isPending || selectedCount === 0}
          >
            {mutation.isPending
              ? "建立中…"
              : `建立 ${selectedCount} 筆`}
          </button>
        </div>
      </div>
    </div>
  );
}
