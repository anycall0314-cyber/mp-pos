import { useEffect, useId, useRef, useState } from "react";

import { searchPhoneModels } from "@/api/search";
import type { LifecycleStatus } from "@/api/types";

interface PhoneModelOption {
  model_key: string;
  model_name: string;
  sku_count: number;
  any_lifecycle_status: string;
}

interface Props {
  onPick: (model: PhoneModelOption) => void;
  placeholder?: string;
  /** 允許找不到時直接以輸入字串新增一個機型(只有維修單:機型是自由文字)。商品的相容機型要是型號庫有的,不能開(全站檢視 D5:以前開著,看起來加上去了、按儲存才被退回)。 */
  allowCreate?: boolean;
}

function lifecycleClass(s: string): string {
  switch (s as LifecycleStatus) {
    case "active":
      return "ia-badge ia-badge-active";
    case "replacing":
      return "ia-badge ia-badge-replacing";
    case "discontinued":
      return "ia-badge ia-badge-discontinued";
    case "clearance":
      return "ia-badge ia-badge-clearance";
    default:
      return "ia-badge";
  }
}

function lifecycleLabel(s: string): string {
  switch (s as LifecycleStatus) {
    case "active":
      return "主力現貨";
    case "replacing":
      return "即將換代";
    case "discontinued":
      return "停產下架";
    case "clearance":
      return "清倉處理";
    default:
      return "";
  }
}

/** 機型搜尋下拉:回傳 model_key 為主鍵的選項。
 * 跟一般 ComboBox 不同,id 是 string (model_key)。
 */
export function PhoneModelPicker({
  onPick,
  placeholder = "搜尋機型名稱…",
  allowCreate = false,
}: Props) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [options, setOptions] = useState<PhoneModelOption[]>([]);
  // 上下鍵移動、Enter 選(全站檢視 D5:以前只能用滑鼠點)
  const [highlight, setHighlight] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    const t = setTimeout(() => {
      searchPhoneModels(query)
        .then((opts) => {
          if (cancelled) return;
          setOptions(
            opts.map((o) => ({
              model_key: o.model_key,
              model_name: o.model_name,
              sku_count: o.sku_count,
              any_lifecycle_status: o.any_lifecycle_status,
            })),
          );
          setHighlight(0);
          setLoading(false);
        })
        .catch(() => setLoading(false));
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [open, query]);

  // 讀螢幕:combobox 連到清單、念反白的那一筆(全站控制項 MC-04)
  const listId = `pm${useId().replace(/:/g, "")}`;
  const trimmed = query.trim();
  const canCreate =
    allowCreate &&
    !!trimmed &&
    !options.some(
      (o) => o.model_name.toLowerCase() === trimmed.toLowerCase() || o.model_key === trimmed.toLowerCase(),
    );
  /** 下拉裡可以選的:搜到的機型,加上(允許的話)最後一列「新增機型」 */
  const choiceCount = options.length + (canCreate ? 1 : 0);

  function choose(idx: number) {
    if (idx < options.length) {
      onPick(options[idx]);
    } else if (canCreate) {
      onPick({ model_key: trimmed.toLowerCase(), model_name: trimmed, sku_count: 0, any_lifecycle_status: "" });
    } else {
      return;
    }
    setOpen(false);
    setQuery("");
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.nativeEvent.isComposing) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!open) setOpen(true);
      else if (choiceCount > 0) setHighlight((h) => (h + 1) % choiceCount);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (choiceCount > 0) setHighlight((h) => (h - 1 + choiceCount) % choiceCount);
    } else if (e.key === "Enter") {
      // 還在搜(打完字 0.2 秒內)不選:等這次的結果回來,不會選到上一次清單的第一筆
      e.preventDefault();
      if (open && !loading && choiceCount > 0) choose(Math.min(highlight, choiceCount - 1));
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  function focusAndOpen(e?: React.FocusEvent<HTMLInputElement>) {
    setOpen(true);
    setQuery("");
    if (e && window.matchMedia("(max-width: 768px)").matches) {
      setTimeout(() => {
        e.target.scrollIntoView({ block: "start", behavior: "smooth" });
      }, 100);
    }
  }

  return (
    <div ref={rootRef} className={`combobox${open ? " open" : ""}`}>
      <div className="combobox-input-wrap">
        <input
          ref={inputRef}
          className="combobox-input"
          type="text"
          value={query}
          placeholder={placeholder}
          onFocus={focusAndOpen}
          onChange={(e) => {
            setQuery(e.target.value);
            setLoading(true);
            if (!open) setOpen(true);
          }}
          onKeyDown={onKeyDown}
          role="combobox"
          aria-expanded={open}
          aria-controls={open && choiceCount > 0 ? listId : undefined}
          aria-autocomplete="list"
          aria-activedescendant={open && choiceCount > 0 ? `${listId}-o${Math.min(highlight, choiceCount - 1)}` : undefined}
        />
      </div>
      {open && (
        <div className="combobox-pop">
          {loading && options.length === 0 ? (
            <div className="combobox-hint">搜尋中…</div>
          ) : options.length === 0 && !canCreate ? (
            <div className="combobox-hint">
              {allowCreate && !trimmed ? "打機型名稱" : "型號庫沒有這支"}
            </div>
          ) : (
            <ul className="combobox-list" role="listbox" id={listId} aria-label="機型候選">
              {options.map((opt, idx) => (
                <li
                  key={opt.model_key}
                  id={`${listId}-o${idx}`}
                  role="option"
                  aria-selected={idx === highlight}
                  className={`combobox-option${idx === highlight ? " active" : ""}`}
                  onMouseEnter={() => setHighlight(idx)}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    choose(idx);
                  }}
                >
                  <span className="combobox-option-label">
                    {opt.model_name}
                  </span>
                  <span className="combobox-option-secondary">
                    <span className={lifecycleClass(opt.any_lifecycle_status)}>
                      {lifecycleLabel(opt.any_lifecycle_status)}
                    </span>
                    {"  "}
                    {opt.sku_count} 個品項
                  </span>
                </li>
              ))}
              {canCreate && (
                  <li
                    id={`${listId}-o${options.length}`}
                    role="option"
                    aria-selected={highlight === options.length}
                    className={`combobox-option combobox-option-create${highlight === options.length ? " active" : ""}`}
                    onMouseEnter={() => setHighlight(options.length)}
                    onMouseDown={(e) => {
                      e.preventDefault();
                      choose(options.length);
                    }}
                  >
                    <span className="combobox-option-label">
                      新增機型「{query.trim()}」
                    </span>
                    <span className="combobox-option-secondary">
                      自訂(本店未販售)
                    </span>
                  </li>
                )}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
