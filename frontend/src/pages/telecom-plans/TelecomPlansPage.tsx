import { useEffect, useMemo, useState } from "react";

import { useSaveTelecomPlan, useTelecomPlans } from "@/api/hooks";
import type { TelecomPlan } from "@/api/types";
import { Toolbar } from "@/components/Toolbar";
import {
  MasterDetail,
  MasterColumn,
  DetailTab,
} from "@/components/master-detail/MasterDetail";

import { BulkAddTelecomPlansModal } from "./BulkAddTelecomPlansModal";
import { TelecomPlanForm } from "./TelecomPlanForm";

export function TelecomPlansPage() {
  const { data, isLoading, isError, error } = useTelecomPlans({
    includeInactive: true,
  });
  const savePlan = useSaveTelecomPlan();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerInitial, setDrawerInitial] = useState<TelecomPlan | null>(null);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkResult, setBulkResult] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  // inline 佣金編輯暫存:key=plan.id, value=輸入中字串。
  // 沒鍵或鍵不存在 → 顯示原值;onBlur 比對若不同就 PATCH
  const [editCommission, setEditCommission] = useState<Record<number, string>>(
    {},
  );
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
          ? String(Math.round(Number(plan.commission)))
          : null;
        const editIntStr = String(Math.round(Number(v.trim() || 0)));
        if (plan && editIntStr === planIntStr) {
          changed = true;
        } else {
          next[id] = v;
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
    const intStr = String(Math.round(Number(v.trim() || 0)));
    const originalIntStr = String(Math.round(Number(plan.commission)));
    if (!v.trim() || intStr === originalIntStr) {
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
      await savePlan.mutateAsync({ id: plan.id, commission: intStr });
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

  async function patchSelected(patch: Partial<TelecomPlan>, label: string) {
    if (selectedIds.size === 0) return;
    if (!confirm(`對勾選的 ${selectedIds.size} 筆方案執行「${label}」?`)) return;
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
        `批次失敗:${e instanceof Error ? e.message : String(e)}`,
      );
      setTimeout(() => setBulkResult(null), 6000);
    } finally {
      setBatchPending(false);
    }
  }

  const columns: MasterColumn<TelecomPlan>[] = useMemo(
    () => [
      {
        key: "select",
        header: (
          <input
            type="checkbox"
            checked={allFilteredSelected}
            onChange={(e) => toggleAllFiltered(e.target.checked)}
            onClick={(e) => e.stopPropagation()}
            title="勾選此頁全部"
          />
        ),
        render: (r) => (
          <input
            type="checkbox"
            checked={selectedIds.has(r.id)}
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
            {Math.round(Number(r.monthly_fee)).toLocaleString()}
          </span>
        ),
      },
      {
        key: "contract_months",
        header: "綁約",
        render: (r) => <span className="num">{r.contract_months} 月</span>,
      },
      { key: "kind", header: "類型", render: (r) => r.kind_label },
      {
        key: "commission",
        header: "佣金",
        render: (r) => {
          const original = String(Math.round(Number(r.commission)));
          const editing = editCommission[r.id];
          const value = editing ?? original;
          const dirty = editing != null && editing !== original;
          return (
            <input
              type="number"
              step="1"
              min="0"
              className="num-input"
              value={value}
              onChange={(e) =>
                setEditCommission((s) => ({ ...s, [r.id]: e.target.value }))
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
        key: "is_active",
        header: "啟用",
        render: (r) => (
          <input
            type="checkbox"
            checked={r.is_active}
            onChange={(e) => commitActive(r, e.target.checked)}
            onClick={(e) => e.stopPropagation()}
            disabled={savingIds.has(r.id)}
          />
        ),
      },
    ],
    [allFilteredSelected, selectedIds, editCommission, savingIds],
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
            <dd>{Math.round(Number(r.monthly_fee)).toLocaleString()}</dd>
            <dt>綁約月數</dt>
            <dd>{r.contract_months}</dd>
            <dt>類型</dt>
            <dd>{r.kind_label}</dd>
            <dt>佣金</dt>
            <dd>{Math.round(Number(r.commission)).toLocaleString()}</dd>
            <dt>備註</dt>
            <dd>{r.note || "—"}</dd>
            <dt>狀態</dt>
            <dd>{r.is_active ? "啟用" : "停用"}</dd>
          </dl>
          <div style={{ marginTop: 12 }}>
            <button
              className="btn primary"
              onClick={() => {
                setDrawerInitial(r);
                setDrawerOpen(true);
              }}
            >
              編輯
            </button>
          </div>
        </div>
      ),
    },
  ];

  return (
    <div className="page">
      <Toolbar
        title="電信方案"
        actions={
          <>
            <button className="btn" onClick={() => setBulkOpen(true)}>
              批次新增
            </button>
            <button
              className="btn primary"
              onClick={() => {
                setDrawerInitial(null);
                setDrawerOpen(true);
              }}
            >
              + 新增方案
            </button>
          </>
        }
      />

      {/* 批次操作工具列(僅 上/下架);佣金已改為列表 inline 直接編輯 */}
      {selectedIds.size > 0 && (
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
            className="btn"
            type="button"
            onClick={() => patchSelected({ is_active: true }, "上架")}
            disabled={batchPending}
          >
            批次上架
          </button>
          <button
            className="btn"
            type="button"
            onClick={() => patchSelected({ is_active: false }, "下架")}
            disabled={batchPending}
          >
            批次下架
          </button>
          {batchPending && (
            <span style={{ color: "var(--text-dim)" }}>處理中…</span>
          )}
          <span style={{ marginLeft: "auto", fontSize: 12, color: "var(--text-dim)" }}>
            佣金請直接於下方列表佣金欄位輸入(離開欄位自動儲存)
          </span>
        </div>
      )}

      {bulkResult && (
        <div
          style={{
            padding: "6px 16px",
            background: "rgba(128,208,144,0.15)",
            color: "#80d090",
            fontSize: 13,
          }}
        >
          {bulkResult}
        </div>
      )}
      {isLoading && <div className="md-empty">載入中…</div>}
      {isError && <div className="md-empty">載入失敗:{String(error)}</div>}
      {!isLoading && !isError && (
        <MasterDetail
          rows={filtered}
          columns={columns}
          rowKey={(r) => r.id}
          tabs={tabs}
          searchPlaceholder="搜尋 專案名稱 / 電信商 / 月租 / 綁約"
          onSearch={setQuery}
          emptyDetailHint={
            (data ?? []).length === 0
              ? "尚無方案,點右上「+ 新增方案」開始建立"
              : filtered.length === 0
                ? `查無符合「${query}」的方案`
                : "從左側選擇方案檢視詳細"
          }
        />
      )}
      <TelecomPlanForm
        open={drawerOpen}
        initial={drawerInitial}
        onClose={() => setDrawerOpen(false)}
      />
      <BulkAddTelecomPlansModal
        open={bulkOpen}
        onClose={() => setBulkOpen(false)}
        onSuccess={(count) => {
          setBulkOpen(false);
          setBulkResult(`成功建立 ${count} 筆方案`);
          setTimeout(() => setBulkResult(null), 4000);
        }}
      />
    </div>
  );
}
