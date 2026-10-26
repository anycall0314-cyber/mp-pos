import { FormEvent, useState } from "react";

import { useDeleteStaffRole, useSaveStaffRole } from "@/api/hooks";
import type { StaffAccountsResponse, StaffRole } from "@/api/types";
import { Banner } from "@/components/Banner";
import { Field } from "@/components/Field";
import { PaneForm } from "@/components/PaneForm";
import { ArmButton } from "@/components/workbench/ArmButton";
import { apiErrorText } from "@/components/workbench/errors";
import { useArm } from "@/components/workbench/useArm";
import { changed, leaveArmed, leaveDraft } from "@/lib/draftGuard";
import { changedFlags, type Flags, roleFlags } from "@/lib/staffAccess";

import { AbilityChecklist } from "./AbilityChecklist";

/**
 * 身份別的新增 / 編輯整頁(owner 2026-10-27)。改勾選,這個身份的人一起變(帳號自己的例外照舊)。
 * 新增可以先照一個現有的身份別,再改幾項。還有人在用的刪不掉。
 */
export function StaffRoleForm({
  data,
  initial,
  onClose,
}: {
  data: StaffAccountsResponse;
  /** 編輯哪一個;null = 新增 */
  initial: StaffRole | null;
  onClose: (saved?: string) => void;
}) {
  const start = { name: initial?.name ?? "", flags: roleFlags(data.abilities, initial) };
  const [state, setState] = useState<{ name: string; flags: Flags }>(start);
  const [base] = useState(start);
  const [copyFrom, setCopyFrom] = useState<number | "">("");
  const [error, setError] = useState<string | null>(null);
  const save = useSaveStaffRole();
  const remove = useDeleteStaffRole();
  const arm = useArm();
  const dirty = changed(state, base);
  const busy = save.isPending || remove.isPending;

  function back() {
    leaveDraft(dirty, arm, "back", () => onClose());
  }

  function copy(id: number | "") {
    setCopyFrom(id);
    const source = data.roles.find((r) => r.id === id) ?? null;
    setState((s) => ({ ...s, flags: roleFlags(data.abilities, source) }));
  }

  async function submit(e?: FormEvent) {
    e?.preventDefault();
    setError(null);
    const name = state.name.trim();
    if (!name) return setError("身份別名稱要填");
    try {
      if (!initial) {
        // 新的從預設開始:只送跟預設不一樣的(照哪個身份別開始的,勾選已經換成它的了)
        await save.mutateAsync({ name, abilities: changedFlags(roleFlags(data.abilities, null), state.flags) });
        onClose(`已新增 ${name}`);
        return;
      }
      const body: Parameters<typeof save.mutateAsync>[0] = { id: initial.id };
      if (name !== initial.name) body.name = name;
      const flags = changedFlags(roleFlags(data.abilities, initial), state.flags);
      if (Object.keys(flags).length) body.abilities = flags;
      if (Object.keys(body).length === 1) return onClose();
      await save.mutateAsync(body);
      onClose(`已儲存 ${name}`);
    } catch (err) {
      setError(apiErrorText(err));
    }
  }

  async function del() {
    if (!initial) return;
    setError(null);
    try {
      await remove.mutateAsync(initial.id);
      onClose(`已刪除 ${initial.name}`);
    } catch (err) {
      setError(apiErrorText(err));
    }
  }

  return (
    <PaneForm
      title={initial ? initial.name : "新增身份別"}
      onBack={back}
      leaveArmed={leaveArmed(arm.armed, "back")}
      busy={busy}
      footer={
        <>
          {initial && (
            <ArmButton
              className="btn danger"
              label="刪除身份別"
              armedLabel="確定刪除"
              disabled={busy || initial.accounts > 0}
              title={initial.accounts > 0 ? `還有 ${initial.accounts} 個帳號是這個身份別` : undefined}
              onConfirm={del}
            />
          )}
          <button className="btn primary" type="button" onClick={() => void submit()} disabled={busy}>
            {save.isPending ? "儲存中…" : "儲存"}
          </button>
        </>
      }
    >
      {error && <Banner kind="error" message={error} />}
      <form className="staff-form" onSubmit={submit}>
        <div className="staff-form-grid">
          <Field label="名稱" required>
            <input
              value={state.name}
              maxLength={20}
              autoFocus={!initial}
              onChange={(e) => setState((s) => ({ ...s, name: e.target.value }))}
            />
          </Field>
          {!initial && data.roles.length > 0 && (
            <Field label="照哪個開始">
              <select value={copyFrom} onChange={(e) => copy(e.target.value ? Number(e.target.value) : "")}>
                <option value="">預設</option>
                {data.roles.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
              </select>
            </Field>
          )}
        </div>
      </form>
      <AbilityChecklist
        items={data.abilities}
        values={state.flags}
        onChange={(flags) => setState((s) => ({ ...s, flags }))}
        disabled={busy}
      />
    </PaneForm>
  );
}
