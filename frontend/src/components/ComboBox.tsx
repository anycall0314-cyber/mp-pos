import {
  KeyboardEvent,
  ReactNode,
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";

export interface ComboOption<T = unknown> {
  id: number;
  label: string;
  secondary?: string;
  payload?: T;
  /** 看得到但不能選(例:已停用的商品,要讓人認得它已經建過檔) */
  disabled?: boolean;
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
  /**
   * 沒用上下鍵動過反白時,Enter 只選「跟打的字完全相同」的那一筆(卡號、電話);沒有就留著清單讓人挑。
   * 條碼槍自帶 Enter:刷 SIM 卡選到第一筆、會員打完電話選到別人(全站檢視 A2)。不給 = 照舊選反白的那一筆。
   */
  exactOnEnter?: (opt: ComboOption<T>, query: string) => boolean;
  /** 欄名(讀螢幕念的、清除鈕的名字);外面包 Field 的會自動用 Field 的欄名,不用給 */
  ariaLabel?: string;
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
  exactOnEnter,
  ariaLabel,
}: ComboBoxProps<T>) {
  // 讀螢幕:輸入框是 combobox、連到下面的清單、念出現在反白的那一筆(全站控制項 MC-04;選的規則沒動)
  const listId = `cb${useId().replace(/:/g, "")}`;
  const optionId = (idx: number) => `${listId}-o${idx}`;
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<ComboOption<T>[]>([]);
  const [highlightIdx, setHighlightIdx] = useState(0);
  const [loading, setLoading] = useState(false);

  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const requestSeq = useRef(0);
  /** 現在這份清單是哪一串字的結果:Enter 要等「現在打的字」的結果回來才選(全站檢視 A2:以前會選到舊清單的第一筆) */
  const resultsFor = useRef<string | null>(null);
  const pendingEnter = useRef(false);
  const queryNow = useRef("");
  /** 人用上下鍵動過反白(動過就照反白的選,不要求完全相同) */
  const moved = useRef(false);

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
        resultsFor.current = q;
        setOptions(results);
        // 預設反白第一個「能選的」;第一筆若是不能選的(已停用)就往下找
        const first = results.findIndex((o) => !o.disabled);
        setHighlightIdx(first < 0 ? 0 : first);
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
        pendingEnter.current = false;
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
    queryNow.current = "";
    moved.current = false;
    runSearch("");
  }

  /** Enter 選哪一筆:要求完全相同的(沒動過反白)只選完全相同的;不然選反白的(或「新增」那一列) */
  function enterPick() {
    if (exactOnEnter && !moved.current) {
      const exact = options.find((o) => !o.disabled && exactOnEnter(o, query.trim()));
      if (exact) pickOption(exact);
      return;
    }
    if (highlightIdx < options.length) {
      const opt = options[highlightIdx];
      if (opt) pickOption(opt);
    } else if (onCreateNew && query.trim()) {
      onCreateNew(query.trim());
      setOpen(false);
      setQuery("");
    }
  }

  // 按 Enter 的時候結果還沒回來:回來了(而且是現在這串字的)才選
  // 等的時候人按了 Esc / 點到外面 / 自己點了一筆(複審 P1:晚到的結果不能再替他選,例如銷退的原單被換掉)
  useEffect(() => {
    if (!pendingEnter.current || resultsFor.current !== queryNow.current) return;
    pendingEnter.current = false;
    if (!open) return;
    enterPick();
    // 只跟著新的結果走
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [options]);

  function pickOption(opt: ComboOption<T>) {
    if (opt.disabled) return;
    pendingEnter.current = false;
    onChange(opt.id, opt);
    setOpen(false);
    setQuery("");
  }

  function clearValue() {
    pendingEnter.current = false;
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
    // 上下鍵跳過不能選的選項(最多繞一圈)
    const step = (i: number, delta: number) => {
      if (len === 0) return 0;
      let next = i;
      for (let n = 0; n < len; n++) {
        next = (next + delta + len) % len;
        if (!options[next]?.disabled) return next;
      }
      return i;
    };
    if (e.key === "ArrowDown") {
      e.preventDefault();
      moved.current = true;
      setHighlightIdx((i) => step(i, 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      moved.current = true;
      setHighlightIdx((i) => step(i, -1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      // 現在打的這串字還沒有結果(還在等、或還沒開始查):馬上查,回來再選
      if (resultsFor.current !== query) {
        pendingEnter.current = true;
        void runSearch(query);
        return;
      }
      enterPick();
    } else if (e.key === "Escape") {
      pendingEnter.current = false;
      setOpen(false);
      setQuery("");
    } else if (e.key === "Delete" && query === "" && value !== "" && !disabled) {
      // 鍵盤清掉已選的(清除鈕不佔 Tab 順序;沒打字時按 Delete 才算,打字中的 Delete 照常刪字)
      e.preventDefault();
      clearValue();
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
          onFocus={(e) => {
            openAndFocus();
            // 手機:把 input 捲到視窗頂端,避免下拉選單被 iOS 鍵盤蓋住
            if (window.matchMedia("(max-width: 768px)").matches) {
              setTimeout(() => {
                e.target.scrollIntoView({ block: "start", behavior: "smooth" });
              }, 100);
            }
          }}
          onChange={(e) => {
            setQuery(e.target.value);
            queryNow.current = e.target.value;
            moved.current = false;
            pendingEnter.current = false;
            if (!open) setOpen(true);
          }}
          onKeyDown={handleKey}
          role="combobox"
          aria-label={ariaLabel}
          aria-expanded={open}
          aria-controls={open && options.length > 0 ? listId : undefined}
          aria-autocomplete="list"
          aria-activedescendant={open && highlightIdx < options.length && options.length > 0 ? optionId(highlightIdx) : undefined}
          aria-keyshortcuts={value !== "" && !disabled ? "Delete" : undefined}
        />
        {value !== "" && !disabled && (
          <button
            type="button"
            className="combobox-clear"
            tabIndex={-1}
            onClick={clearValue}
            aria-label={ariaLabel ? `清除${ariaLabel}` : "清除"}
            title="清除(游標在框裡時也可以按 Delete)"
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
            <ul className="combobox-list" role="listbox" id={listId} aria-label={ariaLabel ? `${ariaLabel}的候選` : "候選"}>
              {options.map((opt, idx) => (
                <li
                  key={opt.id}
                  id={optionId(idx)}
                  role="option"
                  aria-selected={opt.disabled ? undefined : idx === highlightIdx}
                  aria-disabled={opt.disabled || undefined}
                  className={`combobox-option${idx === highlightIdx ? " active" : ""}${opt.disabled ? " disabled" : ""}`}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    pickOption(opt);
                  }}
                  onMouseEnter={() => {
                    if (!opt.disabled) setHighlightIdx(idx);
                  }}
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
