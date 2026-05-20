import {
  KeyboardEvent,
  ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

export interface ComboOption<T = unknown> {
  id: number;
  label: string;
  secondary?: string;
  payload?: T;
}

interface ComboBoxProps<T = unknown> {
  value: number | "";
  selectedOption?: ComboOption<T> | null;
  onChange: (id: number | "", option?: ComboOption<T>) => void;
  fetchOptions: (query: string) => Promise<ComboOption<T>[]>;
  placeholder?: string;
  disabled?: boolean;
  emptyHint?: ReactNode;
  onCreateNew?: (query: string) => void;
  createNewLabel?: string;
  debounceMs?: number;
  className?: string;
  required?: boolean;
  /** 已有選擇且下拉收合時,按 Enter 觸發(快捷鍵:選完商品直接新增下一行) */
  onEnterAfterValue?: () => void;
  /** 載入後自動 focus 這個輸入框 */
  autoFocus?: boolean;
}

export function ComboBox<T = unknown>({
  value,
  selectedOption,
  onChange,
  fetchOptions,
  placeholder = "輸入關鍵字搜尋…",
  disabled = false,
  emptyHint = "找不到符合的資料",
  onCreateNew,
  createNewLabel = "+ 新增",
  debounceMs = 200,
  className,
  required = false,
  onEnterAfterValue,
  autoFocus = false,
}: ComboBoxProps<T>) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<ComboOption<T>[]>([]);
  const [highlightIdx, setHighlightIdx] = useState(0);
  const [loading, setLoading] = useState(false);

  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const requestSeq = useRef(0);

  // 已選 → 顯示其 label;未選 → 空字串
  const selectedLabel = useMemo(() => {
    if (value === "" || value == null) return "";
    return selectedOption?.label ?? "";
  }, [value, selectedOption]);

  const displayValue = open ? query : selectedLabel;

  const runSearch = useCallback(
    async (q: string) => {
      const seq = ++requestSeq.current;
      setLoading(true);
      try {
        const results = await fetchOptions(q);
        if (seq !== requestSeq.current) return;
        setOptions(results);
        setHighlightIdx(0);
      } finally {
        if (seq === requestSeq.current) setLoading(false);
      }
    },
    [fetchOptions],
  );

  useEffect(() => {
    if (!open) return;
    const handle = setTimeout(() => runSearch(query), debounceMs);
    return () => clearTimeout(handle);
  }, [query, open, debounceMs, runSearch]);

  useEffect(() => {
    function onDocMouseDown(e: MouseEvent) {
      if (!rootRef.current) return;
      if (!rootRef.current.contains(e.target as Node)) {
        setOpen(false);
        setQuery("");
      }
    }
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, []);

  function openAndFocus() {
    if (disabled) return;
    setOpen(true);
    setQuery("");
    runSearch("");
  }

  function pickOption(opt: ComboOption<T>) {
    onChange(opt.id, opt);
    setOpen(false);
    setQuery("");
  }

  function clearValue() {
    onChange("", undefined);
    setQuery("");
    inputRef.current?.focus();
  }

  function handleKey(e: KeyboardEvent<HTMLInputElement>) {
    // 中文 / 日文 / 韓文輸入法選字中按 Enter 不應觸發「選擇選項」
    // 三種偵測:React 合成事件、原生事件、舊版 keyCode 229
    const native = e.nativeEvent as KeyboardEvent["nativeEvent"] & {
      isComposing?: boolean;
    };
    const composing =
      (e as unknown as { isComposing?: boolean }).isComposing ||
      native?.isComposing ||
      e.keyCode === 229;
    if (composing) return;

    if (!open) {
      if (e.key === "Enter") {
        e.preventDefault();
        // 已有選擇且設了 onEnterAfterValue 時,Enter 用來「下一筆」而不是重開下拉
        if (value !== "" && onEnterAfterValue) {
          onEnterAfterValue();
        } else {
          openAndFocus();
        }
        return;
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        openAndFocus();
      }
      return;
    }
    const len = options.length + (onCreateNew && query.trim() ? 1 : 0);
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlightIdx((i) => (len === 0 ? 0 : (i + 1) % len));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlightIdx((i) => (len === 0 ? 0 : (i - 1 + len) % len));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (highlightIdx < options.length) {
        const opt = options[highlightIdx];
        if (opt) pickOption(opt);
      } else if (onCreateNew && query.trim()) {
        onCreateNew(query.trim());
        setOpen(false);
        setQuery("");
      }
    } else if (e.key === "Escape") {
      setOpen(false);
      setQuery("");
    }
  }

  const showCreateRow = !!onCreateNew && query.trim().length > 0;

  return (
    <div
      ref={rootRef}
      className={`combobox${open ? " open" : ""}${disabled ? " disabled" : ""}${className ? " " + className : ""}`}
    >
      <div className="combobox-input-wrap">
        <input
          ref={inputRef}
          type="text"
          className="combobox-input"
          value={displayValue}
          placeholder={placeholder}
          disabled={disabled}
          required={required}
          autoFocus={autoFocus}
          onFocus={openAndFocus}
          onChange={(e) => {
            setQuery(e.target.value);
            if (!open) setOpen(true);
          }}
          onKeyDown={handleKey}
        />
        {value !== "" && !disabled && (
          <button
            type="button"
            className="combobox-clear"
            tabIndex={-1}
            onClick={clearValue}
            aria-label="清除"
          >
            ×
          </button>
        )}
      </div>
      {open && (
        <div className="combobox-pop">
          {loading && options.length === 0 ? (
            <div className="combobox-hint">搜尋中…</div>
          ) : options.length === 0 ? (
            <div className="combobox-hint">{emptyHint}</div>
          ) : (
            <ul className="combobox-list" role="listbox">
              {options.map((opt, idx) => (
                <li
                  key={opt.id}
                  role="option"
                  aria-selected={idx === highlightIdx}
                  className={`combobox-option${idx === highlightIdx ? " active" : ""}`}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    pickOption(opt);
                  }}
                  onMouseEnter={() => setHighlightIdx(idx)}
                >
                  <span className="combobox-option-label">{opt.label}</span>
                  {opt.secondary && (
                    <span className="combobox-option-secondary">{opt.secondary}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
          {showCreateRow && (
            <div
              className={`combobox-create${highlightIdx === options.length ? " active" : ""}`}
              onMouseDown={(e) => {
                e.preventDefault();
                onCreateNew?.(query.trim());
                setOpen(false);
                setQuery("");
              }}
              onMouseEnter={() => setHighlightIdx(options.length)}
            >
              {createNewLabel}「{query.trim()}」
            </div>
          )}
        </div>
      )}
    </div>
  );
}
