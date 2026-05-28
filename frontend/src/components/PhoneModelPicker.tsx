import { useEffect, useRef, useState } from "react";

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
}: Props) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [options, setOptions] = useState<PhoneModelOption[]>([]);
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
          setLoading(false);
        })
        .catch(() => setLoading(false));
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [open, query]);

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
            if (!open) setOpen(true);
          }}
        />
      </div>
      {open && (
        <div className="combobox-pop">
          {loading && options.length === 0 ? (
            <div className="combobox-hint">搜尋中…</div>
          ) : options.length === 0 ? (
            <div className="combobox-hint">找不到符合的機型</div>
          ) : (
            <ul className="combobox-list" role="listbox">
              {options.map((opt) => (
                <li
                  key={opt.model_key}
                  role="option"
                  className="combobox-option"
                  onMouseDown={(e) => {
                    e.preventDefault();
                    onPick(opt);
                    setOpen(false);
                    setQuery("");
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
                    {opt.sku_count} 款 SKU
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
