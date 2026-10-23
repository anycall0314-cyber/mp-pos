import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/api/client";
import { useLegacyCandidates } from "@/api/hooks";
import type { LegacyMemberRow } from "@/api/types";
import { useCurrentUser } from "@/auth/AuthContext";
import { Banner } from "@/components/Banner";
import { refreshMemberHistory } from "@/lib/memberUrl";
import { errorText } from "@/lib/errorText";

/**
 * 會員名單右邊(管理員):「可能是同一人」的舊 POS 會員,按「確認對照」把他的舊紀錄掛到這一位。
 * 原本放在消費紀錄底下;消費紀錄分頁改成只看、不給任何操作之後搬到這裡(owner 2026-10-21)。
 * 對照完開著的消費紀錄分頁換成這一位重新讀。
 */
export function LegacyLinkCandidates({ memberId }: { memberId: number }) {
  const isAdmin = useCurrentUser()?.profile?.role === "tenant_admin";
  const qc = useQueryClient();
  const candidates = useLegacyCandidates(memberId, isAdmin);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function link(c: LegacyMemberRow) {
    setError("");
    setBusy(true);
    try {
      await api(`/legacy/members/${c.id}/link/`, {
        method: "POST",
        body: JSON.stringify({
          member: memberId,
          method: c.reason === "電話相同" ? "phone" : "name",
        }),
      });
      qc.invalidateQueries({ queryKey: ["legacy-history"] });
      qc.invalidateQueries({ queryKey: ["legacy-candidates"] });
      refreshMemberHistory(memberId);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  const rows = candidates.data ?? [];
  if (!isAdmin || (rows.length === 0 && !error)) return null;

  return (
    <div style={{ marginTop: 24 }}>
      <h4 className="pc-detail-title">舊 POS 可能同一人</h4>
      {error && <Banner kind="error" message={error} />}
      <div className="legacy-links">
        {rows.map((c) => (
          <div key={c.id} className="legacy-candidate">
            <span>
              {c.source_member_id} {c.name} {c.phone}
              <span className="legacy-sub">
                {" "}
                {c.reason} · {c.documents} 張 · ${c.net_amount?.display}
              </span>
            </span>
            <button className="btn small" disabled={busy} onClick={() => link(c)}>
              確認對照
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
