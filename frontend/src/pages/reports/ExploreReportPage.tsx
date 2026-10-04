import { ReactNode, useEffect, useMemo, useRef, useState } from "react";

import {
  useAnalyticsCatalog,
  useAnalyticsOptions,
  useAnalyticsQuery,
  useDeleteReport,
  useSavedReports,
  useSaveReport,
} from "@/api/hooks";
import type {
  AnalyticsCatalog,
  AnalyticsFilterShown,
  AnalyticsNumbers,
  AnalyticsOption,
  AnalyticsResult,
  AnalyticsSpec,
  AnalyticsValue,
  SavedReport,
} from "@/api/types";
import { useCurrentUser } from "@/auth/AuthContext";
import { Banner, errorMessageOf } from "@/components/Banner";
import { Toolbar } from "@/components/Toolbar";

/**
 * 報表 → 自由組合
 *
 * 不是一張寫死的報表:挑「指標 × 分組 × 條件 × 期間」送出查詢單(apps/analytics),
 * 數字怎麼算只有後端的定義一種。常用的組合可以存成「我的報表」。
 */

type Format = "money" | "int" | "pct";
type Filters = Record<string, AnalyticsOption[]>;

const CUSTOM = "custom";
const DEFAULT_MEASURES = ["net_sales", "gross_profit"];
const DEFAULT_DIMS = ["warehouse"];
const DEFAULT_PRESET = "this_month";
const COMPARES = [
  { key: "", label: "不比較" },
  { key: "previous", label: "上一期" },
  { key: "last_year", label: "去年同期" },
];
/** 比較那一欄叫什麼:畫面與匯出都要跟選的比較方式一致(選去年同期不能寫成上期)。 */
const previousLabel = (compare: string | null | undefined) =>
  compare === "last_year" ? "去年同期" : "上期";

function today(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function fmt(v: string | number | null | undefined, format: Format): string {
  if (v === null || v === undefined) return "—";
  const n = Number(v);
  if (format === "pct") return `${(n * 100).toFixed(1)}%`;
  return Math.round(n).toLocaleString();
}

/** 跟上一期比:回傳顯示文字與方向。比率類看「差幾個百分點」,其他看差額與漲跌幅。 */
function change(
  cur: string | number | null | undefined,
  prev: string | number | null | undefined,
  format: Format,
): { text: string; dir: "up" | "down" | "" } {
  if (cur === null || cur === undefined || prev === null || prev === undefined) {
    return { text: "—", dir: "" };
  }
  const diff = Number(cur) - Number(prev);
  const dir = diff > 0 ? "up" : diff < 0 ? "down" : "";
  const sign = diff > 0 ? "+" : "";
  if (format === "pct") return { text: `${sign}${(diff * 100).toFixed(1)}`, dir };
  const amount = `${sign}${Math.round(diff).toLocaleString()}`;
  if (Number(prev) === 0) return { text: amount, dir };
  const pct = Math.round((diff / Math.abs(Number(prev))) * 100);
  return { text: `${amount} (${pct > 0 ? "+" : ""}${pct}%)`, dir };
}

function csvCell(v: unknown): string {
  const s = v === null || v === undefined ? "" : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function allowedDims(catalog: AnalyticsCatalog, measures: string[]): string[] {
  const sets = measures
    .map((key) => catalog.measures.find((m) => m.key === key)?.dimensions)
    .filter((d): d is string[] => !!d);
  if (sets.length === 0) return [];
  return catalog.dimensions
    .map((d) => d.key)
    .filter((key) => sets.every((s) => s.includes(key)));
}

export function ExploreReportPage() {
  const role = useCurrentUser()?.profile?.role;
  const isAdmin = role === "tenant_admin" || role === "platform_admin";
  const { data: catalog, error: catalogError } = useAnalyticsCatalog();
  const { data: reports, error: reportsError } = useSavedReports();
  const saveReport = useSaveReport();
  const deleteReport = useDeleteReport();

  const [measures, setMeasures] = useState<string[]>(DEFAULT_MEASURES);
  const [dims, setDims] = useState<string[]>(DEFAULT_DIMS);
  const [preset, setPreset] = useState<string>(DEFAULT_PRESET);
  const [from, setFrom] = useState<string>(today);
  const [to, setTo] = useState<string>(today);
  const [grain, setGrain] = useState<string>("month");
  const [filters, setFilters] = useState<Filters>({});
  const [compare, setCompare] = useState<string>("");
  const [sort, setSort] = useState<string>("");

  const [applied, setApplied] = useState<AnalyticsSpec | null>(null);
  const [loaded, setLoaded] = useState<SavedReport | null>(null);
  const [notice, setNotice] = useState<{ kind: "error" | "info"; message: string } | null>(null);
  const [editingFilter, setEditingFilter] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const query = useAnalyticsQuery(applied);
  const result = query.data;

  const allowed = useMemo(
    () => (catalog ? allowedDims(catalog, measures) : []),
    [catalog, measures],
  );
  const dimLabel = (key: string) =>
    catalog?.dimensions.find((d) => d.key === key)?.label ?? key;
  const hasDate = dims.includes("date");

  function buildSpec(over: Partial<{ sort: string }> = {}): AnalyticsSpec {
    const out: Record<string, AnalyticsValue[]> = {};
    for (const [key, opts] of Object.entries(filters)) {
      if (opts.length) out[key] = opts.map((o) => o.value);
    }
    return {
      measures,
      dimensions: dims,
      period: preset === CUSTOM ? { from, to, grain } : { preset, grain },
      filters: out,
      compare: compare && !hasDate ? (compare as "previous" | "last_year") : null,
      sort: over.sort ?? sort,
    };
  }

  function run(spec: AnalyticsSpec = buildSpec()) {
    setNotice(null);
    if (JSON.stringify(spec) === JSON.stringify(applied)) query.refetch();
    else setApplied(spec);
  }

  // 第一次進來先跑預設的(本月各門市的淨銷售額與毛利)
  const started = useRef(false);
  useEffect(() => {
    if (catalog && !started.current) {
      started.current = true;
      run();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalog]);

  /** 指標換了之後,不再適用的分組與條件要拿掉(後端也會擋,這裡先讓畫面一致)。 */
  function changeMeasures(next: string[]) {
    setMeasures(next);
    if (!catalog) return;
    const ok = allowedDims(catalog, next);
    const nextDims = dims.filter((d) => ok.includes(d));
    setDims(nextDims);
    setFilters((prev) =>
      Object.fromEntries(Object.entries(prev).filter(([key]) => ok.includes(key))),
    );
    const sorted = sort.replace(/^-/, "");
    if (sort && !next.includes(sorted) && !nextDims.includes(sorted)) setSort("");
  }

  function changeDim(index: number, key: string) {
    const next = [...dims];
    if (key) next[index] = key;
    else next.splice(index, 1);
    setDims(next);
    if (sort && !measures.includes(sort.replace(/^-/, "")) && !next.includes(sort.replace(/^-/, ""))) {
      setSort("");
    }
  }

  function reset() {
    setMeasures(DEFAULT_MEASURES);
    setDims(DEFAULT_DIMS);
    setPreset(DEFAULT_PRESET);
    setGrain("month");
    setFilters({});
    setCompare("");
    setSort("");
    setLoaded(null);
    setNotice(null);
  }

  function sortBy(key: string, isMeasure: boolean) {
    // 指標先由大到小,分組先由小到大;再點一次反過來
    const first = isMeasure ? `-${key}` : key;
    const second = isMeasure ? key : `-${key}`;
    const next = sort === first ? second : first;
    setSort(next);
    run(buildSpec({ sort: next }));
  }

  function openReport(report: SavedReport) {
    if (report.error) {
      setLoaded(null);
      setNotice({ kind: "error", message: `「${report.name}」不能用:${report.error}` });
      return;
    }
    const s = report.spec;
    const shown: Filters = {};
    for (const f of report.filters as AnalyticsFilterShown[]) shown[f.dimension] = f.values;
    setMeasures(s.measures);
    setDims(s.dimensions);
    setPreset(s.period.preset ?? CUSTOM);
    if (s.period.from) setFrom(s.period.from);
    if (s.period.to) setTo(s.period.to);
    setGrain(s.period.grain ?? "month");
    setFilters(shown);
    setCompare(s.compare ?? "");
    setSort(s.sort ?? "");
    setLoaded(report);
    setApplied({ ...s });
    setNotice(
      report.missing.length
        ? { kind: "info", message: `條件裡已不存在的資料:${report.missing.join("、")}` }
        : null,
    );
  }

  async function removeLoaded() {
    if (!loaded || !confirm(`確定刪除「${loaded.name}」?`)) return;
    try {
      await deleteReport.mutateAsync(loaded.id);
      setLoaded(null);
    } catch (e) {
      setNotice({ kind: "error", message: errorMessageOf(e) });
    }
  }

  function exportCsv() {
    if (!result) return;
    const head = [
      ...result.columns.dimensions.map((d) => d.label),
      ...result.columns.measures.flatMap((m) =>
        result.applied.compare
          ? [m.label, `${m.label}(${previousLabel(result.applied.compare)})`]
          : [m.label],
      ),
    ];
    // 比率在畫面上是百分比,匯出也給百分比(不然 0.2238 貼進試算表會被看成 0.22%)
    const cell = (v: string | number | null | undefined, format: Format) =>
      format === "pct" && v !== null && v !== undefined ? fmt(v, format) : v;
    const line = (labels: string[], cur: AnalyticsNumbers, prev?: AnalyticsNumbers) => [
      ...labels,
      ...result.columns.measures.flatMap((m) =>
        result.applied.compare
          ? [cell(cur[m.key], m.format), cell(prev?.[m.key], m.format)]
          : [cell(cur[m.key], m.format)],
      ),
    ];
    const rows = result.rows.map((r) => line(r.dims.map((d) => d.label), r.values, r.previous));
    if (result.columns.dimensions.length) {
      rows.push(
        line(
          result.columns.dimensions.map((_, i) => (i === 0 ? "合計" : "")),
          result.totals,
          result.totals_previous,
        ),
      );
    }
    const csv = [head, ...rows].map((r) => r.map(csvCell).join(",")).join("\n");
    const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${loaded?.name ?? "自由組合"}_${result.applied.period.from}_${result.applied.period.to}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  if (catalogError) {
    return (
      <div className="page">
        <Toolbar title="自由組合" />
        <div className="entry-body">
          <Banner kind="error" message={`讀取失敗:${errorMessageOf(catalogError)}`} />
        </div>
      </div>
    );
  }
  if (!catalog) {
    return (
      <div className="page">
        <Toolbar title="自由組合" />
      </div>
    );
  }

  const unpicked = catalog.measures.filter((m) => !measures.includes(m.key));
  const filterable = allowed.filter((key) => key !== "date" && !(key in filters));

  return (
    <div className="page">
      <Toolbar
        title="自由組合"
        actions={
          <select
            className="ex-select"
            value={loaded?.id ?? ""}
            onChange={(e) => {
              const picked = reports?.find((r) => r.id === Number(e.target.value));
              if (picked) openReport(picked);
              else setLoaded(null);
            }}
          >
            <option value="">我的報表</option>
            {reports?.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
                {r.shared ? "(共用)" : ""}
              </option>
            ))}
          </select>
        }
      />

      <div className="ex-builder">
        <div className="ex-line">
          <span className="ex-line-label">期間</span>
          <select className="ex-select" value={preset} onChange={(e) => setPreset(e.target.value)}>
            {catalog.presets.map((p) => (
              <option key={p.key} value={p.key}>
                {p.label}
              </option>
            ))}
            <option value={CUSTOM}>自訂</option>
          </select>
          {preset === CUSTOM && (
            <>
              <input
                type="date"
                className="ex-date"
                aria-label="起日"
                value={from}
                onChange={(e) => setFrom(e.target.value)}
              />
              <input
                type="date"
                className="ex-date"
                aria-label="迄日"
                value={to}
                onChange={(e) => setTo(e.target.value)}
              />
            </>
          )}
          <select
            className="ex-select"
            aria-label="比較"
            value={hasDate ? "" : compare}
            disabled={hasDate}
            onChange={(e) => setCompare(e.target.value)}
          >
            {COMPARES.map((c) => (
              <option key={c.key} value={c.key}>
                {c.label}
              </option>
            ))}
          </select>
        </div>

        <div className="ex-line">
          <span className="ex-line-label">指標</span>
          {measures.map((key) => (
            <span key={key} className="ex-chip">
              {catalog.measures.find((m) => m.key === key)?.label ?? key}
              <button
                type="button"
                aria-label="移除"
                onClick={() => changeMeasures(measures.filter((m) => m !== key))}
              >
                ×
              </button>
            </span>
          ))}
          {measures.length < catalog.limits.measures && (
            <select
              className="ex-select ex-add"
              value=""
              onChange={(e) => e.target.value && changeMeasures([...measures, e.target.value])}
            >
              <option value="">加指標</option>
              {catalog.groups.map((group) => {
                const items = unpicked.filter((m) => m.group === group);
                if (items.length === 0) return null;
                return (
                  <optgroup key={group} label={group}>
                    {items.map((m) => (
                      <option key={m.key} value={m.key}>
                        {m.label}
                      </option>
                    ))}
                  </optgroup>
                );
              })}
            </select>
          )}
        </div>

        <div className="ex-line">
          <span className="ex-line-label">分組</span>
          {[...dims, ""].slice(0, catalog.limits.dimensions).map((current, index) => (
            <select
              key={index}
              className="ex-select"
              value={current}
              onChange={(e) => changeDim(index, e.target.value)}
            >
              <option value="">{current ? "不分" : "加分組"}</option>
              {allowed
                .filter((key) => key === current || !dims.includes(key))
                .map((key) => (
                  <option key={key} value={key}>
                    {dimLabel(key)}
                  </option>
                ))}
            </select>
          ))}
          {hasDate && (
            <select
              className="ex-select"
              aria-label="日期單位"
              value={grain}
              onChange={(e) => setGrain(e.target.value)}
            >
              {catalog.grains.map((g) => (
                <option key={g.key} value={g.key}>
                  按{g.label}
                </option>
              ))}
            </select>
          )}
        </div>

        <div className="ex-line">
          <span className="ex-line-label">條件</span>
          {Object.entries(filters).map(([key, opts]) => (
            <span key={key} className="ex-chip">
              <button type="button" className="ex-chip-text" onClick={() => setEditingFilter(key)}>
                {dimLabel(key)}:{opts.map((o) => o.label).join("、")}
              </button>
              <button
                type="button"
                aria-label="移除"
                onClick={() =>
                  setFilters((prev) =>
                    Object.fromEntries(Object.entries(prev).filter(([k]) => k !== key)),
                  )
                }
              >
                ×
              </button>
            </span>
          ))}
          {filterable.length > 0 && (
            <select
              className="ex-select ex-add"
              value=""
              onChange={(e) => e.target.value && setEditingFilter(e.target.value)}
            >
              <option value="">加條件</option>
              {filterable.map((key) => (
                <option key={key} value={key}>
                  {dimLabel(key)}
                </option>
              ))}
            </select>
          )}
        </div>

        <div className="ex-line ex-actions">
          <button
            type="button"
            className="btn primary"
            onClick={() => run()}
            disabled={measures.length === 0}
          >
            查詢
          </button>
          <button type="button" className="btn" onClick={reset}>
            清除
          </button>
          <button type="button" className="btn" onClick={exportCsv} disabled={!result}>
            匯出
          </button>
          <button
            type="button"
            className="btn"
            onClick={() => setSaving(true)}
            disabled={measures.length === 0}
          >
            存檔
          </button>
          {loaded?.editable && (
            <button type="button" className="btn danger" onClick={removeLoaded}>
              刪除
            </button>
          )}
        </div>
      </div>

      <div className="ex-result">
        {reportsError && (
          <Banner kind="error" message={`我的報表讀取失敗:${errorMessageOf(reportsError)}`} />
        )}
        {notice && <Banner kind={notice.kind} message={notice.message} />}
        {query.error && <Banner kind="error" message={errorMessageOf(query.error)} />}
        {result && !query.error && <ResultView result={result} sort={sort} onSort={sortBy} />}
      </div>

      {editingFilter && (
        <FilterModal
          dimension={editingFilter}
          label={dimLabel(editingFilter)}
          withBlank={catalog.dimensions.find((d) => d.key === editingFilter)?.kind === "ref"}
          searchable={catalog.dimensions.find((d) => d.key === editingFilter)?.kind === "ref"}
          selected={filters[editingFilter] ?? []}
          onClose={() => setEditingFilter(null)}
          onApply={(opts) => {
            setFilters((prev) => {
              const next = { ...prev };
              if (opts.length) next[editingFilter] = opts;
              else delete next[editingFilter];
              return next;
            });
            setEditingFilter(null);
          }}
        />
      )}

      {saving && (
        <SaveModal
          loaded={loaded}
          isAdmin={isAdmin}
          busy={saveReport.isPending}
          onClose={() => setSaving(false)}
          onSave={async (name, shared, asNew) => {
            // 開著自己能改的報表時,存檔就是改那一份(改名也是);要另外多一份才勾「另存一份」
            const update = !!loaded?.editable && !asNew;
            const saved = await saveReport.mutateAsync({
              id: update ? loaded.id : undefined,
              name,
              spec: buildSpec(),
              shared,
            });
            setLoaded(saved);
            setSaving(false);
          }}
        />
      )}
    </div>
  );
}

function ResultView({
  result,
  sort,
  onSort,
}: {
  result: AnalyticsResult;
  sort: string;
  onSort: (key: string, isMeasure: boolean) => void;
}) {
  const { columns, applied } = result;
  const comparing = !!applied.compare;
  const mark = (key: string) => (sort === key ? " ▲" : sort === `-${key}` ? " ▼" : "");

  return (
    <>
      <div className="ex-period">
        {applied.period.from} ~ {applied.period.to}
        {applied.compare_period &&
          `　對比 ${applied.compare_period.from} ~ ${applied.compare_period.to}`}
      </div>

      <div className="sd-summary ex-summary">
        {columns.measures.map((m) => {
          const delta = comparing
            ? change(result.totals[m.key], result.totals_previous?.[m.key], m.format)
            : null;
          return (
            <div key={m.key} className="sd-summary-card">
              <div className="sd-summary-card-label">{m.label}</div>
              <div className="sd-summary-card-value">{fmt(result.totals[m.key], m.format)}</div>
              {delta && <div className={`ex-delta ex-${delta.dir}`}>{delta.text}</div>}
            </div>
          );
        })}
      </div>

      {columns.dimensions.length > 0 && (
        <div className="ex-table-wrap">
          <table className="report-grid ex-grid">
            <thead>
              <tr>
                {columns.dimensions.map((d) => (
                  <th key={d.key}>
                    <button type="button" className="ex-sort" onClick={() => onSort(d.key, false)}>
                      {d.label}
                      {mark(d.key)}
                    </button>
                  </th>
                ))}
                {columns.measures.map((m) => (
                  <MeasureHead
                    key={m.key}
                    comparing={comparing}
                    previous={previousLabel(applied.compare)}
                  >
                    <button type="button" className="ex-sort" onClick={() => onSort(m.key, true)}>
                      {m.label}
                      {mark(m.key)}
                    </button>
                  </MeasureHead>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.rows.map((row, i) => (
                <tr key={i}>
                  {row.dims.map((d, j) => (
                    <td key={j} className={d.value === null ? "dim" : undefined}>
                      {d.label}
                    </td>
                  ))}
                  {columns.measures.map((m) => (
                    <MeasureCells
                      key={m.key}
                      format={m.format}
                      cur={row.values[m.key]}
                      prev={row.previous?.[m.key]}
                      comparing={comparing}
                    />
                  ))}
                </tr>
              ))}
              {result.rows.length === 0 && (
                <tr>
                  <td
                    className="dim"
                    colSpan={
                      columns.dimensions.length + columns.measures.length * (comparing ? 3 : 1)
                    }
                  >
                    沒有資料
                  </td>
                </tr>
              )}
            </tbody>
            {result.rows.length > 0 && (
              <tfoot>
                <tr>
                  <td colSpan={columns.dimensions.length}>合計</td>
                  {columns.measures.map((m) => (
                    <MeasureCells
                      key={m.key}
                      format={m.format}
                      cur={result.totals[m.key]}
                      prev={result.totals_previous?.[m.key]}
                      comparing={comparing}
                    />
                  ))}
                </tr>
              </tfoot>
            )}
          </table>
          {result.truncated && (
            <div className="ex-note">
              只列前 {result.rows.length.toLocaleString()} 筆(共{" "}
              {result.row_count.toLocaleString()} 筆),合計是全部
            </div>
          )}
        </div>
      )}
    </>
  );
}

function MeasureHead({
  comparing,
  previous,
  children,
}: {
  comparing: boolean;
  previous: string;
  children: ReactNode;
}) {
  return (
    <>
      <th className="num">{children}</th>
      {comparing && <th className="num">{previous}</th>}
      {comparing && <th className="num">增減</th>}
    </>
  );
}

function MeasureCells({
  format,
  cur,
  prev,
  comparing,
}: {
  format: Format;
  cur: string | number | null | undefined;
  prev: string | number | null | undefined;
  comparing: boolean;
}) {
  const delta = comparing ? change(cur, prev, format) : null;
  return (
    <>
      <td className="num">{fmt(cur, format)}</td>
      {comparing && <td className="num dim">{fmt(prev, format)}</td>}
      {delta && <td className={`num ex-${delta.dir}`}>{delta.text}</td>}
    </>
  );
}

function FilterModal({
  dimension,
  label,
  withBlank,
  searchable,
  selected,
  onApply,
  onClose,
}: {
  dimension: string;
  label: string;
  withBlank: boolean;
  searchable: boolean;
  selected: AnalyticsOption[];
  onApply: (opts: AnalyticsOption[]) => void;
  onClose: () => void;
}) {
  const [typed, setTyped] = useState("");
  const [q, setQ] = useState("");
  const [picked, setPicked] = useState<AnalyticsOption[]>(selected);
  const { data: options, error } = useAnalyticsOptions(dimension, q);

  useEffect(() => {
    const t = setTimeout(() => setQ(typed.trim()), 250);
    return () => clearTimeout(t);
  }, [typed]);

  const isPicked = (o: AnalyticsOption) => picked.some((p) => p.value === o.value);
  const toggle = (o: AnalyticsOption) =>
    setPicked((prev) =>
      isPicked(o) ? prev.filter((p) => p.value !== o.value) : [...prev, o],
    );

  // 已經選的排最前面(換了搜尋字也看得到、取消得掉)
  const blank: AnalyticsOption = { value: null, label: "未指定 / 未對照" };
  const listed = [
    ...picked,
    ...(withBlank && !isPicked(blank) && !q ? [blank] : []),
    ...(options ?? []).filter((o) => !isPicked(o)),
  ];

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-card ex-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="modal-title">{label}</div>
        {error && <Banner kind="error" message={errorMessageOf(error)} />}
        <div className="modal-body">
          {searchable && (
            <input
              autoFocus
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              placeholder="搜尋"
            />
          )}
          <div className="ex-options">
            {listed.map((o) => (
              <label key={String(o.value)} className="ex-option">
                <input type="checkbox" checked={isPicked(o)} onChange={() => toggle(o)} />
                {o.label}
              </label>
            ))}
            {options && listed.length === 0 && <div className="dim">沒有符合的</div>}
          </div>
        </div>
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>
            取消
          </button>
          <button type="button" className="btn primary" onClick={() => onApply(picked)}>
            套用
          </button>
        </div>
      </div>
    </div>
  );
}

function SaveModal({
  loaded,
  isAdmin,
  busy,
  onSave,
  onClose,
}: {
  loaded: SavedReport | null;
  isAdmin: boolean;
  busy: boolean;
  onSave: (name: string, shared: boolean, asNew: boolean) => Promise<void>;
  onClose: () => void;
}) {
  const editing = !!loaded?.editable;
  const [name, setName] = useState(editing ? loaded.name : "");
  const [shared, setShared] = useState(editing ? loaded.shared : false);
  const [asNew, setAsNew] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    setError("");
    try {
      await onSave(name.trim(), shared, asNew);
    } catch (e) {
      setError(errorMessageOf(e));
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-card ex-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="modal-title">{editing && !asNew ? "更新我的報表" : "存成我的報表"}</div>
        {error && <Banner kind="error" message={error} />}
        <div className="modal-body">
          <input
            autoFocus
            value={name}
            maxLength={60}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.nativeEvent.isComposing && name.trim()) submit();
            }}
            placeholder="名稱"
          />
          {isAdmin && (
            <label className="ex-option">
              <input
                type="checkbox"
                checked={shared}
                onChange={(e) => setShared(e.target.checked)}
              />
              全公司共用
            </label>
          )}
          {editing && (
            <label className="ex-option">
              <input
                type="checkbox"
                checked={asNew}
                onChange={(e) => setAsNew(e.target.checked)}
              />
              另存一份
            </label>
          )}
        </div>
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>
            取消
          </button>
          <button
            type="button"
            className="btn primary"
            onClick={submit}
            disabled={busy || !name.trim()}
          >
            儲存
          </button>
        </div>
      </div>
    </div>
  );
}
