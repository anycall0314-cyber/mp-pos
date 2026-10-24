import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  useDeleteInvoiceTrack,
  useDeletePaymentMethod,
  useInvoiceTracks,
  useInvoiceTypes,
  usePaymentMethods,
  useSaveInvoiceTrack,
  useSaveInvoiceType,
  useSavePaymentMethod,
  useSaveTenantSettings,
  useSaveWarehouse,
  useTenantSettings,
  useWarehouses,
} from "@/api/hooks";
import type { InvoiceTrack, InvoiceType, PaymentMethod, PaymentMethodKind } from "@/api/types";
import { useAuth, useDefaultWarehouse } from "@/auth/AuthContext";
import { ArmButton } from "@/components/workbench/ArmButton";
import { errorText } from "@/lib/errorText";
import { Banner } from "@/components/Banner";
import { InvoiceJumpDialog } from "@/components/invoice/InvoiceJumpDialog";
import { openLabelPrint } from "@/components/labels/openLabelPrint";
import { Toolbar } from "@/components/Toolbar";
import { apiErrorText } from "@/components/workbench/errors";
import { toast } from "@/components/workbench/toast";
import { can } from "@/lib/abilities";
import {
  PERIOD_MONTHS,
  monthsLabel,
  periodOf,
  periodParts,
  periodStart,
  trackStateLabel,
  trackUsable,
} from "@/lib/invoiceTracks";
import {
  COMPANY_MODES,
  canSetStaffCost,
  ruleProblem,
  rulePayload,
  valueInput,
  valueUnit,
} from "@/lib/staffCost";
import { useCellSaves } from "@/hooks/useCellSaves";
import { CellMark } from "@/components/CellMark";
import {
  SETTINGS_TABS,
  isSettingsTab,
  openingTab,
  rememberKey,
  shownValue,
  type SettingsTab,
} from "@/lib/settingsTabs";

const PM_KINDS: { value: PaymentMethodKind; label: string }[] = [
  { value: "cash", label: "現金" },
  { value: "transfer", label: "匯款" },
  { value: "non_cash", label: "非現金" },
];

function readTab(key: string | null): string | null {
  if (!key) return null;
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function SettingsPage() {
  const warehouses = useWarehouses();
  const saveWarehouse = useSaveWarehouse();
  const types = useInvoiceTypes();
  const saveType = useSaveInvoiceType();
  const tracks = useInvoiceTracks();
  const saveTrack = useSaveInvoiceTrack();
  const delTrack = useDeleteInvoiceTrack();
  const pms = usePaymentMethods();
  const savePm = useSavePaymentMethod();
  const delPm = useDeletePaymentMethod();
  const tenantSettings = useTenantSettings();
  const saveTenantSettings = useSaveTenantSettings();

  // 分四頁(全站檢視 L02):網址指定的 → 這個人上次看的 → 一般設定
  const me = useAuth().user;
  const [params, setParams] = useSearchParams();
  const memKey = rememberKey(me?.id);
  const [tab, setTab] = useState<SettingsTab>(() => openingTab(params.get("tab"), readTab(memKey)));
  const urlTab = params.get("tab");
  useEffect(() => {
    // 已經在這一頁時從功能搜尋 / 別的連結指定了另一頁
    if (isSettingsTab(urlTab)) setTab(urlTab);
  }, [urlTab]);
  function pickTab(next: SettingsTab) {
    setTab(next);
    try {
      if (memKey) window.localStorage.setItem(memKey, next);
    } catch {
      // 瀏覽器不給存:下次從一般設定開始
    }
    setParams(
      (prev) => {
        const p = new URLSearchParams(prev);
        p.set("tab", next);
        return p;
      },
      { replace: true },
    );
  }
  // 自動存的格子各自的狀態:已存 / 沒存成(紅隊:含勾選、單選、下拉)
  const cell = useCellSaves();

  const [editing, setEditing] = useState<Partial<InvoiceTrack> | null>(null);
  // 字軌表單的期別:民國年 + 那一期的第一個月(存檔時換成那一期的第一天)。沒登記期別的舊字軌兩格都是空的
  const [periodYear, setPeriodYear] = useState("");
  const [periodMonth, setPeriodMonth] = useState("");
  const [jumping, setJumping] = useState<InvoiceTrack | null>(null);
  // 新增 / 修改 / 刪除字軌與跳號要有「發票字軌」那一項(伺服器會擋;這裡只是不讓人白按)
  const canTracks = can(useAuth().user, "invoice_tracks");
  // 鎖在門市的帳號只能設定自己門市的字軌
  const myStore = useDefaultWarehouse();
  const ownStore = myStore.locked ? myStore.id : null;
  const [editingPm, setEditingPm] = useState<Partial<PaymentMethod> | null>(null);

  const [warrantyDays, setWarrantyDays] = useState("");
  useEffect(() => {
    if (tenantSettings.data && warrantyDays === "") {
      setWarrantyDays(String(tenantSettings.data.repair_warranty_days));
    }
  }, [tenantSettings.data]);

  const [remindMonths, setRemindMonths] = useState("");
  // 人動過這一格之後,伺服器的值不再蓋進來(清空重打到一半不會被填回去)
  const [remindTouched, setRemindTouched] = useState(false);
  useEffect(() => {
    if (tenantSettings.data && !remindTouched) {
      setRemindMonths(String(tenantSettings.data.contract_remind_months));
    }
  }, [tenantSettings.data, remindTouched]);

  async function saveRemindMonths() {
    const n = Number(remindMonths);
    if (!Number.isInteger(n) || n < 1 || n > 24) {
      toast("提醒的月數需在 1 ~ 24 之間", "err");
      return;
    }
    try {
      await saveTenantSettings.mutateAsync({ contract_remind_months: n });
      toast("已儲存", "ok");
    } catch (e) {
      toast(apiErrorText(e), "err");
    }
  }

  // 業務員成本全公司的那一條(只有管理員的資料裡有;店員看不到這一段)
  const canSetStaff = canSetStaffCost(tenantSettings.data);
  const [staffMode, setStaffMode] = useState("");
  const [staffValue, setStaffValue] = useState("");
  const [staffTouched, setStaffTouched] = useState(false);
  const savedStaffMode = tenantSettings.data?.staff_cost_mode ?? "";
  const savedStaffValue = valueInput(savedStaffMode, tenantSettings.data?.staff_cost_value);
  useEffect(() => {
    // 人動過之後,伺服器的值不再蓋進來(打到一半不會被填回去)
    if (tenantSettings.data && !staffTouched) {
      setStaffMode(savedStaffMode);
      setStaffValue(savedStaffValue);
    }
  }, [tenantSettings.data, staffTouched]);

  async function saveStaffCost() {
    const problem = ruleProblem(staffMode, staffValue);
    if (problem) {
      toast(`業務員成本:${problem}`, "err");
      return;
    }
    try {
      await saveTenantSettings.mutateAsync(rulePayload(staffMode, staffValue));
      setStaffTouched(false);
      toast("已儲存", "ok");
    } catch (e) {
      toast(apiErrorText(e), "err");
    }
  }

  async function saveWarranty() {
    const n = Number(warrantyDays);
    if (!Number.isFinite(n) || n < 1 || n > 3650) {
      toast("保固天數需在 1 ~ 3650 之間", "err");
      return;
    }
    await saveTenantSettings.mutateAsync({ repair_warranty_days: n });
  }

  function startNew() {
    // 預設選「會取號」的類型:公司預設的那一種;預設是免用發票就選第一種要開發票的
    const numbered = (types.data ?? []).filter((t) => t.code !== "none");
    const firstType = numbered.find((t) => t.is_default) ?? numbered[0] ?? types.data?.[0];
    const stores = warehouses.data ?? [];
    const now = periodOf(new Date());
    setPeriodYear(String(now.rocYear));
    setPeriodMonth(String(now.firstMonth));
    setEditing({
      invoice_type: firstType?.id ?? 0,
      // 只有一間門市、或這個帳號鎖在門市:直接帶好;不然要自己選(每間門市的發票機各有一捲紙)
      warehouse: ownStore ?? (stores.length === 1 ? stores[0].id : null),
      prefix: "",
      range_start: 0,
      range_end: 0,
      is_active: true,
      note: "",
    });
  }

  function startEdit(t: InvoiceTrack) {
    const period = periodParts(t.period_start);
    setPeriodYear(period ? String(period.rocYear) : "");
    setPeriodMonth(period ? String(period.firstMonth) : "");
    setEditing(t);
  }

  // 期別兩格都填了才算有選;沒登記期別的舊字軌可以照舊留空
  const pickedPeriod = periodStart(Number(periodYear), Number(periodMonth));
  const periodMissing = !pickedPeriod && (!editing?.id || !!editing?.period_start || !!periodYear || !!periodMonth);

  async function submitTrack() {
    if (!editing) return;
    // 只送改得了的欄位:「下一張」只有新增時送(之後要改用跳號)
    const body: Partial<InvoiceTrack> & { id?: number } = {
      id: editing.id,
      invoice_type: editing.invoice_type,
      warehouse: editing.warehouse ?? null,
      prefix: editing.prefix,
      range_start: editing.range_start,
      range_end: editing.range_end,
      is_active: editing.is_active,
      note: editing.note,
    };
    if (pickedPeriod) body.period_start = pickedPeriod;
    if (!editing.id && editing.next_number !== undefined) body.next_number = editing.next_number;
    try {
      await saveTrack.mutateAsync(body);
      setEditing(null);
    } catch (e) {
      // banner picks up via mutation state
    }
  }

  // 按「儲存」的那幾塊打到一半沒存的:分頁上一直標「還沒儲存」(紅隊:不跳窗、不只提醒一次)
  const unsaved: Record<SettingsTab, boolean> = {
    general:
      (!!tenantSettings.data && warrantyDays.trim() !== "" &&
        warrantyDays.trim() !== String(tenantSettings.data.repair_warranty_days)) ||
      (remindTouched && !!tenantSettings.data && remindMonths.trim() !== String(tenantSettings.data.contract_remind_months)) ||
      (canSetStaff && (staffMode !== savedStaffMode || (staffMode !== "" && staffValue.trim() !== savedStaffValue))),
    stores: false,
    invoice: editing !== null,
    payment: editingPm !== null,
  };

  return (
    <div className="page">
      <Toolbar title="系統設定" />
      <div className="tab-switcher settings-tabs" role="tablist" aria-label="系統設定">
        {SETTINGS_TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            className={`tab-switcher-item${tab === t.key ? " active" : ""}`}
            onClick={() => pickTab(t.key)}
          >
            {t.label}
            {unsaved[t.key] && <span className="settings-unsaved">還沒儲存</span>}
          </button>
        ))}
      </div>
      <div className="entry-body">
        <div role="tabpanel" hidden={tab !== "general"}>
          <h3 style={{ marginTop: 0 }}>維修</h3>
          <p style={{ color: "var(--text-dim)", fontSize: 14 }}>
            返修保固天數:自原維修單完修日起算,在此範圍內視為保固有效。
          </p>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              marginBottom: 24,
              flexWrap: "wrap",
            }}
          >
            <label style={{ fontSize: 14 }}>保固天數</label>
            <input
              type="number"
              min={1}
              max={3650}
              value={warrantyDays}
              onChange={(e) => setWarrantyDays(e.target.value)}
              style={{ width: 120 }}
            />
            <span style={{ fontSize: 14, color: "var(--text-dim)" }}>
              天(預設 90 天)
            </span>
            <button
              type="button"
              className="btn primary"
              onClick={saveWarranty}
              disabled={
                saveTenantSettings.isPending ||
                !tenantSettings.data ||
                String(tenantSettings.data?.repair_warranty_days) ===
                  warrantyDays.trim()
              }
            >
              {saveTenantSettings.isPending ? "儲存中…" : "儲存"}
            </button>
          </div>

          <h3>電信</h3>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              marginBottom: 24,
              flexWrap: "wrap",
            }}
          >
            <label style={{ fontSize: 14 }}>合約到期前</label>
            <input
              type="number"
              min={1}
              max={24}
              value={remindMonths}
              aria-label="合約到期前幾個月提醒"
              onChange={(e) => {
                setRemindTouched(true);
                setRemindMonths(e.target.value);
              }}
              style={{ width: 120 }}
            />
            <span style={{ fontSize: 14, color: "var(--text-dim)" }}>
              個月列入待聯絡(預設 3 個月)
            </span>
            <button
              type="button"
              className="btn primary"
              onClick={saveRemindMonths}
              disabled={
                saveTenantSettings.isPending ||
                !tenantSettings.data ||
                String(tenantSettings.data?.contract_remind_months) === remindMonths.trim()
              }
            >
              {saveTenantSettings.isPending ? "儲存中…" : "儲存"}
            </button>
          </div>

          {canSetStaff && (
            <>
              <h3>業務員成本</h3>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                  marginBottom: 24,
                  flexWrap: "wrap",
                }}
              >
                <label style={{ fontSize: 14 }}>全公司</label>
                <select
                  value={staffMode}
                  aria-label="業務員成本全公司的算法"
                  onChange={(e) => {
                    setStaffTouched(true);
                    setStaffMode(e.target.value);
                  }}
                >
                  {COMPANY_MODES.map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
                {staffMode && (
                  <>
                    <input
                      inputMode="decimal"
                      value={staffValue}
                      aria-label="業務員成本加多少"
                      onChange={(e) => {
                        setStaffTouched(true);
                        setStaffValue(e.target.value);
                      }}
                      style={{ width: 120 }}
                    />
                    <span style={{ fontSize: 14, color: "var(--text-dim)" }}>
                      {valueUnit(staffMode)}
                    </span>
                  </>
                )}
                <button
                  type="button"
                  className="btn primary"
                  onClick={saveStaffCost}
                  disabled={
                    saveTenantSettings.isPending ||
                    (staffMode === savedStaffMode &&
                      (staffMode === "" || staffValue.trim() === savedStaffValue))
                  }
                >
                  {saveTenantSettings.isPending ? "儲存中…" : "儲存"}
                </button>
              </div>
            </>
          )}

          <h3>標籤</h3>
          <div style={{ marginBottom: 24 }}>
            <button
              type="button"
              className="btn"
              onClick={() => openLabelPrint("test=1")}
            >
              列印測試標籤
            </button>
          </div>
        </div>
        <div role="tabpanel" hidden={tab !== "stores"}>
          <h3 style={{ marginTop: 0 }}>門市</h3>
          <p style={{ color: "var(--text-dim)", fontSize: 14 }}>
            門市地址 / 電話會印在收據(代收話費等)上。代碼 / 名稱請聯絡管理員調整。
          </p>

          {saveWarehouse.isError && (
            <Banner
              kind="error"
              message={`儲存失敗:${String(saveWarehouse.error ?? "")}`}
            />
          )}

          {warehouses.isLoading && <div className="md-empty">載入中…</div>}
          {!warehouses.isLoading && (
            <table className="line-table" style={{ maxWidth: 920 }}>
              <thead>
                <tr>
                  <th style={{ width: 80 }}>代碼</th>
                  <th style={{ width: 140 }}>名稱</th>
                  <th>地址</th>
                  <th style={{ width: 160 }}>電話</th>
                  <th style={{ width: 70, textAlign: "center" }}>啟用</th>
                </tr>
              </thead>
              <tbody>
                {(warehouses.data ?? []).map((w) => (
                  <tr key={w.id}>
                    <td>{w.code}</td>
                    <td>{w.name}</td>
                    <td>
                      <input
                        defaultValue={w.address}
                        placeholder="收據抬頭顯示用"
                        onBlur={(e) => {
                          cell.blur(`w${w.id}:address`, e.target.value, w.address, (v) => saveWarehouse.mutateAsync({ id: w.id, address: v }));
                        }}
                      />
                      <CellMark cell={cell} k={`w${w.id}:address`} />
                    </td>
                    <td>
                      <input
                        defaultValue={w.phone}
                        placeholder="例:04-12345678"
                        onBlur={(e) => {
                          cell.blur(`w${w.id}:phone`, e.target.value, w.phone, (v) => saveWarehouse.mutateAsync({ id: w.id, phone: v }));
                        }}
                      />
                      <CellMark cell={cell} k={`w${w.id}:phone`} />
                    </td>
                    <td style={{ textAlign: "center" }}>
                      <input
                        type="checkbox"
                        checked={shownValue(cell.get<boolean>(`w${w.id}:active`), w.is_active)}
                        onChange={(e) => {
                          const v = e.target.checked;
                          void cell.save(`w${w.id}:active`, v, () => saveWarehouse.mutateAsync({ id: w.id, is_active: v }));
                        }}
                      />
                      <CellMark cell={cell} k={`w${w.id}:active`} />
                    </td>
                  </tr>
                ))}
                {(warehouses.data ?? []).length === 0 && (
                  <tr>
                    <td colSpan={5} className="md-empty">
                      尚無門市資料
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </div>
        {/* 發票:字軌在上面、類型在下面(紅隊:開單送進來的是要新增字軌) */}
        <div role="tabpanel" hidden={tab !== "invoice"}>
          <h3 style={{ marginTop: 0 }}>發票字軌</h3>
          <p style={{ color: "var(--text-dim)", fontSize: 14 }}>
            一間門市、一期一條。開單只取自己門市當期的字軌。
          </p>

          {canTracks && (
            <div style={{ marginBottom: 8 }}>
              <button className="btn primary" onClick={startNew}>
                新增字軌
              </button>
            </div>
          )}

          {saveTrack.isError && (
            <Banner kind="error" message={`儲存失敗:${apiErrorText(saveTrack.error)}`} />
          )}
          {delTrack.isError && (
            <Banner kind="error" message={`刪除失敗:${apiErrorText(delTrack.error)}`} />
          )}

          {editing && (
            <div className="fieldset" style={{ marginBottom: 12, maxWidth: 720 }}>
              <legend>{editing.id ? "編輯字軌" : "新增字軌"}</legend>
              <div className="field-row-3">
                <label>
                  發票類型
                  <select
                    value={editing.invoice_type ?? 0}
                    onChange={(e) =>
                      setEditing({
                        ...editing,
                        invoice_type: Number(e.target.value),
                      })
                    }
                  >
                    {(types.data ?? []).map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  門市
                  <select
                    value={editing.warehouse ?? ""}
                    disabled={ownStore !== null}
                    onChange={(e) =>
                      setEditing({
                        ...editing,
                        warehouse: e.target.value ? Number(e.target.value) : null,
                      })
                    }
                  >
                    {/* 空的選項:新增時 = 還沒選(存不了);舊的共用字軌 = 全部門市 */}
                    {(editing.warehouse ?? null) === null && (
                      <option value="">{editing.id ? "全部門市" : "請選擇"}</option>
                    )}
                    {(warehouses.data ?? []).map((w) => (
                      <option key={w.id} value={w.id}>
                        {w.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  字軌
                  <input
                    value={editing.prefix ?? ""}
                    onChange={(e) =>
                      setEditing({
                        ...editing,
                        prefix: e.target.value.toUpperCase(),
                      })
                    }
                    maxLength={4}
                    placeholder="例:AB"
                  />
                </label>
              </div>
              <div className="field-row-3">
                <label>
                  年度
                  <input
                    type="number"
                    value={periodYear}
                    onChange={(e) => setPeriodYear(e.target.value)}
                    placeholder="民國"
                  />
                </label>
                <label>
                  月份
                  <select value={periodMonth} onChange={(e) => setPeriodMonth(e.target.value)}>
                    {!periodMonth && <option value="">請選擇</option>}
                    {PERIOD_MONTHS.map((m) => (
                      <option key={m} value={m}>
                        {monthsLabel(m)}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="field-row-3">
                <label>
                  起號
                  <input
                    type="number"
                    value={editing.range_start ?? 0}
                    onChange={(e) =>
                      setEditing({
                        ...editing,
                        range_start: Number(e.target.value),
                      })
                    }
                  />
                </label>
                <label>
                  迄號
                  <input
                    type="number"
                    value={editing.range_end ?? 0}
                    onChange={(e) =>
                      setEditing({
                        ...editing,
                        range_end: Number(e.target.value),
                      })
                    }
                  />
                </label>
                {/* 「下一張」只有新增時可以填(那一捲已經用掉幾張);之後要改用清單上的「跳號」 */}
                {!editing.id && (
                  <label>
                    下一張
                    <input
                      type="number"
                      value={editing.next_number ?? ""}
                      placeholder="空白 = 起號"
                      onChange={(e) =>
                        setEditing({
                          ...editing,
                          next_number: e.target.value === ""
                            ? undefined
                            : Number(e.target.value),
                        })
                      }
                    />
                  </label>
                )}
              </div>
              <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <input
                  type="checkbox"
                  checked={editing.is_active ?? true}
                  onChange={(e) =>
                    setEditing({ ...editing, is_active: e.target.checked })
                  }
                />
                啟用
              </label>
              <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
                <button className="btn" type="button" onClick={() => setEditing(null)}>
                  取消
                </button>
                <button
                  className="btn primary"
                  type="button"
                  onClick={submitTrack}
                  disabled={
                    saveTrack.isPending ||
                    !editing.prefix ||
                    periodMissing ||
                    (!editing.id && (editing.warehouse ?? null) === null)
                  }
                >
                  {saveTrack.isPending ? "儲存中…" : "儲存"}
                </button>
              </div>
            </div>
          )}

          {tracks.isLoading && <div className="md-empty">載入中…</div>}
          {!tracks.isLoading && (
            <table className="line-table" style={{ maxWidth: 1080 }}>
              <thead>
                <tr>
                  <th>門市</th>
                  <th>類型</th>
                  <th>期別</th>
                  <th>字軌</th>
                  <th className="num">起號</th>
                  <th className="num">迄號</th>
                  <th className="num">下一張</th>
                  <th>狀態</th>
                  <th>動作</th>
                </tr>
              </thead>
              <tbody>
                {(tracks.data ?? []).map((t) => (
                  <tr key={t.id}>
                    <td>{t.warehouse_name || "全部門市"}</td>
                    <td>{t.invoice_type_name}</td>
                    <td>{t.period_label || "—"}</td>
                    <td>
                      <code>{t.prefix}</code>
                    </td>
                    <td className="num">{t.range_start}</td>
                    <td className="num">{t.range_end}</td>
                    <td className="num">
                      {t.is_depleted ? (
                        "—"
                      ) : (
                        <span style={trackUsable(t) ? { color: "var(--success-text-soft)" } : undefined}>
                          {t.next_invoice_no}
                        </span>
                      )}
                    </td>
                    <td style={trackUsable(t) ? undefined : { color: "var(--danger-text)" }}>
                      {trackStateLabel(t)}
                    </td>
                    <td className="row-actions">
                      {canTracks && (
                        <>
                          <button className="btn small" onClick={() => setJumping(t)}>跳號</button>
                          {/* 共用的舊字軌:鎖在門市的帳號只能跳號,改與刪要管理員 */}
                          {(ownStore === null || t.warehouse === ownStore) && (
                            <>
                              <button className="btn small" onClick={() => startEdit(t)}>編輯</button>
                              <ArmButton
                                label="刪除"
                                className="btn small danger"
                                onConfirm={() =>
                                  delTrack.mutateAsync(t.id).catch((e) => toast(`刪除失敗:${errorText(e)}`, "err"))
                                }
                              />
                            </>
                          )}
                        </>
                      )}
                    </td>
                  </tr>
                ))}
                {(tracks.data ?? []).length === 0 && (
                  <tr>
                    <td colSpan={9} className="md-empty">
                      還沒有字軌
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}

          {jumping && <InvoiceJumpDialog track={jumping} onClose={() => setJumping(null)} />}
          <h3 style={{ marginTop: 32 }}>發票類型</h3>
          <p style={{ color: "var(--text-dim)", fontSize: 14 }}>
            內建 6 種,可切換啟用 / 指定預設 / 改名稱。銷貨、進貨單的下拉只列「啟用中」。
          </p>

          {saveType.isError && (
            <Banner kind="error" message={`儲存失敗:${String(saveType.error ?? "")}`} />
          )}

          {types.isLoading && <div className="md-empty">載入中…</div>}
          {!types.isLoading && (
            <table className="line-table" style={{ maxWidth: 720 }}>
              <thead>
                <tr>
                  <th>顯示名稱</th>
                  <th style={{ width: 80 }} className="num">排序</th>
                  <th style={{ width: 70, textAlign: "center" }}>啟用</th>
                  <th style={{ width: 70, textAlign: "center" }}>預設</th>
                  <th style={{ width: 130 }}>帶入課稅別</th>
                </tr>
              </thead>
              <tbody>
                {(types.data ?? []).map((t) => (
                  <tr key={t.id}>
                    <td>
                      <input
                        defaultValue={t.name}
                        onBlur={(e) => {
                          cell.blur(`t${t.id}:name`, e.target.value, t.name, (v) => saveType.mutateAsync({ id: t.id, name: v }));
                        }}
                      />
                      <CellMark cell={cell} k={`t${t.id}:name`} />
                    </td>
                    <td>
                      <input
                        type="number"
                        className="num-input"
                        defaultValue={t.sort_order}
                        onBlur={(e) => {
                          cell.blur(`t${t.id}:sort`, Number(e.target.value), t.sort_order, (v) => saveType.mutateAsync({ id: t.id, sort_order: v }));
                        }}
                      />
                      <CellMark cell={cell} k={`t${t.id}:sort`} />
                    </td>
                    <td style={{ textAlign: "center" }}>
                      <input
                        type="checkbox"
                        checked={shownValue(cell.get<boolean>(`t${t.id}:active`), t.is_active)}
                        onChange={(e) => {
                          const v = e.target.checked;
                          void cell.save(`t${t.id}:active`, v, () => saveType.mutateAsync({ id: t.id, is_active: v }));
                        }}
                      />
                      <CellMark cell={cell} k={`t${t.id}:active`} />
                    </td>
                    <td style={{ textAlign: "center" }}>
                      <input
                        type="radio"
                        name="invoice_default"
                        checked={shownValue(cell.get<number>("t:default"), (types.data ?? []).find((x) => x.is_default)?.id ?? 0) === t.id}
                        onChange={() => void cell.save("t:default", t.id, () => saveType.mutateAsync({ id: t.id, is_default: true }))}
                      />
                      {cell.get<number>("t:default")?.value === t.id && <CellMark cell={cell} k="t:default" />}
                    </td>
                    <td>
                      {/* 開單選了這種發票,課稅別跟著帶什麼(全站檢視 A1:發票在舊系統開、稅有繳的店,免用要帶應稅內含) */}
                      <select
                        value={shownValue(cell.get<string>(`t${t.id}:tax`), t.tax_method ?? "")}
                        onChange={(e) => {
                          const v = e.target.value as InvoiceType["tax_method"];
                          void cell.save(`t${t.id}:tax`, v ?? "", () => saveType.mutateAsync({ id: t.id, tax_method: v }));
                        }}
                      >
                        <option value="">不帶</option>
                        <option value="taxable_included">應稅內含</option>
                        <option value="taxable_excluded">應稅外加</option>
                        <option value="untaxed">未稅</option>
                      </select>
                      <CellMark cell={cell} k={`t${t.id}:tax`} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div role="tabpanel" hidden={tab !== "payment"}>
          <h3 style={{ marginTop: 0 }}>付款方式</h3>
          <p style={{ color: "var(--text-dim)", fontSize: 14 }}>
            結帳時可選的付款通路。分類:
            <b style={{ color: "var(--success-text-soft)" }}>現金</b> 計入當日營業現金;
            <b>匯款</b> 與
            <b>非現金</b>(刷卡 / LinePay / 街口 / 全支付 / Apple Pay…)
            不計入當日現金。可自由新增、停用、設預設。
          </p>

          <div style={{ marginBottom: 8 }}>
            <button
              className="btn primary"
              onClick={() =>
                setEditingPm({
                  code: "",
                  name: "",
                  kind: "non_cash",
                  sort_order: 100,
                  is_active: true,
                  is_default: false,
                  note: "",
                })
              }
            >
              新增付款方式
            </button>
          </div>

          {savePm.isError && (
            <Banner kind="error" message={`儲存失敗:${String(savePm.error ?? "")}`} />
          )}

          {editingPm && (
            <div className="fieldset" style={{ marginBottom: 12, maxWidth: 720 }}>
              <legend>{editingPm.id ? "編輯付款方式" : "新增付款方式"}</legend>
              <div className="field-row-3">
                <label>
                  顯示名稱
                  <input
                    value={editingPm.name ?? ""}
                    onChange={(e) =>
                      setEditingPm({ ...editingPm, name: e.target.value })
                    }
                    placeholder="例:LinePay / 街口 / 全支付"
                  />
                </label>
                <label>
                  分類
                  <select
                    value={editingPm.kind ?? "non_cash"}
                    onChange={(e) =>
                      setEditingPm({
                        ...editingPm,
                        kind: e.target.value as PaymentMethodKind,
                      })
                    }
                  >
                    {PM_KINDS.map((k) => (
                      <option key={k.value} value={k.value}>
                        {k.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="field-row-3">
                <label>
                  排序
                  <input
                    type="number"
                    className="num-input"
                    value={editingPm.sort_order ?? 0}
                    onChange={(e) =>
                      setEditingPm({
                        ...editingPm,
                        sort_order: Number(e.target.value),
                      })
                    }
                  />
                </label>
                <label style={{ alignSelf: "end" }}>
                  <input
                    type="checkbox"
                    checked={editingPm.is_active ?? true}
                    onChange={(e) =>
                      setEditingPm({
                        ...editingPm,
                        is_active: e.target.checked,
                      })
                    }
                  />{" "}
                  啟用
                </label>
                <label style={{ alignSelf: "end" }}>
                  <input
                    type="checkbox"
                    checked={editingPm.is_default ?? false}
                    onChange={(e) =>
                      setEditingPm({
                        ...editingPm,
                        is_default: e.target.checked,
                      })
                    }
                  />{" "}
                  設為預設
                </label>
              </div>
              <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
                <button
                  className="btn"
                  type="button"
                  onClick={() => setEditingPm(null)}
                >
                  取消
                </button>
                <button
                  className="btn primary"
                  type="button"
                  disabled={
                    savePm.isPending || !editingPm.name
                  }
                  onClick={async () => {
                    await savePm.mutateAsync(
                      editingPm as Partial<PaymentMethod> & { id?: number },
                    );
                    setEditingPm(null);
                  }}
                >
                  {savePm.isPending ? "儲存中…" : "儲存"}
                </button>
              </div>
            </div>
          )}

          {pms.isLoading && <div className="md-empty">載入中…</div>}
          {!pms.isLoading && (
            <table className="line-table" style={{ maxWidth: 880 }}>
              <thead>
                <tr>
                  <th>顯示名稱</th>
                  <th style={{ width: 80 }}>分類</th>
                  <th style={{ width: 70 }} className="num">排序</th>
                  <th style={{ width: 70, textAlign: "center" }}>啟用</th>
                  <th style={{ width: 70, textAlign: "center" }}>預設</th>
                  <th style={{ width: 110 }}>動作</th>
                </tr>
              </thead>
              <tbody>
                {(pms.data ?? []).map((p) => (
                  <tr key={p.id}>
                    <td>{p.name}</td>
                    <td>
                      <span
                        style={{
                          color:
                            p.kind === "cash"
                              ? "var(--success-text-soft)"
                              : p.kind === "transfer"
                              ? "#80b0d0"
                              : "var(--text-dim)",
                        }}
                      >
                        {p.kind_label}
                      </span>
                    </td>
                    <td className="num">{p.sort_order}</td>
                    <td style={{ textAlign: "center" }}>
                      <input
                        type="checkbox"
                        checked={shownValue(cell.get<boolean>(`p${p.id}:active`), p.is_active)}
                        onChange={(e) => {
                          const v = e.target.checked;
                          void cell.save(`p${p.id}:active`, v, () => savePm.mutateAsync({ id: p.id, is_active: v }));
                        }}
                      />
                      <CellMark cell={cell} k={`p${p.id}:active`} />
                    </td>
                    <td style={{ textAlign: "center" }}>
                      <input
                        type="radio"
                        name="pm_default"
                        checked={shownValue(cell.get<number>("p:default"), (pms.data ?? []).find((x) => x.is_default)?.id ?? 0) === p.id}
                        onChange={() => void cell.save("p:default", p.id, () => savePm.mutateAsync({ id: p.id, is_default: true }))}
                      />
                      {cell.get<number>("p:default")?.value === p.id && <CellMark cell={cell} k="p:default" />}
                    </td>
                    <td className="row-actions">
                      <button className="btn small" onClick={() => setEditingPm(p)}>編輯</button>
                      <ArmButton
                        label="刪除"
                        className="btn small danger"
                        onConfirm={() =>
                          delPm.mutateAsync(p.id).catch((e) => toast(`刪除失敗:${errorText(e)}`, "err"))
                        }
                      />
                    </td>
                  </tr>
                ))}
                {(pms.data ?? []).length === 0 && (
                  <tr>
                    <td colSpan={6} className="md-empty">
                      尚未設定任何付款方式
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </div>
      </div>
      {/* 版本(2026-10-23 從今日總覽搬來;UI 改善計劃 UI-10:技術資訊不放在工作的第一頁) */}
      <div className="settings-version">版本 {__APP_VERSION__}</div>
    </div>
  );
}
