import { useEffect, useRef, useState } from "react";
import wasmUrl from "zxing-wasm/reader/zxing_reader.wasm?url";

import { countPhoneCall, CountPhoneError, type PhoneCountState } from "@/api/countPhone";
import { newId } from "@/lib/newId";
import { BARCODE_FORMATS, createScanGate, pileQty, tapText } from "@/lib/phoneCount";
import { errorText } from "@/lib/errorText";

/**
 * 手機走動盤點(`/m/count#憑證`;owner 2026-10-15「盤點要有手機可以配對掃，方便走動盤點」)。不用登入、不用裝 App。
 *
 * 只能對「電腦上那一張盤點單」刷碼:配件每刷一個 +1(大家刷的加在一起)、機器記那一台、系統不認得的在「配件」模式記成沒對到的碼。
 * 看得到自己刷了什麼與那個品項大家合起來數到幾個;**看不到帳上數量**,不能送出、核准。
 * 相機一直對著同一個條碼只算一下,拿開再出現才算下一下(`createScanGate`)。藍牙掃描槍接手機也可以(當成打字,刷進下面那一格)。
 */

const DEVICE_KEY = "mp-pos-count-device";
type Mode = "accessory" | "phone";
/** 斷線時同一個動作自動重送幾次(同一個編號:伺服器做過就不再做,不會多算) */
const RETRIES = 3;

/** 一個要送給伺服器的動作:帶自己的編號(複審 P0:回應在路上斷線,重送不能多 +1) */
interface Job {
  op: string;
  action: "tap" | "pile" | "undo";
  body: { code?: string; mode?: Mode; n?: number; target?: number };
}

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** 這支手機自己的識別:重新整理還是同一支(別支手機拿同一個 QR Code 連不進來)。 */
function deviceId(): string {
  for (const store of [() => localStorage, () => sessionStorage]) {
    try {
      const box = store();
      const saved = box.getItem(DEVICE_KEY);
      if (saved) return saved;
      const fresh = newId();
      box.setItem(DEVICE_KEY, fresh);
      return fresh;
    } catch {
      /* 這一種儲存不能用,試下一種 */
    }
  }
  return newId();
}

interface Detector {
  detect(source: HTMLVideoElement): Promise<{ rawValue: string }[]>;
}

/** 手機自己會讀條碼(Android 的 Chrome)就用它;不會(iPhone)就用打包進來的讀條碼程式(核心檔放在自己網站上)。 */
async function makeDetector(): Promise<Detector> {
  const native = (window as unknown as { BarcodeDetector?: { new (o: object): Detector; getSupportedFormats?: () => Promise<string[]> } }).BarcodeDetector;
  if (native?.getSupportedFormats) {
    try {
      const formats = (await native.getSupportedFormats()).filter((f) => BARCODE_FORMATS.includes(f));
      if (formats.includes("code_128")) return new native({ formats });
    } catch {
      /* 退到打包進來的 */
    }
  }
  const mod = await import("barcode-detector/ponyfill");
  mod.prepareZXingModule({ overrides: { locateFile: (path: string, prefix: string) => (path.endsWith(".wasm") ? wasmUrl : prefix + path) } });
  return new mod.BarcodeDetector({ formats: BARCODE_FORMATS as never[] });
}

export function PhoneCountPage() {
  const token = useRef(window.location.hash.replace(/^#/, "")).current;
  const device = useRef(deviceId()).current;
  const [info, setInfo] = useState<PhoneCountState | null>(null);
  const infoRef = useRef<PhoneCountState | null>(null);
  infoRef.current = info;
  const [problem, setProblem] = useState<{ text: string; gone: boolean } | null>(null);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [mode, setMode] = useState<Mode>("accessory");
  const [typed, setTyped] = useState("");
  const [pile, setPile] = useState("");
  const [camera, setCamera] = useState(false);
  const [busy, setBusy] = useState(false);
  /** 斷線、重送也沒成功的動作:還不確定伺服器有沒有記到,按「重送」用同一個編號再送 */
  const [pending, setPending] = useState<Job[]>([]);
  // 當下的一份(排隊中的動作要馬上知道有沒有還沒確定的,不能等畫面重畫)
  const pendingNow = useRef<Job[]>([]);
  const holdPending = (next: Job[]) => {
    pendingNow.current = next;
    setPending(next);
  };
  const modeRef = useRef<Mode>("accessory");
  modeRef.current = mode;
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const queue = useRef<Promise<void>>(Promise.resolve());
  const gate = useRef(createScanGate());
  const audio = useRef<AudioContext | null>(null);
  const goneRef = useRef(false);
  goneRef.current = !!problem?.gone;

  function feedback(ok: boolean) {
    try {
      navigator.vibrate?.(ok ? 60 : [80, 60, 80]);
    } catch {
      /* 沒有震動 */
    }
    const ctx = audio.current;
    if (!ctx) return;
    try {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.frequency.value = ok ? 1200 : 300;
      gain.gain.value = 0.15;
      osc.connect(gain).connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + (ok ? 0.08 : 0.25));
    } catch {
      /* 沒有聲音 */
    }
  }

  function wakeAudio() {
    try {
      audio.current ??= new AudioContext();
      void audio.current.resume();
    } catch {
      /* 沒有聲音 */
    }
  }

  function fail(e: unknown) {
    const err = e instanceof CountPhoneError ? e : new CountPhoneError("沒有成功,請再試一次", "network");
    if (["gone", "expired", "taken"].includes(err.code)) {
      setProblem({ text: err.message, gone: true });
      stopCamera();
    } else {
      setNote({ ok: false, text: err.message });
      feedback(false);
    }
  }

  /** 排隊一個一個送(連刷的時候照順序,不會兩個同時在路上) */
  function enqueue(job: () => Promise<void>) {
    queue.current = queue.current.then(job).catch(() => undefined);
  }

  /** 送一個動作:斷線就用同一個編號自動重送;伺服器做過的會當成已經做了,不會做兩次 */
  async function run(job: Job): Promise<PhoneCountState> {
    for (let attempt = 0; ; attempt++) {
      try {
        return await countPhoneCall(token, device, job.action, { ...job.body, op: job.op });
      } catch (e) {
        if (!(e instanceof CountPhoneError) || e.code !== "network" || attempt >= RETRIES - 1) throw e;
        await wait(800 * 2 ** attempt);
      }
    }
  }

  function submitJob(job: Job) {
    if (goneRef.current) return;
    enqueue(async () => {
      // 前面有還沒確定的動作:這一個排在它後面、等按「重送」一起照順序送(複審第二輪 P0:不能超車,收回會收到別的那一下)
      // 重送時也一樣:前一下又沒送到,後面的就跟著排回去,不會自己先送出去
      if (pendingNow.current.length > 0) {
        holdPending([...pendingNow.current, job]);
        setNote({ ok: false, text: `還沒確定 ${pendingNow.current.length} 下,先按重送` });
        return;
      }
      setBusy(true);
      try {
        const next = await run(job);
        setInfo(next);
        const last = next.taps[0];
        setNote({ ok: true, text: job.action === "undo" ? "收回了" : last ? `${last.name} ${tapText(last)}`.trim() : job.body.code ?? "" });
        setPile("");
        feedback(true);
      } catch (e) {
        if (e instanceof CountPhoneError && e.code === "network") {
          holdPending([...pendingNow.current, job]);
          setNote({ ok: false, text: "連不上,剛剛那一下還不確定" });
          feedback(false);
        } else {
          fail(e);
        }
      } finally {
        setBusy(false);
      }
    });
  }

  function send(code: string) {
    const text = code.trim();
    if (!text) return;
    const op = newId();
    submitJob({ op, action: "tap", body: { code: text, mode: modeRef.current } });
  }

  /** 「這一堆幾個」「收回這一下」:帶手機看到的最後一下(伺服器的最後一下不是它就擋,不會收錯) */
  function act(action: "pile" | "undo", n?: number) {
    const target = infoRef.current?.taps.find((x) => !x.undone)?.id;
    submitJob({ op: newId(), action, body: action === "pile" ? { n, target } : { target } });
  }

  /** 重送還不確定的那幾下(同一個編號、照原本的順序);中間又失敗的那一下與後面的留著 */
  function resend() {
    const jobs = pendingNow.current;
    holdPending([]);
    for (const job of jobs) submitJob(job);
  }

  /** 掃碼那一下:連上(綁這支手機)。沒連上要講原因、可以重試 —— 不能一直停在「連線中」 */
  const [claimError, setClaimError] = useState("");
  function claim() {
    setClaimError("");
    countPhoneCall(token, device, "claim").then(setInfo, (e) => {
      if (e instanceof CountPhoneError && ["gone", "expired", "taken"].includes(e.code)) fail(e);
      else setClaimError(errorText(e));
    });
  }

  useEffect(() => {
    document.title = "手機盤點";
    if (!token) {
      setProblem({ text: "請用手機相機掃電腦盤點單上的 QR Code", gone: true });
      return;
    }
    claim();
    // 只在開頁時連一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 每 10 秒看一次這次配對還在不在(電腦按了結束、單子送出了,這裡要停)
  useEffect(() => {
    if (!info || problem?.gone) return;
    const handle = window.setInterval(() => {
      countPhoneCall(token, device, "state").then(setInfo, (e) => {
        if (e instanceof CountPhoneError && ["gone", "expired", "taken"].includes(e.code)) fail(e);
      });
    }, 10000);
    return () => window.clearInterval(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [!!info, problem?.gone]);

  function stopCamera() {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setCamera(false);
  }

  async function startCamera() {
    wakeAudio();
    setNote(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false });
      streamRef.current = stream;
      setCamera(true);
    } catch {
      setNote({ ok: false, text: "開不了相機:請允許這個網頁使用相機,或在下面那一格打碼" });
    }
  }

  // 相機開著:每 120 毫秒讀一次條碼
  useEffect(() => {
    if (!camera) return;
    const video = videoRef.current;
    if (!video || !streamRef.current) return;
    video.srcObject = streamRef.current;
    void video.play().catch(() => undefined);
    let stopped = false;
    let handle = 0;
    let detector: Detector | null = null;
    let lock: { release: () => Promise<void> } | null = null;
    (navigator as unknown as { wakeLock?: { request: (t: string) => Promise<typeof lock> } }).wakeLock
      ?.request("screen").then((l) => { lock = l; }, () => undefined);
    const tick = async () => {
      if (stopped) return;
      try {
        detector ??= await makeDetector();
        if (video.readyState >= 2) {
          const found = await detector.detect(video);
          const code = found[0]?.rawValue?.trim();
          if (code && gate.current(code, performance.now())) send(code);
        }
      } catch {
        /* 這一格讀不到,下一格再試 */
      }
      if (!stopped) handle = window.setTimeout(tick, 120);
    };
    handle = window.setTimeout(tick, 120);
    return () => {
      stopped = true;
      window.clearTimeout(handle);
      void lock?.release().catch(() => undefined);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [camera]);

  useEffect(() => () => stopCamera(), []);

  async function finish() {
    stopCamera();
    try {
      await countPhoneCall(token, device, "finish");
    } catch {
      /* 已經結束了也一樣 */
    }
    setProblem({ text: "這支手機盤完了。要再盤,請在電腦按「手機盤點」再掃一次", gone: true });
  }

  if (problem?.gone) {
    return (
      <div className="pc-page">
        <div className="pc-gone">{problem.text}</div>
      </div>
    );
  }
  if (!info) {
    return (
      <div className="pc-page">
        <div className="pc-gone">{claimError || "連線中…"}</div>
        {claimError && (
          <button type="button" className="pc-btn" onClick={claim}>
            重試
          </button>
        )}
      </div>
    );
  }
  // 「收回這一下」「這一堆幾個」對的是這支手機最後一下還沒收回的(跟伺服器同一個規則)
  const last = info.taps.find((t) => !t.undone);
  const canPile = last && !last.undone && last.kind === "line";
  return (
    <div className="pc-page">
      <div className="pc-head">
        <div className="pc-title">
          {info.no} {info.warehouse}
          <span className="pc-who">{info.label}</span>
        </div>
        <button type="button" className="pc-btn" onClick={() => void finish()}>
          結束
        </button>
      </div>
      <div className="pc-modes" role="group" aria-label="刷到不認得的碼時">
        {(["accessory", "phone"] as const).map((m) => (
          <button key={m} type="button" className={`pc-mode${mode === m ? " on" : ""}`} aria-pressed={mode === m} onClick={() => setMode(m)}>
            {m === "accessory" ? "配件" : "手機"}
          </button>
        ))}
      </div>
      {camera ? (
        <div className="pc-cam">
          <video ref={videoRef} playsInline muted autoPlay />
          <div className="pc-aim" aria-hidden="true" />
          <button type="button" className="pc-btn pc-cam-off" onClick={stopCamera}>
            關相機
          </button>
        </div>
      ) : (
        <button type="button" className="pc-btn pc-cam-on" onClick={() => void startCamera()}>
          開相機
        </button>
      )}
      <form
        className="pc-type"
        onSubmit={(e) => {
          e.preventDefault();
          wakeAudio();
          send(typed);
          setTyped("");
        }}
      >
        <input
          id="pc-code"
          type="text"
          inputMode="text"
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          placeholder="打碼 / 藍牙掃描槍"
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
        />
        <button type="submit" className="pc-btn" disabled={!typed.trim()}>
          送出
        </button>
      </form>
      {note && <div className={`pc-note ${note.ok ? "ok" : "bad"}`}>{note.text}</div>}
      {pending.length > 0 && (
        <div className="pc-pending">
          <span>還沒確定 {pending.length} 下</span>
          <button type="button" className="pc-btn" disabled={busy} onClick={resend}>
            重送
          </button>
        </div>
      )}
      {last && !last.undone && (
        <div className="pc-last">
          {canPile && (
            <form
              className="pc-pile"
              onSubmit={(e) => {
                e.preventDefault();
                const n = pileQty(pile);
                if (n !== null) act("pile", n);
              }}
            >
              <label htmlFor="pc-pile">這一堆幾個</label>
              <input id="pc-pile" type="text" inputMode="numeric" value={pile} onChange={(e) => setPile(e.target.value)} />
              <button type="submit" className="pc-btn" disabled={pileQty(pile) === null || busy}>
                改
              </button>
            </form>
          )}
          <button type="button" className="pc-btn pc-undo" disabled={busy} onClick={() => act("undo")}>
            收回這一下
          </button>
        </div>
      )}
      <ul className="pc-list">
        {info.taps.map((t) => (
          <li key={t.id} className={t.undone ? "undone" : ""}>
            <span className="pc-name">{t.name}</span>
            <span className="pc-qty">{tapText(t)}</span>
            <span className="pc-code">{t.code}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
