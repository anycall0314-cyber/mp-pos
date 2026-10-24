import { useRef, type ReactNode } from "react";

import { cx, nextIndex } from "@/lib/uiKeys";

/**
 * 同一頁裡換工作區(docs/ui-controls.md §1、§4):文字 + 底線,選中的有 aria-selected。換路由用連結,不是這個。
 * 鍵盤:整排只停一次 Tab(選中的那一個),左右鍵 / Home / End 換一頁並選起來。
 * 內容用 `TabPanel` 包,`id` 兩邊給一樣的(綁 aria-controls / aria-labelledby)。
 * 換頁就只是換頁:不重設草稿、不送出、不確認(各頁原本的保留規則照舊)。
 */
export interface TabItem<K extends string> {
  key: K;
  label: ReactNode;
  /** 分頁旁邊的小字(數量、「還沒儲存」);是狀態,不能按 */
  note?: ReactNode;
  /** 小字要提醒時的顏色:alert = 要處理(紅字)、warn = 建議看一下(黃字);不給就是灰字 */
  noteTone?: "alert" | "warn";
  disabled?: boolean;
}

export function Tabs<K extends string>({
  id,
  label,
  items,
  value,
  onChange,
  className,
}: {
  id: string;
  label: string;
  items: TabItem<K>[];
  value: K;
  onChange: (key: K) => void;
  className?: string;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const at = items.findIndex((t) => t.key === value);
  return (
    <div role="tablist" aria-label={label} className={cx("ui-tabs", className)}>
      {items.map((t, i) => (
        <button
          key={t.key}
          ref={(el) => {
            refs.current[i] = el;
          }}
          type="button"
          role="tab"
          id={`${id}-tab-${t.key}`}
          aria-controls={`${id}-panel-${t.key}`}
          aria-selected={t.key === value}
          tabIndex={t.key === value || (at < 0 && i === 0) ? 0 : -1}
          disabled={t.disabled}
          className="ui-tab"
          onClick={() => onChange(t.key)}
          onKeyDown={(e) => {
            const n = nextIndex(items.length, i, e.key, (j) => !!items[j].disabled);
            if (n === null) return;
            e.preventDefault();
            refs.current[n]?.focus();
            onChange(items[n].key);
          }}
        >
          {t.label}
          {t.note !== undefined && t.note !== null && t.note !== false && <span className={cx("ui-tab-note", t.noteTone)}>{t.note}</span>}
        </button>
      ))}
    </div>
  );
}

export function TabPanel({ id, k, active, children, className }: { id: string; k: string; active: boolean; children: ReactNode; className?: string }) {
  return (
    <div role="tabpanel" id={`${id}-panel-${k}`} aria-labelledby={`${id}-tab-${k}`} hidden={!active} className={className}>
      {children}
    </div>
  );
}
