import { ReactNode } from "react";
import { Link } from "react-router-dom";

import { NavMatch, NavModule } from "@/nav";

import { NavSearch } from "./NavSearch";

/**
 * 側邊欄:今日總覽 + 業務入口(名稱一律 4 個字),系統設定固定在最下面。
 * 點一個入口直接進它的預設頁;同一個入口的其他頁在頁面上方的分頁切換(ModuleBar)。
 */
export function Sidebar({
  modules,
  match,
  onNavigate,
  onOpenRequest,
  footer,
}: {
  modules: NavModule[];
  match: NavMatch | null;
  onNavigate: () => void;
  onOpenRequest: () => void;
  footer: ReactNode;
}) {
  const main = modules.filter((m) => !m.bottom);
  const bottom = modules.filter((m) => m.bottom);

  function link(m: NavModule) {
    const active = match?.module.key === m.key;
    return (
      <Link
        key={m.key}
        to={m.to}
        onClick={onNavigate}
        className={`sidebar-link${active ? " active" : ""}`}
        // 同一層只有一個「目前這一頁」:人就在這個入口的預設頁才標 page,在它底下的其他頁標 true
        aria-current={
          active ? (match?.page.to === m.to ? "page" : "true") : undefined
        }
      >
        {m.label}
      </Link>
    );
  }

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">MP POS</div>
      <NavSearch
        modules={modules}
        onNavigate={onNavigate}
        onOpenRequest={onOpenRequest}
      />
      <nav className="sidebar-nav" aria-label="主要功能">
        {main.map(link)}
      </nav>
      {bottom.length > 0 && (
        <nav className="sidebar-bottom" aria-label="系統">
          {bottom.map(link)}
        </nav>
      )}
      <div className="sidebar-footer">{footer}</div>
    </aside>
  );
}
