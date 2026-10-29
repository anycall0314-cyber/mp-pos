import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { useRepairOrders, useSaveRepairOrder, useVoidRepairOrder } from "@/api/hooks";
import { useCan, useSeesActualCost } from "@/auth/AuthContext";
import { ArmButton } from "@/components/workbench/ArmButton";
import { toast } from "@/components/workbench/toast";
import { errorText } from "@/lib/errorText";
import { AppliedFilters } from "@/components/AppliedFilters";
import { MoneyInput } from "@/components/MoneyInput";
import { apiErrorText } from "@/components/workbench/errors";
import { Toolbar } from "@/components/Toolbar";
import { ControlBar, SegmentedControl, ToolbarField } from "@/components/ui";
import { useStoreParam } from "@/hooks/useStoreParam";
import { appliedList, cond } from "@/lib/appliedFilters";
import { localDay } from "@/lib/fixedReports";
import { type InlinePhase, needsSave, phaseText, takeServerValue } from "@/lib/inlineSave";
import { intStr, money } from "@/lib/money";

/** 維修方式:三個、名稱短、互斥 → 單選列(docs/ui-controls.md §1);值跟伺服器的 mode 參數一樣("" = 全部) */
const MODE_OPTIONS: { value: "" | "in_house" | "external"; label: string }[] = [
  { value: "", label: "全部" },
  { value: "in_house", label: "自修" },
  { value: "external", label: "委外" },
];

const STATUS_OPTIONS = [
  // 預設只看還沒完成的(全站檢視 E4:以前連完成的都列,取機時要在一長串裡找)
  { v: "open", label: "未完成" },
  { v: "", label: "全部" },
  { v: "pending", label: "待評估" },
  { v: "quoting", label: "報價中" },
  { v: "in_repair", label: "維修中" },
  { v: "sent_external", label: "已送外廠" },
  { v: "ready_pickup", label: "待取件" },
  { v: "completed", label: "完成" },
];

/**
 * 清單上直接改的數字格(UI 改善計劃 UI-13;規則在 lib/inlineSave.ts):離開格子或按 Enter 就存,
 * 旁邊寫「存檔中 / 已存 / 沒存成」;沒存成時打的字留著、寫原因、可以重試;Esc 放棄改回原本的。
 */
function InlineMoneyCell({
  initial,
  disabled,
  onSave,
  title,
}: {
  initial: string;
  disabled?: boolean;
  onSave: (v: string) => Promise<void>;
  title?: string;
}) {
  const server = intStr(initial);
  const [val, setVal] = useState(server);
  const [phase, setPhase] = useState<InlinePhase>("idle");
  const [error, setError] = useState("");
  // 打的字也記在 ref:按 Esc 改回原本的之後馬上離開格子,存檔要看到改回來的那一個(state 還沒更新)
  const valRef = useRef(server);
  // 人有沒有打字(只是點進去不算):沒打字就不送,格子跟著伺服器現在的值
  const dirty = useRef(false);
  const busy = useRef(false);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (takeServerValue(phase, dirty.current)) {
      setVal(server);
      valRef.current = server;
    }
    // 只在伺服器的值換了的時候看
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [server]);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  function show(v: string) {
    setVal(v);
    valRef.current = v;
  }
  function edit(v: string) {
    show(v);
    dirty.current = true;
  }

  async function flush() {
    if (busy.current) return;
    const next = intStr(valRef.current);
    if (!needsSave(next, server, dirty.current)) {
      dirty.current = false;
      show(server);
      setPhase("idle");
      setError("");
      return;
    }
    busy.current = true;
    setPhase("saving");
    setError("");
    try {
      await onSave(next);
      dirty.current = false;
      setPhase("saved");
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setPhase((p) => (p === "saved" ? "idle" : p)), 2000);
    } catch (e) {
      setPhase("failed");
      setError(apiErrorText(e));
    } finally {
      busy.current = false;
    }
  }

  return (
    <span className="rp-inline">
      <MoneyInput
        min={0}
        value={val}
        disabled={disabled || phase === "saving"}
        onChange={edit}
        onBlur={() => void flush()}
        onKeyDown={(e) => {
          if (e.key === "Enter") (e.target as HTMLInputElement).blur();
          if (e.key === "Escape") {
            dirty.current = false;
            show(server);
            setPhase("idle");
            setError("");
            (e.target as HTMLInputElement).blur();
          }
        }}
        title={title}
        aria-invalid={phase === "failed" || undefined}
        className={`rp-inline-money ${phase}`}
      />
      {phase !== "idle" && (
        <span className={`rp-inline-state ${phase}`} role="status">
          {phaseText(phase)}
          {phase === "failed" && (
            <button type="button" className="rp-inline-retry" onClick={() => void flush()}>
              重試
            </button>
          )}
        </span>
      )}
      {phase === "failed" && error && <span className="rp-inline-err">{error}</span>}
    </span>
  );
}

const NUMBER_FMT = (v: string | number) =>
  money(v);

export function RepairsPage() {
  // 不是管理員:伺服器給的毛利是照零件的業務員成本算的(owner 2026-10-28)
  const actual = useSeesActualCost();
  // 今日總覽點過來帶的條件:?status=ready_pickup(待取件)、?overdue=1(預計完修日過了還沒完成)、
  // ?overdue=external(委外超過預計取回日還沒取回;跟首頁「委外單逾期」同一條)
  const [params] = useSearchParams();
  const [status, setStatus] = useState(() => {
    const v = params.get("status");
    return v !== null && STATUS_OPTIONS.some((o) => o.v === v) ? v : "open";
  });
  // 搜尋:單號、會員電話 / 姓名、機身序號;按 Enter 才查
  const [searchDraft, setSearchDraft] = useState("");
  const [search, setSearch] = useState("");
  const canVoid = useCan("void_others");
  const voidRepair = useVoidRepairOrder();
  const [mode, setMode] = useState<"" | "in_house" | "external">("");
  const [returnVisitOnly, setReturnVisitOnly] = useState(false);
  const [overdue, setOverdue] = useState<"" | "1" | "external">(() => {
    const v = params.get("overdue");
    return v === "1" || v === "external" ? v : "";
  });
  // 首頁選了門市帶過來(?warehouse=):只看那一家(全站檢視 R06)
  const store = useStoreParam();
  const { data, isLoading, isError, error } = useRepairOrders({
    open: status === "open",
    status: status === "open" ? "" : status,
    mode,
    search,
    warehouse: store.id,
  });
  const all = data ?? [];
  const today = localDay();
  const late = (r: (typeof all)[number]) =>
    overdue === "external"
      ? r.mode === "external" && r.status === "sent_external" && !!r.external_expected_pickup && r.external_expected_pickup < today
      : !!r.expected_complete_date && r.expected_complete_date < today && r.status !== "completed";
  const rows = all.filter(
    (r) =>
      (!returnVisitOnly || r.is_return_visit) &&
      // 挑了狀態 / 逾期時作廢的不算(跟今日總覽的件數一樣)
      ((status === "" && !overdue) || !r.is_void) &&
      (!overdue || late(r)),
  );
  const returnVisitCount = all.filter((r) => r.is_return_visit).length;
  const save = useSaveRepairOrder();

  async function patchField(id: number, body: Record<string, string>) {
    await save.mutateAsync({ id, ...body });
  }

  return (
    <div className="page">
      <Toolbar
        title="維修單"
        actions={
          // 進入建單是一般動作,不是這一頁的主要動作(淡色複查:鮮藍實心太搶)
          <Link to="/repairs/new" className="btn">
            建立維修單
          </Link>
        }
      />
      {/* 篩選列(全站控制項 B1):欄名 + 控制項;維修方式三個用單選列,返修 / 逾期可以同時勾。搜尋按 Enter 才查、其他即時套用(照舊) */}
      <ControlBar className="list-filterbar" label="維修單篩選">
        <ToolbarField label="搜尋">
          <input
            type="text"
            value={searchDraft}
            placeholder="單號 / 電話 / 姓名 / 序號"
            onChange={(e) => setSearchDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.nativeEvent.isComposing) {
                setSearch(searchDraft.trim());
                e.currentTarget.select();
              }
            }}
          />
        </ToolbarField>
        <ToolbarField label="狀態">
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            {STATUS_OPTIONS.map((o) => (
              <option key={o.v} value={o.v}>
                {o.label}
              </option>
            ))}
          </select>
        </ToolbarField>
        <SegmentedControl
          label="維修方式"
          value={mode}
          onChange={setMode}
          options={MODE_OPTIONS}
        />
        <label className="ui-tf">
          <input type="checkbox" checked={returnVisitOnly} onChange={(e) => setReturnVisitOnly(e.target.checked)} />
          <span>只看返修</span>
        </label>
        <label className="ui-tf">
          <input type="checkbox" checked={!!overdue} onChange={(e) => setOverdue(e.target.checked ? "1" : "")} />
          <span>只看逾期</span>
        </label>
        <span className="list-filterbar-count">
          {rows.length} 筆
          {returnVisitCount > 0 && !returnVisitOnly && (
            <span style={{ marginLeft: 8, color: "var(--text-dim)" }}>
              (含返修 {returnVisitCount} 筆)
            </span>
          )}
        </span>
      </ControlBar>

      <AppliedFilters
        items={appliedList([
          status !== "open" && cond("狀態", STATUS_OPTIONS.find((o) => o.v === status)?.label),
          cond("搜尋", search),
          cond("方式", mode && (mode === "external" ? "委外" : "自修")),
          returnVisitOnly && cond("只看", "返修"),
          !!overdue && cond("只看", overdue === "external" ? "委外逾期" : "逾期"),
          cond("門市", store.name),
        ])}
        onClear={() => {
          store.clear();
          setStatus("open");
          setSearch("");
          setSearchDraft("");
          setMode("");
          setReturnVisitOnly(false);
          setOverdue("");
        }}
      />
      <div className="md-table" style={{ height: "calc(100% - 100px)" }}>
        {isLoading && <div className="md-empty">載入中…</div>}
        {isError && <div className="md-empty">沒有讀到:{errorText(error)}</div>}
        {!isLoading && !isError && rows.length === 0 && (
          <div className="md-empty">{status || mode || returnVisitOnly || overdue || search ? "沒有符合的維修單" : "還沒有維修單"}</div>
        )}
        {rows.length > 0 && (
          <table className="md-table-inner">
            <thead>
              <tr>
                {/* 13 欄 → 10 欄(全站檢視 E11):方式、機型、預計完修放在同一格的第二行 */}
                <th>單號</th>
                <th>狀態</th>
                <th>會員 / 機型</th>
                <th>收件 / 預計完修</th>
                <th>門市</th>
                <th className="num" title="委外:預估費用">
                  預估
                </th>
                <th className="num" title="委外:實際費用 / 自修:工資">
                  費用
                </th>
                <th className="num">實付</th>
                <th className="num" title="自修:實付 − 零件成本 / 委外:實付 − 委外費用">
                  {actual ? "毛利" : "業務員毛利"}
                </th>
                {canVoid && <th aria-label="作廢" />}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                // 毛利用伺服器算好的(維修毛利只有一份算法:工資不扣、自修扣零件成本)
                const margin = Number(r.margin || 0);
                const locked = r.is_void || r.status === "completed";
                // 自家庫存送去整理的單:不收錢、沒有毛利(花的錢加進那一台的成本),工資不算
                const stock = !!r.stock_serial_detail;
                const dash = <span style={{ color: "var(--text-dim)" }}>—</span>;
                return (
                  <tr key={r.id}>
                    <td>
                      <Link
                        to={`/repairs/${r.id}`}
                        className="stock-link-name id-code"
                      >
                        {r.no}
                      </Link>
                      {r.is_return_visit && (
                        <span
                          className="rh-badge"
                          style={{
                            marginLeft: 6,
                            background:
                              r.warranty_info?.status === "within"
                                ? "rgba(74,222,128,0.15)"
                                : "rgba(251,146,60,0.15)",
                            color:
                              r.warranty_info?.status === "within"
                                ? "var(--success-text)"
                                : "var(--warn-text-orange)",
                          }}
                        >
                          返修
                        </span>
                      )}
                      <div className="rp-sub">{r.mode_label}</div>
                    </td>
                    <td>{r.status_label}</td>
                    <td>
                      <div>{stock ? "自家庫存" : r.customer_name}</div>
                      <div className="rp-sub">{r.host_model_name}</div>
                    </td>
                    <td>
                      <div>{r.received_date}</div>
                      <div className="rp-sub">{r.expected_complete_date ?? "—"}</div>
                    </td>
                    <td>{r.warehouse_name || r.warehouse_code}</td>
                    <td className="num">
                      {r.mode === "external" ? (
                        <InlineMoneyCell
                          initial={r.external_quote_estimated}
                          disabled={locked}
                          title="委外預估費用"
                          onSave={(v) =>
                            patchField(r.id, {
                              external_quote_estimated: v,
                            })
                          }
                        />
                      ) : (
                        <span style={{ color: "var(--text-dim)" }}>—</span>
                      )}
                    </td>
                    <td className="num">
                      {r.mode === "external" ? (
                        <InlineMoneyCell
                          initial={r.external_quote_actual}
                          disabled={locked}
                          title="委外實際費用"
                          onSave={(v) =>
                            patchField(r.id, {
                              external_quote_actual: v,
                            })
                          }
                        />
                      ) : stock ? (
                        dash
                      ) : (
                        <InlineMoneyCell
                          initial={r.labor_fee}
                          disabled={locked}
                          title="自修工資(零件成本由領用清單彙總,需點進單號編輯)"
                          onSave={(v) =>
                            patchField(r.id, { labor_fee: v })
                          }
                        />
                      )}
                    </td>
                    <td className="num">
                      {stock ? (
                        dash
                      ) : (
                        <InlineMoneyCell
                          initial={r.customer_paid_amount}
                          disabled={locked}
                          title="實付金額"
                          onSave={(v) =>
                            patchField(r.id, { customer_paid_amount: v })
                          }
                        />
                      )}
                    </td>
                    <td
                      className="num"
                      style={{
                        color:
                          stock
                            ? "var(--text-dim)"
                            : margin < 0
                            ? "var(--danger-text)"
                            : margin > 0
                              ? "var(--success-text)"
                              : "var(--text-dim)",
                        fontWeight: 600,
                      }}
                    >
                      {stock ? "—" : `$${NUMBER_FMT(margin)}`}
                    </td>
                    {canVoid && (
                      <td>
                        {/* 開錯的單作廢(按兩下;已完成的要先在單裡重開,伺服器也擋) */}
                        {!r.is_void && r.status !== "completed" && (
                          <ArmButton
                            key={r.id}
                            label="作廢"
                            className="btn ui-btn-text danger"
                            onConfirm={() =>
                              voidRepair
                                .mutateAsync(r.id)
                                .then(() => toast(`${r.no} 已作廢`, "ok"))
                                .catch((e) => toast(`作廢失敗:${errorText(e)}`, "err"))
                            }
                          />
                        )}
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
