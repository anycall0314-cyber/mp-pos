import { useQueryClient } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";

import { useSaveStaffAbilities, useStaffAccounts } from "@/api/hooks";
import type { StaffAccountsResponse } from "@/api/types";
import { Toolbar } from "@/components/Toolbar";
import { apiErrorText } from "@/components/workbench/errors";
import { toast } from "@/components/workbench/toast";
import { groupAbilities, staffSaveGate, withAbility } from "@/lib/abilities";

/**
 * 系統設定 → 員工帳號:每個店員帳號一項一項勾(owner 2026-10-10)。
 * 預設全開;勾掉 = 這個帳號不能做那件事(伺服器會擋,不是只把按鈕藏起來)。
 * 管理員永遠全開、這一頁改不了。帳號的新增 / 停用 / 密碼照舊在平台管理。
 * 勾了就存:畫面先換;**那一格存完之前不能再按**(兩個請求先後到的順序不一定)。管這件事的閘門是 lib/abilities 的 staffSaveGate,
 * 放在模組裡、不跟著這一頁走:存到一半切到別頁再回來,那一格還是鎖著;
 * 全部存完才重抓一次,以伺服器的為準(沒存成的會換回來並講原因)。
 */
export function StaffAccountsPage() {
  const qc = useQueryClient();
  const { data, isLoading, isError, error } = useStaffAccounts();
  const save = useSaveStaffAbilities();
  const gate = staffSaveGate;
  // 閘門裡哪幾格在存變了就重畫(把那幾格停用 / 放開);離開這一頁再回來也接得上
  useSyncExternalStore(gate.subscribe, gate.version);

  async function toggle(id: number, key: string, allowed: boolean) {
    if (gate.busy(id, key)) return;
    // 還在路上的重抓先丟掉:它是這一下之前的樣子,晚一點回來會把剛勾的蓋回去
    void qc.cancelQueries({ queryKey: ["staff-accounts"] });
    qc.setQueryData<StaffAccountsResponse>(["staff-accounts"], (old) =>
      old
        ? { ...old, accounts: withAbility(old.accounts, id, key, allowed) }
        : old,
    );
    try {
      await gate.run(id, key, () =>
        save.mutateAsync({ id, abilities: { [key]: allowed } }),
      );
    } catch (e) {
      toast(apiErrorText(e), "err");
    } finally {
      if (gate.idle()) qc.invalidateQueries({ queryKey: ["staff-accounts"] });
    }
  }

  const groups = groupAbilities(data?.abilities ?? []);

  return (
    <div className="page">
      <Toolbar title="員工帳號" />
      <div className="entry-body">
        {isLoading && <div className="md-empty">載入中…</div>}
        {isError && <div className="md-empty">{apiErrorText(error)}</div>}
        {data && (
          <div className="staff-scroll">
            <table className="staff-table">
              <thead>
                <tr>
                  <th rowSpan={2}>帳號</th>
                  <th rowSpan={2}>門市</th>
                  {groups.map((g) => (
                    <th
                      key={g.group}
                      colSpan={g.items.length}
                      className="staff-group"
                    >
                      {g.group}
                    </th>
                  ))}
                </tr>
                <tr>
                  {groups.flatMap((g) =>
                    g.items.map((item) => (
                      <th key={item.key} className="staff-item">
                        {item.label}
                        {item.note && (
                          <div className="staff-note">{item.note}</div>
                        )}
                      </th>
                    )),
                  )}
                </tr>
              </thead>
              <tbody>
                {data.accounts.map((a) => (
                  <tr key={a.id} className={a.is_active ? "" : "staff-off"}>
                    <td>
                      {a.name || a.username}
                      <div className="staff-note">
                        {a.username}
                        {a.editable ? "" : ` · ${a.role_label}`}
                        {a.is_active ? "" : " · 已停用"}
                      </div>
                    </td>
                    <td>{a.warehouse || "—"}</td>
                    {groups.flatMap((g) =>
                      g.items.map((item) => (
                        <td key={item.key} className="staff-check">
                          <input
                            type="checkbox"
                            aria-label={`${a.name || a.username}:${item.label}`}
                            checked={a.abilities[item.key] !== false}
                            disabled={!a.editable || gate.busy(a.id, item.key)}
                            onChange={(e) =>
                              toggle(a.id, item.key, e.target.checked)
                            }
                          />
                        </td>
                      )),
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
