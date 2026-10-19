import { FormEvent, useState } from "react";

import { useChangeMyPassword } from "@/api/hooks";
import { swapToken } from "@/api/client";
import { Field } from "@/components/Field";
import { Toolbar } from "@/components/Toolbar";
import { apiErrorText } from "@/components/workbench/errors";
import { toast } from "@/components/workbench/toast";
import { changeProblem } from "@/lib/password";

/**
 * 自己改密碼(側欄帳號旁的「密碼」;owner 2026-10-19:「登入後沒有修改密碼的選項」)。
 * 改好之後這個帳號在別台都要重新登入;這一台換上伺服器給的新 token 繼續用。規則在 lib/password,伺服器也擋。
 */
export function PasswordPage() {
  const change = useChangeMyPassword();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [tried, setTried] = useState(false);
  const problem = changeProblem(current, next, again);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setTried(true);
    if (problem || change.isPending) return;
    try {
      const { token } = await change.mutateAsync({ current_password: current, new_password: next });
      swapToken(token);
      setCurrent("");
      setNext("");
      setAgain("");
      setTried(false);
      toast("密碼已改好,其他裝置要重新登入", "ok");
    } catch (err) {
      toast(apiErrorText(err), "err");
    }
  }

  return (
    <div className="page">
      <Toolbar title="改密碼" />
      <div className="entry-body">
        <form className="pw-form" onSubmit={submit}>
          <Field label="目前的密碼">
            <input type="password" autoComplete="current-password" value={current}
              onChange={(e) => setCurrent(e.target.value)} />
          </Field>
          <Field label="新密碼">
            <input type="password" autoComplete="new-password" value={next}
              onChange={(e) => setNext(e.target.value)} />
          </Field>
          <Field label="再輸入一次" error={tried && problem ? problem : undefined}>
            <input type="password" autoComplete="new-password" value={again}
              onChange={(e) => setAgain(e.target.value)} />
          </Field>
          <div className="pw-actions">
            <button type="submit" className="btn primary" disabled={change.isPending}>
              儲存
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
