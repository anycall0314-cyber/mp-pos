import { NavLink } from "react-router-dom";

import { useCurrentUser } from "@/auth/AuthContext";
import { NAV_GROUPS, PLATFORM_NAV_GROUP } from "@/nav";
import { Toolbar } from "@/components/Toolbar";

/**
 * 登入後的入口頁:把所有主類別 + 子項目用大字大行高列出來,
 * 手機友善(整列當按鈕)、桌機也清楚。
 */
export function HomePage() {
  const user = useCurrentUser();
  const groups =
    user?.profile?.role === "platform_admin"
      ? [PLATFORM_NAV_GROUP, ...NAV_GROUPS]
      : NAV_GROUPS;

  return (
    <div className="page">
      <Toolbar title="主選單" />
      <div className="home-grid">
        {groups.map((g) => (
          <section key={g.key} className="home-group">
            <div className="home-group-label">{g.label}</div>
            <ul className="home-item-list">
              {g.items.map((it) => (
                <li key={it.to}>
                  <NavLink to={it.to} className="home-item-link">
                    {it.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
