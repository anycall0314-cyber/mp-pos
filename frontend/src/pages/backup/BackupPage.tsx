import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api } from "@/api/client";
import { useCurrentUser } from "@/auth/AuthContext";
import { Banner } from "@/components/Banner";
import { Toolbar } from "@/components/Toolbar";

import { sha256File } from "./sha256";

/**
 * 設定 → 備份與還原(公司管理員)
 *
 * 一次備份 = 這家公司全部門市 + 附件,不看畫面上選哪一家店。
 * 狀態照實寫:伺服器「可下載」、瀏覽器「已開始下載」都不代表檔案已經在硬碟裡,
 * 要重新選取檔案核對過才算「已驗證本機檔案」。
 */

interface BackupJob {
  id: number;
  kind: "manual" | "safety";
  status: "queued" | "running" | "verified" | "failed" | "expired";
  status_label: string;
  created_at: string;
  snapshot_at: string | null;
  expires_at: string | null;
  file_size: number;
  file_sha256: string;
  summary: { rows?: number; attachments?: number; warehouses?: string[] };
  error: string;
  requested_by: string;
  download_started_at: string | null;
  local_verified_at: string | null;
}

interface RestoreReport {
  ok?: boolean;
  problems?: string[];
  warnings?: string[];
  source?: {
    company: string;
    snapshot_at: string;
    warehouses: string[];
    rows: number;
    attachments: number;
  };
  target?: { company: string; rows: number; warehouses: string[] };
}

interface RestoreJob {
  id: number;
  status:
    | "prechecked"
    | "rejected"
    | "queued"
    | "running"
    | "done"
    | "failed"
    | "needs_attention"
    | "cancelled";
  status_label: string;
  created_at: string;
  finished_at: string | null;
  report: RestoreReport;
  result: { rows?: number; snapshot_at?: string; profiles_without_store?: number };
  error: string;
  confirm_word: string;
}

interface Overview {
  company: string;
  warehouses: string[];
  key: {
    exists: boolean;
    fingerprint: string;
    acknowledged: boolean;
    readable: boolean;
  };
  last_backup: BackupJob | null;
  last_restore: RestoreJob | null;
  maintenance: {
    active: boolean;
    reason: string;
    restore_job: number | null;
    restore_status: string;
    can_cancel: boolean;
    can_release: boolean;
  };
  retention_hours: number;
}

const BASE = import.meta.env.VITE_API_BASE || "/api/v1";

function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("zh-TW", { hour12: false });
}

function sizeText(bytes: number): string {
  if (!bytes) return "—";
  if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024)} KB`;
  return `${Math.ceil(bytes / 1024 / 1024)} MB`;
}

// crypto.randomUUID 只在 https / localhost 才有;店裡用區網 IP 連線時要有退路
function requestKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function message(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export function BackupPage() {
  const qc = useQueryClient();
  const role = useCurrentUser()?.profile?.role;
  const isAdmin = role === "tenant_admin";

  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [credential, setCredential] = useState("");
  const [busy, setBusy] = useState(false);
  const verifyInput = useRef<HTMLInputElement>(null);
  const verifyJob = useRef<number | null>(null);

  const [restoreFile, setRestoreFile] = useState<File | null>(null);
  const [restoreCredential, setRestoreCredential] = useState("");
  const [confirmText, setConfirmText] = useState("");

  const overview = useQuery({
    queryKey: ["backup-overview"],
    queryFn: () => api<Overview>("/backup/overview/"),
    enabled: isAdmin,
    // 維護中(還原排隊 / 進行)要一直看,結束時畫面才會自己解開
    refetchInterval: (q) => (q.state.data?.maintenance.active ? 3000 : false),
  });
  const jobs = useQuery({
    queryKey: ["backup-jobs"],
    queryFn: () => api<{ results: BackupJob[] }>("/backup/jobs/"),
    enabled: isAdmin,
    // 有工作在跑就每 3 秒看一次;切到別頁、換一台電腦回來,看到的是同一份工作
    refetchInterval: (q) =>
      q.state.data?.results.some(
        (j) => j.status === "queued" || j.status === "running",
      )
        ? 3000
        : false,
  });
  const restores = useQuery({
    queryKey: ["backup-restores"],
    queryFn: () => api<{ results: RestoreJob[] }>("/backup/restores/"),
    enabled: isAdmin,
    refetchInterval: (q) =>
      q.state.data?.results.some(
        (j) => j.status === "queued" || j.status === "running",
      )
        ? 3000
        : false,
  });

  // 還原結束的那一刻,整個系統手上的資料都是舊的(每一筆的內部編號都換了):
  // 全部重新抓,不只這一頁。
  const restoring = !!restores.data?.results.some(
    (j) => j.status === "queued" || j.status === "running",
  );
  const wasRestoring = useRef(false);
  useEffect(() => {
    if (wasRestoring.current && !restoring) qc.invalidateQueries();
    wasRestoring.current = restoring;
  }, [restoring, qc]);

  if (!isAdmin) {
    return (
      <div className="page">
        <Toolbar title="備份與還原" />
        <div className="entry-body">
          <Banner kind="error" message="需要公司管理員權限" />
        </div>
      </div>
    );
  }

  function refresh() {
    qc.invalidateQueries({ queryKey: ["backup-overview"] });
    qc.invalidateQueries({ queryKey: ["backup-jobs"] });
    qc.invalidateQueries({ queryKey: ["backup-restores"] });
  }

  async function run(action: () => Promise<void>) {
    setError("");
    setNotice("");
    setBusy(true);
    try {
      await action();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
      refresh();
    }
  }

  const createKey = () =>
    run(async () => {
      const r = await api<{ credential: string }>("/backup/key/", {
        method: "POST",
      });
      setCredential(r.credential);
    });

  const revealKey = () =>
    run(async () => {
      const r = await api<{ credential: string }>("/backup/key/reveal/", {
        method: "POST",
      });
      setCredential(r.credential);
    });

  const acknowledgeKey = () =>
    run(async () => {
      await api("/backup/key/acknowledge/", { method: "POST" });
      setCredential("");
    });

  const startBackup = () =>
    run(async () => {
      await api<BackupJob>("/backup/jobs/", {
        method: "POST",
        body: JSON.stringify({ idempotency_key: requestKey() }),
      });
    });

  const download = (job: BackupJob) =>
    run(async () => {
      const r = await api<{ ticket: string }>(
        `/backup/jobs/${job.id}/download-ticket/`,
        { method: "POST" },
      );
      // 用一般下載讓瀏覽器直接把檔案存到硬碟(不整包讀進記憶體)
      window.location.href = `${BASE}/backup/download/?ticket=${encodeURIComponent(r.ticket)}`;
    });

  function pickFileToVerify(job: BackupJob) {
    verifyJob.current = job.id;
    verifyInput.current?.click();
  }

  const verifyPicked = (file: File | undefined) =>
    run(async () => {
      if (!file || verifyJob.current == null) return;
      const sha256 = await sha256File(file, (p) => setNotice(`核對中 ${p}%`));
      setNotice("");
      await api(`/backup/jobs/${verifyJob.current}/verify-local/`, {
        method: "POST",
        body: JSON.stringify({ sha256, size: file.size }),
      });
      setNotice("檔案完整");
    });

  const uploadRestore = () =>
    run(async () => {
      if (!restoreFile) return;
      const form = new FormData();
      form.append("file", restoreFile);
      if (restoreCredential.trim()) form.append("credential", restoreCredential.trim());
      await api<RestoreJob>("/backup/restores/", { method: "POST", body: form });
      setRestoreFile(null);
      setRestoreCredential("");
      setConfirmText("");
    });

  const confirmRestore = (job: RestoreJob) =>
    run(async () => {
      await api(`/backup/restores/${job.id}/confirm/`, {
        method: "POST",
        body: JSON.stringify({ confirm: confirmText }),
      });
      setConfirmText("");
    });

  const cancelRestore = (id: number) =>
    run(async () => {
      await api(`/backup/restores/${id}/cancel/`, { method: "POST" });
    });

  const releaseMaintenance = () =>
    run(async () => {
      await api("/backup/maintenance/release/", { method: "POST" });
    });

  const ov = overview.data;
  const jobRows = (jobs.data?.results ?? []).filter((j) => j.kind === "manual");
  const safetyRows = (jobs.data?.results ?? []).filter((j) => j.kind === "safety");
  const restoreRows = restores.data?.results ?? [];
  const pending = restoreRows.find((r) => r.status === "prechecked");
  const interrupted = restoreRows.find((r) => r.status === "needs_attention");
  const loadError = overview.error ?? jobs.error ?? restores.error;
  const working = jobRows.some((j) => j.status === "queued" || j.status === "running");
  const keyReady = !!ov?.key.exists && ov.key.readable;

  return (
    <div className="page">
      <Toolbar title="備份與還原" />
      <div className="entry-body backup-page">
        {error && <Banner kind="error" message={error} />}
        {loadError && <Banner kind="error" message={`讀取失敗:${message(loadError)}`} />}
        {notice && <Banner kind="success" message={notice} />}
        {ov?.maintenance.active && (
          <Banner kind="error" message={`維護中:${ov.maintenance.reason}`} />
        )}

        <section className="backup-card">
          <div className="section-head">{ov?.company ?? "—"}</div>
          <dl className="backup-facts">
            <dt>包含門市</dt>
            <dd>{ov?.warehouses.join("、") || "—"}</dd>
            <dt>最近備份</dt>
            <dd>{when(ov?.last_backup?.snapshot_at)}</dd>
            <dt>最近還原</dt>
            <dd>{when(ov?.last_restore?.finished_at)}</dd>
          </dl>
        </section>

        <section className="backup-card">
          <div className="section-head">復原憑證</div>
          {!ov?.key.exists ? (
            <button className="btn primary" onClick={createKey} disabled={busy}>
              產生憑證
            </button>
          ) : (
            <dl className="backup-facts">
              <dt>核對碼</dt>
              <dd>{ov.key.fingerprint}</dd>
            </dl>
          )}
          {ov?.key.exists && !ov.key.readable && (
            <Banner kind="error" message="伺服器讀不到憑證,請到還原區輸入憑證" />
          )}
          {credential ? (
            <div className="backup-credential">
              <code>{credential}</code>
              <p>抄下來,跟硬碟分開放。伺服器壞掉時只有它能解開備份。</p>
              <button className="btn primary" onClick={acknowledgeKey} disabled={busy}>
                抄好了
              </button>
            </div>
          ) : (
            keyReady && (
              <button className="btn" onClick={revealKey} disabled={busy}>
                再看一次
              </button>
            )
          )}
        </section>

        <section className="backup-card">
          <div className="section-head">備份</div>
          <button
            className="btn primary"
            onClick={startBackup}
            disabled={busy || working || !keyReady || ov?.maintenance.active}
          >
            {working ? "備份中…" : "備份全部門市"}
          </button>
          <input
            ref={verifyInput}
            type="file"
            accept=".mppos-backup"
            style={{ display: "none" }}
            onChange={(e) => {
              verifyPicked(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
          <table className="line-table backup-table">
            <thead>
              <tr>
                <th>資料時間</th>
                <th>狀態</th>
                <th className="num">大小</th>
                <th>下載期限</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {jobRows.map((j) => (
                <tr key={j.id}>
                  <td>{when(j.snapshot_at ?? j.created_at)}</td>
                  <td>
                    {j.status_label}
                    {j.error && <div className="backup-sub backup-bad">{j.error}</div>}
                    {j.download_started_at && (
                      <div className="backup-sub">
                        已開始下載 {when(j.download_started_at)}
                      </div>
                    )}
                    {j.local_verified_at && (
                      <div className="backup-sub backup-good">
                        已驗證本機檔案 {when(j.local_verified_at)}
                      </div>
                    )}
                  </td>
                  <td className="num">{sizeText(j.file_size)}</td>
                  <td>{j.status === "verified" ? when(j.expires_at) : "—"}</td>
                  <td className="backup-actions">
                    {j.status === "verified" && (
                      <button className="btn small" onClick={() => download(j)} disabled={busy}>
                        下載檔案
                      </button>
                    )}
                    {j.file_sha256 && (
                      <button
                        className="btn small"
                        onClick={() => pickFileToVerify(j)}
                        disabled={busy}
                      >
                        驗證檔案
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {jobRows.length === 0 && (
                <tr>
                  <td colSpan={5} className="backup-sub">
                    尚無備份
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </section>

        <section className="backup-card">
          <div className="section-head">還原</div>
          {ov?.maintenance.can_cancel && ov.maintenance.restore_job != null && (
            <div className="backup-report">
              <div className="backup-sub">已排入還原,全公司暫停操作</div>
              <button
                className="btn"
                onClick={() => cancelRestore(ov.maintenance.restore_job as number)}
                disabled={busy}
              >
                取消還原
              </button>
            </div>
          )}
          {ov?.maintenance.can_release && (
            <div className="backup-report">
              {interrupted && <Banner kind="error" message={interrupted.error} />}
              <button className="btn" onClick={releaseMaintenance} disabled={busy}>
                解除維護
              </button>
            </div>
          )}
          {!pending && (
            <div className="backup-upload">
              <input
                type="file"
                accept=".mppos-backup"
                onChange={(e) => setRestoreFile(e.target.files?.[0] ?? null)}
              />
              <input
                value={restoreCredential}
                onChange={(e) => setRestoreCredential(e.target.value)}
                placeholder={keyReady ? "其他憑證(選填)" : "復原憑證 MP-XXXX-…"}
              />
              <button
                className="btn"
                onClick={uploadRestore}
                disabled={busy || !restoreFile || ov?.maintenance.active}
              >
                上傳檢查
              </button>
            </div>
          )}
          {pending && pending.report.source && (
            <div className="backup-report">
              <dl className="backup-facts">
                <dt>備份來源</dt>
                <dd>{pending.report.source.company}</dd>
                <dt>備份時間</dt>
                <dd>{when(pending.report.source.snapshot_at)}</dd>
                <dt>包含門市</dt>
                <dd>{pending.report.source.warehouses.join("、")}</dd>
                <dt>資料筆數</dt>
                <dd>
                  {pending.report.source.rows}(附件 {pending.report.source.attachments})
                </dd>
                <dt>會被取代</dt>
                <dd>
                  {pending.report.target?.company} 全部門市,目前{" "}
                  {pending.report.target?.rows} 筆
                </dd>
              </dl>
              {(pending.report.warnings ?? []).map((w) => (
                <div key={w} className="backup-sub">
                  {w}
                </div>
              ))}
              <div className="backup-upload">
                <input
                  value={confirmText}
                  onChange={(e) => setConfirmText(e.target.value)}
                  placeholder={`輸入「${pending.confirm_word}」`}
                />
                <button className="btn" onClick={() => cancelRestore(pending.id)} disabled={busy}>
                  取消還原
                </button>
                <button
                  className="btn primary"
                  onClick={() => confirmRestore(pending)}
                  disabled={busy || confirmText.trim() !== pending.confirm_word}
                >
                  確認還原
                </button>
              </div>
            </div>
          )}
          <table className="line-table backup-table">
            <thead>
              <tr>
                <th>時間</th>
                <th>狀態</th>
                <th>備份時間點</th>
              </tr>
            </thead>
            <tbody>
              {restoreRows
                .filter((r) => r.status !== "prechecked")
                .map((r) => (
                  <tr key={r.id}>
                    <td>{when(r.finished_at ?? r.created_at)}</td>
                    <td>
                      {r.status_label}
                      {(!!r.error || (r.report.problems?.length ?? 0) > 0) && (
                        <div className="backup-sub backup-bad">
                          {r.error || r.report.problems?.join(";")}
                        </div>
                      )}
                    </td>
                    <td>{when(r.result.snapshot_at ?? r.report.source?.snapshot_at)}</td>
                  </tr>
                ))}
              {safetyRows.map((j) => (
                <tr key={`s${j.id}`}>
                  <td>{when(j.created_at)}</td>
                  <td>
                    還原前安全備份:{j.status_label}
                    {j.error && <div className="backup-sub backup-bad">{j.error}</div>}
                  </td>
                  <td className="backup-actions">
                    {j.status === "verified" && (
                      <button className="btn small" onClick={() => download(j)} disabled={busy}>
                        下載檔案
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
    </div>
  );
}
