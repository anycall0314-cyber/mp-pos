import { ReactNode, useEffect, useRef, useState } from "react";

import { stepKey } from "@/lib/keyboardBind";

export interface MasterColumn<T> {
  key: string;
  header: ReactNode;
  render: (row: T) => ReactNode;
  /**
   * 右邊打開一筆的時候收起來(那些欄位右邊的明細看得到)。全站檢視 E11:打開一筆後清單變窄,
   * 9~12 欄要往右捲才看得到狀態、金額;沒打開的時候清單佔滿整個寬度,照樣全部列出來。
   */
  side?: boolean;
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
  /**
   * 父頁現在照哪幾個字在篩。有給 = 搜尋框顯示的就是它:這個元件被卸下再裝回來(換期間重新載入)時,
   * 框不會變成空的、清單卻還照著剛才的字篩。沒給 = 框自己記(父頁不會把這個元件卸下的才可以不給)。
   */
  searchValue?: string;
  /** 清單是空的時候,清單裡寫的那一句(例:「這段期間沒有雜支」「查無符合「x」的雜支」) */
  emptyText?: string;
}

export function MasterDetail<T>({
  rows,
  columns,
  rowKey,
  tabs,
  actions,
  searchPlaceholder = "搜尋…",
  onSearch,
  searchValue,
  emptyText = "沒有資料",
}: MasterDetailProps<T>) {
  const [selectedKey, setSelectedKey] = useState<string | number | null>(null);
  const [activeTab, setActiveTab] = useState<string>(tabs[0]?.key ?? "");
  // 鍵盤(全站檢視 L04,紅隊):整張清單只停一次 Tab(停在選到的、上次停的、或第一列),方向鍵換列、Enter 打開;
  // 用鍵盤打開的,關掉右邊時游標回到那一列;滑鼠按 × 關的不搬游標
  const rowEls = useRef(new Map<string | number, HTMLTableRowElement>());
  const [focusKey, setFocusKey] = useState<string | number | null>(null);
  const keyOpened = useRef<string | number | null>(null);
  const returnTo = useRef<string | number | null>(null);
  useEffect(() => {
    if (selectedKey !== null || returnTo.current === null) return;
    rowEls.current.get(returnTo.current)?.focus();
    returnTo.current = null;
  }, [selectedKey]);

  const selectedRow = rows.find((r) => rowKey(r) === selectedKey) ?? null;
  const currentActions = selectedRow && actions ? actions(selectedRow) : [];
  const currentTab = tabs.find((t) => t.key === activeTab) ?? tabs[0];
  const shown = selectedRow ? columns.filter((c) => !c.side) : columns;
  const keys = rows.map(rowKey);
  const tabStop = focusKey !== null && keys.includes(focusKey) ? focusKey : selectedRow ? selectedKey : (keys[0] ?? null);

  // 沒選任何一筆:清單佔滿整個寬度、不開右邊(UI 改善計劃 UI-07:不留一大塊空白寫「從左側選擇…」)。
  // 選了一筆:電腦是左右兩欄;手機(窄畫面)整頁換成那一筆,右上「×」回清單(`md-show-detail` 只在窄畫面有作用)
  return (
    <div className={selectedRow ? "md-layout md-show-detail" : "md-layout list-only"}>
      <section className="md-master">
        <div className="md-master-toolbar">
          <input
            type="search"
            placeholder={searchPlaceholder}
            value={searchValue}
            onChange={(e) => onSearch?.(e.target.value)}
          />
        </div>
        <div className="md-table">
          <table>
            <thead>
              <tr>
                {shown.map((c) => (
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
                    ref={(el) => {
                      if (el) rowEls.current.set(k, el);
                      else rowEls.current.delete(k);
                    }}
                    className={k === selectedKey ? "selected" : undefined}
                    tabIndex={k === tabStop ? 0 : -1}
                    aria-selected={k === selectedKey}
                    onFocus={() => setFocusKey(k)}
                    onClick={() => {
                      keyOpened.current = null;
                      setSelectedKey(k);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                        e.preventDefault();
                        const next = stepKey(keys, k, e.key === "ArrowDown" ? 1 : -1);
                        if (next !== null) rowEls.current.get(next)?.focus();
                      } else if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        keyOpened.current = k;
                        setSelectedKey(k);
                      }
                    }}
                  >
                    {shown.map((c) => (
                      <td key={c.key}>{c.render(row)}</td>
                    ))}
                  </tr>
                );
              })}
              {rows.length === 0 && (
                <tr className="md-empty-row">
                  <td colSpan={shown.length} className="md-empty">
                    {emptyText}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
      {selectedRow && (
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
          <button
            type="button"
            className="md-detail-close"
            aria-label="收起"
            title="收起"
            onClick={(e) => {
              // 用鍵盤打開、也用鍵盤關(Enter / 空白鍵按 ×:detail 是 0)的才回到那一列
              returnTo.current = keyOpened.current !== null && e.detail === 0 ? keyOpened.current : null;
              keyOpened.current = null;
              setSelectedKey(null);
            }}
          >
            ×
          </button>
        </div>
        <div className="md-detail-body">{currentTab ? currentTab.render(selectedRow) : null}</div>
        <div className="md-detail-footer">
          {currentActions.map((a) => (
            <button key={a.key} className={a.primary ? "primary" : undefined} onClick={a.onClick}>
              {a.label}
            </button>
          ))}
        </div>
      </section>
      )}
    </div>
  );
}
