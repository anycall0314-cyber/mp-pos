import { FormEvent, useState } from "react";

import { useSaveStaffAccount, useStaffAccountAccess } from "@/api/hooks";
import type { StaffAccount, StaffAccountsResponse, Warehouse } from "@/api/types";
import { Banner } from "@/components/Banner";
import { Checkbox, Field } from "@/components/Field";
import { PaneForm } from "@/components/PaneForm";
import { ArmButton } from "@/components/workbench/ArmButton";
import { apiErrorText } from "@/components/workbench/errors";
import { toast } from "@/components/workbench/toast";
import { useArm } from "@/components/workbench/useArm";
import { changed, leaveArmed, leaveDraft } from "@/lib/draftGuard";
import { MIN_PASSWORD_LENGTH, passwordProblem } from "@/lib/password";
import { changedFlags, defaultRole, type Flags, roleFlags } from "@/lib/staffAccess";

import { AbilityChecklist } from "./AbilityChecklist";

interface FormState {
  name: string;
  username: string;
  password: string;
  warehouse: number | "";
  locked: boolean;
  role: number | "";
  flags: Flags;
}

function toState(data: StaffAccountsResponse, a: StaffAccount | null): FormState {
  if (a) {
    return {
      // 沒有名字的舊帳號先帶帳號名稱(不然只想改一個勾也被「名字要填」擋住);沒改就不送
      name: a.name || a.username,
      username: a.username,
      password: "",
      warehouse: a.warehouse_id ?? "",
      locked: a.warehouse_locked,
      role: a.staff_role?.id ?? "",
      flags: { ...a.own },
    };
  }
  // 預設帶最多人用的身份別(一樣多 → 先建的);新公司第一個是店長,新人不該預設拿店長的權限
  const first = defaultRole(data.roles);
  return {
    name: "",
    username: data.next_username,
    password: "",
    warehouse: "",
    locked: false,
    role: first?.id ?? "",
    flags: roleFlags(data.abilities, first),
  };
}

/**
 * 員工帳號的新增 / 編輯整頁(owner 2026-10-27;不開彈窗)。上面名字、帳號、門市、身份別,下面權限直的排。
 * 換身份別 = 勾選整組照新身份別(例外清掉);之後再勾的、跟身份別不一樣的就是這個帳號的例外。
 */
export function StaffAccountForm({
  data,
  initial,
  stores,
  onClose,
}: {
  data: StaffAccountsResponse;
  /** 編輯哪一個;null = 新增 */
  initial: StaffAccount | null;
  stores: Warehouse[];
  onClose: (saved?: string) => void;
}) {
  const [state, setState] = useState<FormState>(() => toState(data, initial));
  const [base] = useState<FormState>(() => toState(data, initial));
  const [error, setError] = useState<string | null>(null);
  const save = useSaveStaffAccount();
  const arm = useArm();
  const dirty = changed(state, base);
  const isEdit = !!initial;
  const role = data.roles.find((r) => r.id === state.role) ?? null;
  const roleValues = roleFlags(data.abilities, role);

  function patch<K extends keyof FormState>(k: K, v: FormState[K]) {
    setState((s) => ({ ...s, [k]: v }));
  }

  function chooseRole(id: number | "") {
    const next = data.roles.find((r) => r.id === id) ?? null;
    setState((s) => ({ ...s, role: id, flags: roleFlags(data.abilities, next) }));
  }

  function back() {
    leaveDraft(dirty, arm, "back", () => onClose());
  }

  async function submit(e?: FormEvent) {
    e?.preventDefault();
    setError(null);
    if (!state.name.trim()) return setError("名字要填");
    if (state.locked && state.warehouse === "") return setError("鎖在門市要先選門市");
    const warehouse = state.warehouse === "" ? null : state.warehouse;
    const staff_role = state.role === "" ? null : state.role;
    try {
      if (!isEdit) {
        if (!state.username.trim()) return setError("帳號要填");
        const problem = passwordProblem(state.password);
        if (problem) return setError(problem);
        const made = await save.mutateAsync({
          username: state.username.trim(),
          name: state.name.trim(),
          password: state.password,
          warehouse,
          warehouse_locked: state.locked,
          staff_role,
          abilities: changedFlags(roleValues, state.flags),
        });
        onClose(`已新增 ${made.username}`);
        return;
      }
      // 只送改過的;權限只送跟原本不一樣的項目(換身份別時伺服器先清掉例外,再跟新身份別比)
      const body: Parameters<typeof save.mutateAsync>[0] = { id: initial.id };
      if (state.name.trim() !== base.name) body.name = state.name.trim();
      if (warehouse !== initial.warehouse_id) body.warehouse = warehouse;
      if (state.locked !== initial.warehouse_locked) body.warehouse_locked = state.locked;
      const roleChanged = staff_role !== (initial.staff_role?.id ?? null);
      if (roleChanged) body.staff_role = staff_role;
      const flags = changedFlags(roleChanged ? roleValues : initial.own, state.flags);
      if (Object.keys(flags).length) body.abilities = flags;
      if (Object.keys(body).length === 1) return onClose();
      await save.mutateAsync(body);
      onClose(`已儲存 ${state.name.trim()}`);
    } catch (err) {
      setError(apiErrorText(err));
    }
  }

  return (
    <PaneForm
      title={isEdit ? initial.name || initial.username : "新增帳號"}
      onBack={back}
      leaveArmed={leaveArmed(arm.armed, "back")}
      busy={save.isPending}
      footer={
        <button className="btn primary" type="button" onClick={() => void submit()} disabled={save.isPending}>
          {save.isPending ? "儲存中…" : "儲存"}
        </button>
      }
    >
      {error && <Banner kind="error" message={error} />}
      <form className="staff-form" onSubmit={submit}>
        <div className="staff-form-grid">
          <Field label="名字" required>
            <input value={state.name} maxLength={30} autoFocus={!isEdit} onChange={(e) => patch("name", e.target.value)} />
          </Field>
          {isEdit ? (
            <Field label="帳號">
              <input value={initial.username} readOnly />
            </Field>
          ) : (
            <Field label="帳號" required>
              <input value={state.username} maxLength={20} autoComplete="off" onChange={(e) => patch("username", e.target.value)} />
            </Field>
          )}
          {!isEdit && (
            <Field label="密碼" required>
              <input
                value={state.password}
                autoComplete="new-password"
                placeholder={`至少 ${MIN_PASSWORD_LENGTH} 碼`}
                onChange={(e) => patch("password", e.target.value)}
              />
            </Field>
          )}
          <Field label="門市">
            <select
              value={state.warehouse}
              onChange={(e) => patch("warehouse", e.target.value ? Number(e.target.value) : "")}
            >
              <option value="">全部</option>
              {stores.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="身份別" required={data.roles.length > 0}>
            <select value={state.role} onChange={(e) => chooseRole(e.target.value ? Number(e.target.value) : "")}>
              {(data.roles.length === 0 || state.role === "") && <option value="">—</option>}
              {data.roles.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Checkbox checked={state.locked} onChange={(v) => patch("locked", v)} label="鎖在這間門市" />
        {isEdit && <AccountAccess account={initial} />}
      </form>
      <AbilityChecklist
        items={data.abilities}
        values={state.flags}
        role={roleValues}
        onChange={(flags) => patch("flags", flags)}
        disabled={save.isPending}
      />
    </PaneForm>
  );
}

/** 重設密碼(就地打新密碼,不跳視窗)、停用 / 啟用帳號(停用要按兩次);按下去就生效,跟上面的儲存無關 */
function AccountAccess({ account }: { account: StaffAccount }) {
  const access = useStaffAccountAccess();
  const [password, setPassword] = useState<string | null>(null);
  const [active, setActive] = useState(account.is_active);
  const who = account.name || account.username;

  async function send(body: { password?: string; is_active?: boolean }, done: string) {
    try {
      const saved = await access.mutateAsync({ id: account.id, ...body });
      setPassword(null);
      setActive(saved.is_active);
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
            if (e.key === "Enter") {
              e.preventDefault();
              if (!short) void send({ password }, "的密碼已重設");
            }
            if (e.key === "Escape") setPassword(null);
          }}
        />
        <button type="button" className="btn" disabled={short || access.isPending} onClick={() => void send({ password }, "的密碼已重設")}>
          確定
        </button>
        <button type="button" className="btn" disabled={access.isPending} onClick={() => setPassword(null)}>
          取消
        </button>
      </div>
    );
  }
  return (
    <div className="staff-acts">
      <button type="button" className="btn" disabled={!active || access.isPending} onClick={() => setPassword("")}>
        重設密碼
      </button>
      {active ? (
        <ArmButton className="btn" label="停用帳號" armedLabel="確定停用" disabled={access.isPending}
          onConfirm={() => send({ is_active: false }, "的帳號已停用")} />
      ) : (
        <button type="button" className="btn" disabled={access.isPending} onClick={() => void send({ is_active: true }, "的帳號已啟用")}>
          啟用帳號
        </button>
      )}
    </div>
  );
}
