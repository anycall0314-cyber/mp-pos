import { useEffect, useMemo, useState } from "react";

import { useSaveTelecomPlan, useTelecomPlans } from "@/api/hooks";
import type { TelecomPlan } from "@/api/types";
import { useCurrentUser } from "@/auth/AuthContext";
import { useArm } from "@/components/workbench/useArm";
import { Toolbar } from "@/components/Toolbar";
import {
  MasterDetail,
  MasterColumn,
  DetailTab,
} from "@/components/master-detail/MasterDetail";
import {
  companyCommissionInput,
  companyCommissionPayload,
  showCompanyCommission,
} from "@/lib/commission";
import { intStr, money } from "@/lib/money";
import { isManager } from "@/lib/roles";
import { MoneyInput } from "@/components/MoneyInput";

import { BulkAddTelecomPlans } from "./BulkAddTelecomPlans";
import { TelecomPlanForm } from "./TelecomPlanForm";
import { errorText } from "@/lib/errorText";

/** 列裡控制項的名字用:同名方案不少,帶電信商與月租才分得出來(全站控制項 MC-05) */
function planName(r: TelecomPlan): string {
  return `${r.carrier_name} ${r.name || "未命名方案"} ${money(r.monthly_fee)}`;
}

export function TelecomPlansPage() {
  // 刪除 / 套用這類按錯代價大的:再按一次才做(全站檢視 G1:不跳瀏覽器的確認框)
  const arm = useArm();
  const { data, isLoading, isError, error } = useTelecomPlans({
    includeInactive: true,
  });
  const savePlan = useSaveTelecomPlan();
  // 方案(含佣金)只有管理員能改:店員看得到,但沒有會改資料的按鈕與輸入框(伺服器也會擋)
  const canEdit = isManager(useCurrentUser()?.profile?.role);
  // 新增 / 編輯 / 批次新增:整頁換掉清單(owner 2026-10-25 不要 modal);清單留著不卸下,回來時搜尋、勾選、捲動都還在
  const [view, setView] = useState<{ kind: "edit"; plan: TelecomPlan } | { kind: "new" } | { kind: "bulk" } | null>(null);
  const [bulkResult, setBulkResult] = useState<string | null>(null);
  function flashResult(text: string) {
    setBulkResult(text);
    window.setTimeout(() => setBulkResult(null), 4000);
  }
  const [query, setQuery] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  // inline 佣金編輯暫存:key=plan.id, value=輸入中字串。
  // 沒鍵或鍵不存在 → 顯示原值;onBlur 比對若不同就 PATCH
  const [editCommission, setEditCommission] = useState<Record<number, string>>(
    {},
  );
  // 公司佣金(只有管理員有這一欄)一樣可以在清單上直接改;空的 = 還沒設定
  const [editCompany, setEditCompany] = useState<Record<number, string>>({});
  // 正在 inline PATCH 的方案 id(視覺提示用)
  const [savingIds, setSavingIds] = useState<Set<number>>(new Set());
  const [batchPending, setBatchPending] = useState(false);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = data ?? [];
    if (!q) return list;
    return list.filter((p) => {
      const hay = [
        p.name,
        p.code,
        p.carrier_code,
        p.carrier_name,
        p.kind_label,
        String(p.monthly_fee),
        String(p.contract_months),
        p.note,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
  }, [data, query]);

  // 當前可見列表的「全選」狀態
  const allFilteredSelected =
    filtered.length > 0 && filtered.every((p) => selectedIds.has(p.id));

  function toggleOne(id: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  function toggleAllFiltered(check: boolean) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      for (const p of filtered) {
        if (check) next.add(p.id);
        else next.delete(p.id);
      }
      return next;
    });
  }
  function clearSelection() {
    setSelectedIds(new Set());
  }

  // data refetch 後,把 editCommission 中已和伺服器一致的條目清掉(消 dirty 黃底)
  useEffect(() => {
    if (!data) return;
    setEditCommission((prev) => {
      let changed = false;
      const next: Record<number, string> = {};
      for (const [idStr, v] of Object.entries(prev)) {
        const id = Number(idStr);
        const plan = data.find((p) => p.id === id);
        const planIntStr = plan
          ? intStr(plan.commission)
          : null;
        const editIntStr = intStr(v);
        if (plan && editIntStr === planIntStr) {
          changed = true;
        } else {
          next[id] = v;
        }
      }
      return changed ? next : prev;
    });
    setEditCompany((prev) => {
      const next: Record<number, string> = {};
      let changed = false;
      for (const [idStr, v] of Object.entries(prev)) {
        const plan = data.find((p) => p.id === Number(idStr));
        if (plan && companyCommissionPayload(v) === companyCommissionPayload(companyCommissionInput(plan.company_commission))) {
          changed = true;
        } else {
          next[Number(idStr)] = v;
        }
      }
      return changed ? next : prev;
    });
  }, [data]);

  function markSaving(id: number, on: boolean) {
    setSavingIds((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  // 一筆 inline 編輯佣金:onBlur 觸發,值未變不動。一律送整數
  async function commitCommission(plan: TelecomPlan) {
    const v = editCommission[plan.id];
    if (v == null) return;
    const nextIntStr = intStr(v);
    const originalIntStr = intStr(plan.commission);
    if (!v.trim() || nextIntStr === originalIntStr) {
      // 還原成原值,清掉編輯暫存
      setEditCommission((s) => {
        const next = { ...s };
        delete next[plan.id];
        return next;
      });
      return;
    }
    markSaving(plan.id, true);
    try {
      await savePlan.mutateAsync({ id: plan.id, commission: nextIntStr });
      // 留 editCommission 條目,下次 data refetch 後若一致再清(下方 useEffect)
    } catch (e) {
      setBulkResult(
        `${plan.name}:佣金更新失敗:${e instanceof Error ? e.message : e}`,
      );
      setTimeout(() => setBulkResult(null), 6000);
    } finally {
      markSaving(plan.id, false);
    }
  }

  // 一筆 inline 編輯公司佣金:離開欄位才存;清空 = 回到還沒設定
  async function commitCompany(plan: TelecomPlan) {
    const v = editCompany[plan.id];
    if (v == null) return;
    const next = companyCommissionPayload(v);
    const original = companyCommissionPayload(companyCommissionInput(plan.company_commission));
    if (next === original) {
      setEditCompany((s) => {
        const rest = { ...s };
        delete rest[plan.id];
        return rest;
      });
      return;
    }
    markSaving(plan.id, true);
    try {
      await savePlan.mutateAsync({ id: plan.id, company_commission: next });
    } catch (e) {
      setBulkResult(
        `${plan.name}:公司佣金更新失敗:${e instanceof Error ? e.message : e}`,
      );
      setTimeout(() => setBulkResult(null), 6000);
    } finally {
      markSaving(plan.id, false);
    }
  }

  // 一筆 inline 切上下架:onChange 立即觸發
  async function commitActive(plan: TelecomPlan, active: boolean) {
    markSaving(plan.id, true);
    try {
      await savePlan.mutateAsync({ id: plan.id, is_active: active });
    } catch (e) {
      setBulkResult(
        `${plan.name}:狀態更新失敗:${e instanceof Error ? e.message : e}`,
      );
      setTimeout(() => setBulkResult(null), 6000);
    } finally {
      markSaving(plan.id, false);
    }
  }

  const selKey = Array.from(selectedIds).sort((a, b) => a - b).join(",");
  async function patchSelected(patch: Partial<TelecomPlan>, label: string) {
    if (selectedIds.size === 0) return;
    // 綁在這一次勾的那幾筆上:勾選換了就重來
    if (!arm.confirm(`batch:${label}:${selKey}`)) return;
    setBatchPending(true);
    try {
      await Promise.all(
        Array.from(selectedIds).map((id) =>
          savePlan.mutateAsync({ id, ...patch }),
        ),
      );
      setBulkResult(`已完成「${label}」共 ${selectedIds.size} 筆`);
      setTimeout(() => setBulkResult(null), 4000);
      clearSelection();
    } catch (e) {
      setBulkResult(
        `批次失敗:${errorText(e)}`,
      );
      setTimeout(() => setBulkResult(null), 6000);
    } finally {
      setBatchPending(false);
    }
  }

  const columns: MasterColumn<TelecomPlan>[] = useMemo(
    () => ([
      {
        key: "select",
        header: (
          <input
            type="checkbox"
            checked={allFilteredSelected}
            onChange={(e) => toggleAllFiltered(e.target.checked)}
            onClick={(e) => e.stopPropagation()}
            title="勾選此頁全部"
            aria-label="勾選此頁全部方案"
          />
        ),
        render: (r) => (
          <input
            type="checkbox"
            checked={selectedIds.has(r.id)}
            aria-label={`選取 ${planName(r)}`}
            onChange={() => toggleOne(r.id)}
            onClick={(e) => e.stopPropagation()}
          />
        ),
      },
      { key: "name", header: "專案名稱", render: (r) => r.name || "—" },
      {
        key: "carrier",
        header: "電信商",
        render: (r) => `${r.carrier_code} ${r.carrier_name}`,
      },
      {
        key: "monthly_fee",
        header: "月租",
        render: (r) => (
          <span className="num">
            {money(r.monthly_fee)}
          </span>
        ),
      },
      {
        key: "contract_months",
        header: "綁約",
        render: (r) => <span className="num">{r.contract_months} 月</span>,
      },
      { key: "kind", header: "類型", render: (r) => r.kind_label, side: true },
      {
        key: "commission",
        side: true,
        header: "業務員佣金",
        render: (r) => {
          if (!canEdit) return <span className="num">{money(r.commission)}</span>;
          const original = intStr(r.commission);
          const editing = editCommission[r.id];
          const value = editing ?? original;
          const dirty = editing != null && editing !== original;
          return (
            <MoneyInput
              min="0"
              className="num-input"
              value={value}
              aria-label={`${planName(r)} 的業務員佣金`}
              onChange={(v) =>
                setEditCommission((s) => ({ ...s, [r.id]: v }))
              }
              onBlur={() => commitCommission(r)}
              onKeyDown={(e) => {
                if (e.key === "Enter") (e.target as HTMLInputElement).blur();
              }}
              onClick={(e) => e.stopPropagation()}
              disabled={savingIds.has(r.id)}
              style={{
                width: 90,
                textAlign: "right",
                background: dirty
                  ? "rgba(255, 200, 0, 0.12)"
                  : undefined,
              }}
            />
          );
        },
      },
      {
        // 公司實際拿的:只有管理員的資料裡有,這一欄也只給管理員
        key: "company_commission",
        side: true,
        header: "公司佣金",
        render: (r) => {
          const original = companyCommissionInput(r.company_commission);
          const editing = editCompany[r.id];
          const dirty = editing != null && companyCommissionPayload(editing) !== companyCommissionPayload(original);
          return (
            <MoneyInput
              min="0"
              className="num-input"
              value={editing ?? original}
              placeholder="未設定"
              aria-label={`${planName(r)} 的公司佣金`}
              onChange={(v) => setEditCompany((s) => ({ ...s, [r.id]: v }))}
              onBlur={() => commitCompany(r)}
              onKeyDown={(e) => {
                if (e.key === "Enter") (e.target as HTMLInputElement).blur();
              }}
              onClick={(e) => e.stopPropagation()}
              disabled={savingIds.has(r.id)}
              style={{
                width: 90,
                textAlign: "right",
                background: dirty ? "rgba(255, 200, 0, 0.12)" : undefined,
              }}
            />
          );
        },
      },
      {
        key: "is_active",
        header: "啟用",
        render: (r) => !canEdit ? (
          r.is_active ? "啟用" : "停用"
        ) : (
          <input
            type="checkbox"
            checked={r.is_active}
            aria-label={`${planName(r)} 啟用`}
            onChange={(e) => commitActive(r, e.target.checked)}
            onClick={(e) => e.stopPropagation()}
            disabled={savingIds.has(r.id)}
          />
        ),
      },
    ] as MasterColumn<TelecomPlan>[]).filter(
      (c) => canEdit || (c.key !== "select" && c.key !== "company_commission"),
    ),
    [allFilteredSelected, selectedIds, editCommission, editCompany, savingIds, canEdit],
  );

  const tabs: DetailTab<TelecomPlan>[] = [
    {
      key: "basic",
      label: "基本",
      render: (r) => (
        <div>
          <dl>
            <dt>專案名稱</dt>
            <dd>{r.name || "—"}</dd>
            <dt>電信商</dt>
            <dd>
              {r.carrier_code} {r.carrier_name}
            </dd>
            <dt>月租</dt>
            <dd>{money(r.monthly_fee)}</dd>
            <dt>綁約月數</dt>
            <dd>{r.contract_months}</dd>
            <dt>類型</dt>
            <dd>{r.kind_label}</dd>
            <dt>業務員佣金</dt>
            <dd>{money(r.commission)}</dd>
            {canEdit && (
              <>
                <dt>公司佣金</dt>
                <dd>{showCompanyCommission(r.company_commission)}</dd>
              </>
            )}
            <dt>備註</dt>
            <dd>{r.note || "—"}</dd>
            <dt>狀態</dt>
            <dd>{r.is_active ? "啟用" : "停用"}</dd>
          </dl>
        </div>
      ),
    },
  ];

  return (
    <div className="page">
      <Toolbar
        title="電信方案"
        actions={
          canEdit && !view && <>
            <button className="btn" onClick={() => setView({ kind: "bulk" })}>
              批次新增
            </button>
            <button className="btn" onClick={() => setView({ kind: "new" })}>
              新增方案
            </button>
          </>
        }
      />
      {canEdit && (view?.kind === "edit" || view?.kind === "new") && (
        <TelecomPlanForm
          key={view.kind === "edit" ? view.plan.id : "new"}
          initial={view.kind === "edit" ? view.plan : null}
          onClose={(saved) => {
            setView(null);
            if (saved) flashResult(saved);
          }}
        />
      )}
      {canEdit && view?.kind === "bulk" && (
        <BulkAddTelecomPlans
          onClose={() => setView(null)}
          onSuccess={(count) => {
            setView(null);
            flashResult(`成功建立 ${count} 筆方案`);
          }}
        />
      )}
      <div className="pane-list" hidden={!!view}>

      {/* 批次操作工具列(僅 上/下架);佣金已改為列表 inline 直接編輯 */}
      {canEdit && selectedIds.size > 0 && (
        <div
          style={{
            padding: "8px 16px",
            background: "var(--panel-2)",
            borderBottom: "1px solid var(--border)",
            display: "flex",
            alignItems: "center",
            gap: 12,
            flexWrap: "wrap",
          }}
        >
          <strong>已選 {selectedIds.size} 筆</strong>
          <button
            className="btn"
            type="button"
            onClick={clearSelection}
            disabled={batchPending}
          >
            清除選取
          </button>
          <span style={{ color: "var(--text-dim)" }}>|</span>
          <button
            className={`btn${arm.armed === `batch:上架:${selKey}` ? " armed" : ""}`}
            type="button"
            onClick={() => patchSelected({ is_active: true }, "上架")}
            disabled={batchPending}
          >
            {arm.armed === `batch:上架:${selKey}` ? `再按一次上架 ${selectedIds.size} 筆` : "批次上架"}
          </button>
          <button
            className={`btn${arm.armed === `batch:下架:${selKey}` ? " armed" : ""}`}
            type="button"
            onClick={() => patchSelected({ is_active: false }, "下架")}
            disabled={batchPending}
          >
            {arm.armed === `batch:下架:${selKey}` ? `再按一次下架 ${selectedIds.size} 筆` : "批次下架"}
          </button>
          {batchPending && (
            <span style={{ color: "var(--text-dim)" }}>處理中…</span>
          )}
          <span style={{ marginLeft: "auto", fontSize: 14, color: "var(--text-dim)" }}>
            佣金直接在下方列表輸入(離開欄位自動儲存)
          </span>
        </div>
      )}

      {bulkResult && (
        <div
          style={{
            padding: "6px 16px",
            background: "rgba(128,208,144,0.15)",
            color: "var(--success-text-soft)",
            fontSize: 14,
          }}
        >
          {bulkResult}
        </div>
      )}
      {isLoading && <div className="md-empty">載入中…</div>}
      {isError && <div className="md-empty">載入失敗:{errorText(error)}</div>}
      {!isLoading && !isError && (
        <MasterDetail
          rows={filtered}
          columns={columns}
          rowKey={(r) => r.id}
          tabs={tabs}
          searchPlaceholder="搜尋 專案名稱 / 電信商 / 月租 / 綁約"
          onSearch={setQuery}
          emptyText={(data ?? []).length === 0 ? "還沒有方案" : `查無符合「${query}」的方案`}
          onOpen={canEdit ? (r) => setView({ kind: "edit", plan: r }) : undefined}
        />
      )}
      </div>
    </div>
  );
}
