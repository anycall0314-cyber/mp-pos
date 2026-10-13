// 發票機(WP-103):這台電腦記的設定、把一頁送進 COM 埠的順序、測試頁怎麼接。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  BAUD_RATES,
  DEFAULT_SETUP,
  PRINTER_SETUP,
  bytesFromBase64,
  clampTop,
  printerErrorText,
  readPrinterSetup,
  sendToPrinter,
} from "./serialPrinter.ts";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

test("這台電腦記的設定:讀不出來、怪值都回預設", () => {
  assert.deepEqual([...BAUD_RATES], [9600, 19200, 38400, 4800]);       // 機器指撥開關的四種
  assert.deepEqual(DEFAULT_SETUP, { baud: 9600, top: 0 });
  assert.deepEqual(readPrinterSetup('{"baud":19200,"top":3}'), { baud: 19200, top: 3 });
  for (const raw of [null, undefined, "", "abc", "null", "7", '"x"', "[]"]) {
    assert.deepEqual(readPrinterSetup(raw), { baud: 9600, top: 0 }, String(raw));
  }
  assert.deepEqual(readPrinterSetup('{"baud":1200,"top":"5"}'), { baud: 9600, top: 0 });   // 不是清單裡的速率、不是數字的行數
  assert.deepEqual(readPrinterSetup('{"baud":4800,"top":99}'), { baud: 4800, top: PRINTER_SETUP.topMax });
  for (const raw of [null, "null", "7", "abc"]) {                       // 每次給新的一份,改了不會動到預設
    assert.notEqual(readPrinterSetup(raw), DEFAULT_SETUP, String(raw));
  }
});

test("上面空幾行:整數、0 到上限", () => {
  assert.equal(PRINTER_SETUP.topMax, 9);
  assert.deepEqual([-1, 0, 1, 9, 10, 2.6, NaN, "3", null].map(clampTop), [0, 0, 1, 9, 9, 3, 0, 0, 0]);
});

test("伺服器給的位元組原樣轉回來", () => {
  const bytes = bytesFromBase64(Buffer.from([0x1b, 0x40, 0xb5, 0x6f, 0x0a, 0x0c, 0x00, 0xff]).toString("base64"));
  assert.deepEqual([...bytes], [0x1b, 0x40, 0xb5, 0x6f, 0x0a, 0x0c, 0x00, 0xff]);
  assert.equal(bytesFromBase64("").length, 0);
});

function fakePort({ failWrite = false, writable = true } = {}) {
  const log = [];
  const port = {
    log,
    async open(options) { log.push(["open", options]); },
    async close() { log.push(["close-port"]); },
    writable: writable ? {
      getWriter() {
        return {
          async write(data) { if (failWrite) throw new Error("寫不進去"); log.push(["write", [...data]]); },
          async close() { log.push(["close-writer"]); },
          releaseLock() { log.push(["release"]); },
        };
      },
    } : null,
  };
  return port;
}

test("送進發票機:開埠(8N1、不用流量控制)→ 寫 → 等寫完 → 關埠", async () => {
  const port = fakePort();
  await sendToPrinter(port, 19200, new Uint8Array([1, 2, 3]));
  assert.deepEqual(port.log, [
    ["open", { baudRate: 19200, dataBits: 8, stopBits: 1, parity: "none", flowControl: "none" }],
    ["write", [1, 2, 3]], ["close-writer"], ["release"], ["close-port"],
  ]);
});

test("寫到一半出錯、或埠寫不了:照樣把埠關掉(不佔著)", async () => {
  const broken = fakePort({ failWrite: true });
  await assert.rejects(sendToPrinter(broken, 9600, new Uint8Array([1])), /寫不進去/);
  assert.deepEqual(broken.log.map((x) => x[0]), ["open", "release", "close-port"]);
  const dead = fakePort({ writable: false });
  await assert.rejects(sendToPrinter(dead, 9600, new Uint8Array([1])), /發票機沒有回應/);
  assert.deepEqual(dead.log.map((x) => x[0]), ["open", "close-port"]);
});

test("連不上時講人話", () => {
  assert.equal(printerErrorText({ name: "NotFoundError" }), "沒有選發票機");
  assert.match(printerErrorText({ name: "NetworkError" }), /被別的程式佔著/);
  assert.equal(printerErrorText({ name: "InvalidStateError" }), "發票機正在忙,等一下再印");
  assert.equal(printerErrorText(new Error("發票機沒有回應")), "發票機沒有回應");
  assert.equal(printerErrorText(null), "送不出去");
});

test("測試頁:位元組由伺服器排、原樣送;設定記在這台電腦;選埠在按鈕的點擊裡", () => {
  const page = read("../pages/settings/InvoicePrinterPage.tsx");
  assert.match(page, /api<TestPage>\(`\/invoice-printer\/test\/\?kind=\$\{kind\}&top=\$\{setup\.top\}`\)/);
  assert.match(page, /await sendToPrinter\(port\.current, setup\.baud, bytesFromBase64\(page\.data\)\);/);
  assert.match(page, /if \(page\.top !== setup\.top\) change\(\{ \.\.\.setup, top: page\.top \}\);/);   // 伺服器收回來的空行數,畫面跟著
  assert.match(page, /window\.localStorage\.setItem\(PRINTER_SETUP\.storageKey, JSON\.stringify\(next\)\)/);
  assert.match(page, /readPrinterSetup\(window\.localStorage\.getItem\(PRINTER_SETUP\.storageKey\)\)/);
  assert.match(page, /<button className="btn primary" type="button" onClick=\{pick\}>\s*選發票機/);
  assert.match(page, /async function pick\(\) \{\s*setError\(""\);\s*try \{\s*port\.current = await choosePort\(\);/);
  // 沒選埠、正在印:兩顆測試鈕都按不了;兩顆的名字一樣長
  assert.equal(page.match(/disabled=\{!chosen \|\| busy\}/g).length, 2);
  const names = [...page.matchAll(/>\s*(行號測試|樣張測試)\s*<\/button>/g)].map((m) => m[1]);
  assert.deepEqual(names, ["行號測試", "樣張測試"]);
  // 不支援的瀏覽器講一句,不放按了沒反應的按鈕
  assert.match(page, /\{!supported \? \(\s*<div className="md-empty">這個瀏覽器不能直接連發票機/);
  // 路由與選單
  assert.match(read("../App.tsx"), /<Route path="\/settings\/invoice-printer" element=\{<InvoicePrinterPage \/>\} \/>/);
  assert.match(read("../nav.ts"), /to: "\/settings\/invoice-printer",\s*label: "發票機台",/);
});
