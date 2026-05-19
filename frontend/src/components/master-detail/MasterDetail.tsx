import { ReactNode, useState } from "react";

export interface MasterColumn<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
}

export interface DetailTab<T> {
  key: string;
  label: string;
  render: (row: T) => ReactNode;
}

export interface DetailAction {
  key: string;
  label: string;
  primary?: boolean;
  onClick: () => void;
}

interface MasterDetailProps<T> {
  rows: T[];
  columns: MasterColumn<T>[];
  rowKey: (row: T) => string | number;
  tabs: DetailTab<T>[];
  actions?: (row: T) => DetailAction[];
  searchPlaceholder?: string;
  onSearch?: (query: string) => void;
  emptyDetailHint?: string;
}

export function MasterDetail<T>({
  rows,
  columns,
  rowKey,
  tabs,
  actions,
  searchPlaceholder = "搜尋…",
  onSearch,
  emptyDetailHint = "從左側選擇一列以檢視詳細資料",
}: MasterDetailProps<T>) {
  const [selectedKey, setSelectedKey] = useState<string | number | null>(null);
  const [activeTab, setActiveTab] = useState<string>(tabs[0]?.key ?? "");

  const selectedRow = rows.find((r) => rowKey(r) === selectedKey) ?? null;
  const currentActions = selectedRow && actions ? actions(selectedRow) : [];
  const currentTab = tabs.find((t) => t.key === activeTab) ?? tabs[0];

  return (
    <div className="md-layout">
      <section className="md-master">
        <div className="md-master-toolbar">
          <input
            type="search"
            placeholder={searchPlaceholder}
            onChange={(e) => onSearch?.(e.target.value)}
          />
        </div>
        <div className="md-table">
          <table>
            <thead>
              <tr>
                {columns.map((c) => (
                  <th key={c.key}>{c.header}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const k = rowKey(row);
                return (
                  <tr
                    key={k}
                    className={k === selectedKey ? "selected" : undefined}
                    onClick={() => setSelectedKey(k)}
                  >
                    {columns.map((c) => (
                      <td key={c.key}>{c.render(row)}</td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
      <section className="md-detail">
        <div className="md-detail-tabs">
          {tabs.map((t) => (
            <button
              key={t.key}
              className={t.key === currentTab?.key ? "active" : undefined}
              onClick={() => setActiveTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="md-detail-body">
          {selectedRow && currentTab ? (
            currentTab.render(selectedRow)
          ) : (
            <div className="md-empty">{emptyDetailHint}</div>
          )}
        </div>
        <div className="md-detail-footer">
          {currentActions.map((a) => (
            <button key={a.key} className={a.primary ? "primary" : undefined} onClick={a.onClick}>
              {a.label}
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
