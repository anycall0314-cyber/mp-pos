import { useEffect, useRef, useState } from "react";

import { api } from "@/api/client";
import { Toolbar } from "@/components/Toolbar";
import { apiErrorText } from "@/components/workbench/errors";
import { toast } from "@/components/workbench/toast";
import {
  BAUD_RATES,
  PRINTER_SETUP,
  type PrinterSetup,
  type SerialPortLike,
  bytesFromBase64,
  choosePort,
  clampTop,
  printerErrorText,
  readPrinterSetup,
  rememberedPort,
  sendToPrinter,
  serialSupported,
} from "@/lib/serialPrinter";

interface TestPage {
  kind: "ruler" | "sample";
  top: number;
  lines: string[];
  data: string;
}

function loadSetup(): PrinterSetup {
  try {
    return readPrinterSetup(window.localStorage.getItem(PRINTER_SETUP.storageKey));
  } catch {
    return readPrinterSetup(null);
  }
}

/**
 * 發票機(WP-103)測試頁:在接發票機的那台電腦上選埠、印「行號測試」與「樣張」,對紙上印好的字。
 * 位元組由伺服器排(`GET invoice-printer/test/`),這裡只負責送進 COM 埠(`lib/serialPrinter.ts`)。
 * 速率與「上面空幾行」記在這台電腦的瀏覽器裡。
 */
export function InvoicePrinterPage() {
  const supported = serialSupported();
  const [setup, setSetup] = useState<PrinterSetup>(loadSetup);
  const [chosen, setChosen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<TestPage | null>(null);
  const port = useRef<SerialPortLike | null>(null);

  // 之前在這台電腦選過的埠:瀏覽器還記得就直接用,不用每次重選
  useEffect(() => {
    let gone = false;
    rememberedPort()
      .then((p) => {
        if (gone || !p) return;
        port.current = p;
        setChosen(true);
      })
      .catch(() => undefined);
    return () => {
      gone = true;
    };
  }, []);

  function change(next: PrinterSetup) {
    setSetup(next);
    try {
      window.localStorage.setItem(PRINTER_SETUP.storageKey, JSON.stringify(next));
    } catch {
      // 存不了(無痕視窗):這一次照用,下次要重設
    }
  }

  async function pick() {
    setError("");
    try {
      port.current = await choosePort();
      setChosen(true);
    } catch (e) {
      setError(printerErrorText(e));
    }
  }

  async function print(kind: TestPage["kind"]) {
    if (!port.current || busy) return;
    setBusy(true);
    setError("");
    try {
      const page = await api<TestPage>(`/invoice-printer/test/?kind=${kind}&top=${setup.top}`);
      setPreview(page);
      // 伺服器實際用的空行數(超過它的上限會被收回來):畫面跟著,不然畫面寫的跟印出來的不一樣
      if (page.top !== setup.top) change({ ...setup, top: page.top });
      try {
        await sendToPrinter(port.current, setup.baud, bytesFromBase64(page.data));
        toast("已送到發票機", "ok");
      } catch (e) {
        setError(printerErrorText(e));
      }
    } catch (e) {
      setError(apiErrorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <Toolbar title="發票機" />
      <div className="entry-body">
        {!supported ? (
          <div className="md-empty">這個瀏覽器不能直接連發票機,請用電腦版的 Chrome 或 Edge</div>
        ) : (
          <>
            <h3 style={{ marginTop: 0 }}>連線</h3>
            <div className="invoice-printer-row">
              <button className="btn primary" type="button" onClick={pick}>
                選發票機
              </button>
              <span>{chosen ? "已選" : "未選"}</span>
              <label>
                速率
                <select
                  value={setup.baud}
                  onChange={(e) => change({ ...setup, baud: Number(e.target.value) })}
                >
                  {BAUD_RATES.map((b) => (
                    <option key={b} value={b}>
                      {b}
                    </option>
                  ))}
                </select>
              </label>
              <span className="invoice-printer-hint">印出亂碼就換一個速率</span>
            </div>

            <h3>測試</h3>
            <div className="invoice-printer-row">
              <button className="btn" type="button" disabled={!chosen || busy} onClick={() => print("ruler")}>
                行號測試
              </button>
              <button className="btn" type="button" disabled={!chosen || busy} onClick={() => print("sample")}>
                樣張測試
              </button>
              <span>上面空</span>
              <button
                className="btn"
                type="button"
                disabled={setup.top <= 0}
                onClick={() => change({ ...setup, top: clampTop(setup.top - 1) })}
              >
                −
              </button>
              <b>{setup.top}</b>
              <button
                className="btn"
                type="button"
                disabled={setup.top >= PRINTER_SETUP.topMax}
                onClick={() => change({ ...setup, top: clampTop(setup.top + 1) })}
              >
                +
              </button>
              <span>行</span>
            </div>
            <div className="invoice-printer-hint">每印一次用掉一張發票,印完到字軌跳號</div>
            {error && <div className="invoice-jump-note err">{error}</div>}
            {preview && <pre className="invoice-printer-preview">{preview.lines.join("\n")}</pre>}
          </>
        )}
      </div>
    </div>
  );
}
