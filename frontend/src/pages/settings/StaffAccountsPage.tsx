import { useQueryClient } from "@tanstack/react-query";
import { useState, useSyncExternalStore } from "react";

import { useSaveStaffAbilities, useStaffAccountAccess, useStaffAccounts } from "@/api/hooks";
import type { StaffAccount, StaffAccountsResponse } from "@/api/types";
import { Toolbar } from "@/components/Toolbar";
import { ArmButton } from "@/components/workbench/ArmButton";
import { apiErrorText } from "@/components/workbench/errors";
import { toast } from "@/components/workbench/toast";
import { groupAbilities, staffSaveGate, withAbility } from "@/lib/abilities";
import { MIN_PASSWORD_LENGTH, passwordProblem } from "@/lib/password";

/**
 * 系統設定 → 員工帳號:每個店員帳號一項一項勾(owner 2026-10-10)。
 * 預設全開;勾掉 = 這個帳號不能做那件事(伺服器會擋,不是只把按鈕藏起來)。
 * 管理員永遠全開、這一頁改不了。
 * 店員帳號可以在這裡重設密碼、停用 / 啟用(owner 2026-10-19:老闆要收得回離職的人的帳號);
 * 兩種都讓那個店員每一台重新登入,停用連業務員一起停。管理員帳號與新增帳號照舊在平台管理。
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
                      {a.editable && <AccountAccess account={a} />}
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

/** 店員那一列:重設密碼(就地打新密碼,不跳視窗)、停用 / 啟用帳號(停用要按兩次) */
function AccountAccess({ account }: { account: StaffAccount }) {
  const access = useStaffAccountAccess();
  const [password, setPassword] = useState<string | null>(null);
  const who = account.name || account.username;

  async function send(body: { password?: string; is_active?: boolean }, done: string) {
    try {
      await access.mutateAsync({ id: account.id, ...body });
      setPassword(null);
      toast(`${who}${done}`, "ok");
    } catch (e) {
      toast(apiErrorText(e), "err");
    }
  }

  if (password !== null) {
    const short = passwordProblem(password) !== "";
    return (
      <div className="staff-acts">
        <input
          className="staff-pw"
          aria-label={`${who}的新密碼`}
          placeholder={`新密碼,至少 ${MIN_PASSWORD_LENGTH} 碼`}
          autoComplete="off"
          autoFocus
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !short) void send({ password }, "的密碼已重設");
            if (e.key === "Escape") setPassword(null);
          }}
        />
        <button type="button" className="btn" disabled={short || access.isPending}
          onClick={() => void send({ password }, "的密碼已重設")}>
          儲存
        </button>
        <button type="button" className="btn" disabled={access.isPending} onClick={() => setPassword(null)}>
          取消
        </button>
      </div>
    );
  }
  return (
    <div className="staff-acts">
      <button type="button" className="btn" disabled={!account.is_active || access.isPending} onClick={() => setPassword("")}>
        重設密碼
      </button>
      {account.is_active ? (
        <ArmButton className="btn" label="停用帳號" armedLabel="確定停用" disabled={access.isPending}
          onConfirm={() => send({ is_active: false }, "的帳號已停用")} />
      ) : (
        <button type="button" className="btn" disabled={access.isPending}
          onClick={() => void send({ is_active: true }, "的帳號已啟用")}>
          啟用帳號
        </button>
      )}
    </div>
  );
}
