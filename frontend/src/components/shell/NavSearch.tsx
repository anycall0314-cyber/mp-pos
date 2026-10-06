import { KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { NavModule, searchNav } from "@/nav";

/**
 * 功能搜尋:打功能名稱(或改名前的舊名字)直接跳過去。
 * 只找功能,不找會員、單據這些資料。Ctrl / Cmd + K 把游標帶過來。
 */
/** 把游標還給頁面上的掃碼框 / 主搜尋框(沒有就只是離開功能搜尋) */
function backToPage(input: HTMLInputElement | null) {
  const main = document.querySelector<HTMLInputElement>(
    ".main-page .wb-scan-in input, .main-page .scan-input, .main-page .wb-big",
  );
  if (main && !main.disabled) main.focus();
  else input?.blur();
}

export function NavSearch({
  modules,
  onNavigate,
  onOpenRequest,
}: {
  modules: NavModule[];
  onNavigate: () => void;
  /** 窄螢幕側邊欄收著的時候,按快捷鍵要先把它打開(不然游標跑到看不見的地方) */
  onOpenRequest: () => void;
}) {
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const [sel, setSel] = useState(0);
  const [open, setOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const hits = useMemo(() => searchNav(text, modules), [text, modules]);

  useEffect(() => {
    function onKey(e: globalThis.KeyboardEvent) {
      // 只認 Ctrl / Cmd + K;條碼槍與一般打字不會送這個組合
      if ((e.metaKey || e.ctrlKey) && !e.altKey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        onOpenRequest();
        // 等側邊欄滑出來再給游標
        window.setTimeout(() => {
          inputRef.current?.focus();
          inputRef.current?.select();
        }, 0);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** 離開功能搜尋:清空、收起窄螢幕的側邊欄(不然掃碼的結果被它遮住)、把游標還給頁面 */
  function leave() {
    setText("");
    setOpen(false);
    onNavigate();
  }

  function go(to: string) {
    leave();
    inputRef.current?.blur();
    navigate(to);
    // 目的地就是現在這一頁時(網址沒變)頁面不會重新掛上去,它自己的 autoFocus 不會再跑一次:
    // 等新畫面出來之後把游標放回掃碼框,下一個條碼才不會打到空的地方。
    // 用 setTimeout 不用 requestAnimationFrame:分頁在背景時後者不會跑。
    window.setTimeout(() => backToPage(inputRef.current), 60);
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.nativeEvent.isComposing || e.keyCode === 229) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSel((s) => Math.min(hits.length - 1, s + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSel((s) => Math.max(0, s - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const hit = hits[sel] ?? hits[0];
      if (hit) {
        go(hit.page.to);
      } else {
        // 找不到功能就按了 Enter:多半是條碼槍刷到這一格來了。清掉,把游標還給頁面的掃碼框,
        // 不要讓下一個碼繼續打在這裡
        leave();
        backToPage(inputRef.current);
      }
    } else if (e.key === "Escape") {
      leave();
      backToPage(inputRef.current);
    }
  }

  return (
    <div className="nav-search">
      <input
        ref={inputRef}
        type="search"
        value={text}
        placeholder="搜尋功能"
        aria-label="搜尋功能"
        title="Ctrl / Cmd + K"
        autoComplete="off"
        spellCheck={false}
        onChange={(e) => {
          setText(e.target.value);
          setSel(0);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => window.setTimeout(() => setOpen(false), 150)}
        onKeyDown={onKeyDown}
      />
      {open && text.trim() !== "" && (
        <div className="nav-search-menu" role="listbox">
          {hits.length === 0 && (
            <div className="nav-search-item none">找不到這個功能</div>
          )}
          {hits.map((h, i) => (
            <div
              key={h.page.to}
              role="option"
              aria-selected={i === sel}
              className={`nav-search-item${i === sel ? " sel" : ""}`}
              onMouseDown={(e) => {
                e.preventDefault();
                go(h.page.to);
              }}
            >
              <span>{h.page.label}</span>
              <span className="nav-search-where">
                {h.via ? `原「${h.via}」 · ` : ""}
                {h.module.label}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
