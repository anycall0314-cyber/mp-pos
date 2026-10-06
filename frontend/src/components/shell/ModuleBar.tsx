import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { isWorkspacePath, NavMatch } from "@/nav";

/**
 * 頁面上方的分頁列:同一個入口底下的其他頁在這裡切換。
 * 右邊的具名選單(商品設定、作業設定)放低頻的設定頁。
 * 只有一頁、也沒有設定頁的入口(工作台)不佔這一排;開單頁(`isWorkspacePath`)也不佔。
 */
export function ModuleBar({
  match,
  pathname,
}: {
  match: NavMatch | null;
  pathname: string;
}) {
  const [open, setOpen] = useState(false);
  const toolsRef = useRef<HTMLDivElement>(null);

  // 點別的地方 / 按 Esc 把選單收起來
  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (!toolsRef.current?.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // 換頁(含瀏覽器的上一頁 / 下一頁)就把選單收起來,不要帶著展開的選單到另一個入口
  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  if (!match) return null;
  // 開單頁把高度留給明細:不放這一排,頁首有「返回列表」
  if (isWorkspacePath(pathname)) return null;
  const { module, page } = match;
  const tools = module.tools?.items ?? [];
  if (module.tabs.length <= 1 && tools.length === 0) return null;
  const inTools = tools.find((p) => p.to === page.to);
  // 只有一個分頁的入口(銷貨、維修):在清單頁才放這一排(為了右邊的設定選單);
  // 進到開單 / 維修單這種子頁就收起來,把高度留給明細
  if (module.tabs.length <= 1 && !inTools && pathname !== page.to) return null;

  return (
    <div className="module-bar">
      <nav className="module-tabs" aria-label={`${module.label}的頁面`}>
        {module.tabs.map((p) => {
          const active = p.to === page.to;
          return (
            <Link
              key={p.to}
              to={p.to}
              className={`module-tab${active ? " active" : ""}`}
              aria-current={active ? "page" : undefined}
            >
              {p.label}
            </Link>
          );
        })}
      </nav>
      {module.tools && tools.length > 0 && (
        <div className="module-tools" ref={toolsRef}>
          <button
            type="button"
            className={`module-tools-btn${inTools ? " active" : ""}`}
            aria-current={inTools ? "page" : undefined}
            aria-haspopup="menu"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            {module.tools.label}
            {inTools ? ` · ${inTools.label}` : ""}
            <span aria-hidden="true"> ▾</span>
          </button>
          {open && (
            <div className="module-tools-menu" role="menu">
              {tools.map((p) => {
                const active = p.to === page.to;
                return (
                  <Link
                    key={p.to}
                    to={p.to}
                    role="menuitem"
                    className={`module-tools-item${active ? " active" : ""}`}
                    aria-current={active ? "page" : undefined}
                    onClick={() => setOpen(false)}
                  >
                    {p.label}
                  </Link>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
