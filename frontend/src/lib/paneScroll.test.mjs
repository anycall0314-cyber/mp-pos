// 主檔頁窄畫面:選了一筆整頁換成那一筆、× 回清單(全站檢視 R01)。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { readAllCss } from "./cssText.mjs";
import test from "node:test";

import { keepListBody, openPaneAtTop, trackListScroll } from "./paneScroll.ts";

function fakeWindow() {
  const win = {
    listeners: new Set(),
    frames: [],
    addEventListener: (_t, fn) => win.listeners.add(fn),
    removeEventListener: (_t, fn) => win.listeners.delete(fn),
    requestAnimationFrame: (fn) => (win.frames.push(fn), win.frames.length),
    scroll: () => win.listeners.forEach((fn) => fn()),
    paint: () => win.frames.splice(0).forEach((fn) => fn()),
  };
  return win;
}

test("清單開著時一直記位置;打開那一筆時瀏覽器已經把位置縮掉,回清單還是捲回原位", () => {
  const win = fakeWindow();
  const page = { scrollTop: 120 };
  const listAt = { current: 0 };
  const stop = trackListScroll(win, page, listAt);
  assert.equal(listAt.current, 120);
  page.scrollTop = 500;
  win.scroll();
  assert.equal(listAt.current, 500);

  stop(); // 打開那一筆:先停止記
  assert.equal(win.listeners.size, 0);
  page.scrollTop = 280; // 清單藏起來、頁面變短,瀏覽器縮掉的位置
  win.scroll();
  assert.equal(listAt.current, 500);

  const back = openPaneAtTop(win, page, listAt.current, { paneTop: 90, viewH: 700 }, () => true);
  assert.equal(page.scrollTop, 0); // 那一塊在標題下面:從整頁最上面看
  back();
  assert.equal(page.scrollTop, 0); // 清單還沒畫回來,先不捲
  win.paint();
  assert.equal(page.scrollTop, 500);
});

test("那一塊在比較下面(進貨匯入上面還有建立表單):捲到那一塊的開頭", () => {
  const win = fakeWindow();
  const page = { scrollTop: 0 };
  openPaneAtTop(win, page, 0, { paneTop: 760, viewH: 700 }, () => true);
  assert.equal(page.scrollTop, 760);
});

test("整頁換掉(去別的頁)就不捲", () => {
  const win = fakeWindow();
  const page = { scrollTop: 0 };
  const back = openPaneAtTop(win, page, 500, { paneTop: 90, viewH: 700 }, () => false);
  back();
  page.scrollTop = 40;
  win.paint();
  assert.equal(page.scrollTop, 40);
});

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");

test("五個主檔頁與進貨匯入窄畫面都有回清單的 ×;樣式在窄畫面把清單藏起來、右邊整頁", () => {
  const pages = {
    "../pages/members/MembersPage.tsx": "isEditing || isNew",
    "../pages/customers/CustomersPage.tsx": "isEditing || isNew",
    "../pages/suppliers/SuppliersPage.tsx": "isEditing || isNew",
    "../pages/sales-persons/SalesPersonsPage.tsx": "isEditing || isNew",
    "../pages/products/ProductsPage.tsx": "!!selection",
  };
  for (const [path, open] of Object.entries(pages)) {
    const src = read(path);
    assert.match(src, /className=\{[^}]*"pc-layout( pane-page)?"/, path);
    // 改過沒存要按兩次(全站檢視 R02 / V01),× 一樣走那一條;會員、商品照舊直接收
    const close = path.includes("CustomersPage")
      ? `<PaneBack open={${open}} onClose={() => leave("close", () => setSelection(null))}`
      : /Suppliers|SalesPersons/.test(path)
        ? `<PaneBack open={${open}} onClose={() => draft.leave("close", () => setSelection(null))}`
        : `<PaneBack open={${open}} onClose={() => setSelection(null)}`;
    assert.ok(src.includes(close), path);
  }
  const intake = read("../pages/intake/IntakePage.tsx");
  assert.match(intake, /className=\{selectedItem \? "md-layout intake-work md-show-detail" : "md-layout intake-work list-only"\}/);
  // 一直掛著(清單開著時才記得到位置),沒選的時候那一塊藏起來
  assert.match(intake, /<section className="md-detail">\n\s+<PaneBack open=\{!!selectedItem\} onClose=\{\(\) => setSelectedItemId\(null\)\} \/>\n\s+\{selectedItem && <ItemDetail key=\{selectedItem\.id\}/);
  assert.match(readAllCss(), /\.md-layout\.list-only > \.md-detail \{ display: none; \}/);
  const css = readAllCss();
  assert.match(css, /\.intake-work\.md-show-detail \.md-detail \{ grid-template-rows: auto minmax\(0, 1fr\); \}/);
  const narrow = css.slice(css.indexOf(".pc-pane-back { display: none; }"));
  assert.match(narrow, /^\.pc-pane-back \{ display: none; \}\n@media \(max-width: 768px\) \{/);
  assert.match(narrow, /\.pc-layout:not\(\.list-only\):not\(\.solo\) \{ grid-template-columns: minmax\(0, 1fr\); \}/);
  assert.match(narrow, /\.pc-layout:not\(\.list-only\):not\(\.solo\) > \.pc-master \{ display: none; \}/);
  assert.match(narrow, /\.pc-pane-back \{\n\s+display: flex;/);
});

test("進貨匯入單項核對:存修正、存序號、駁回沒成功要寫在那一顆下面(以前沒有任何提示),停在這一行", () => {
  const src = read("../pages/intake/IntakePage.tsx");
  for (const silent of ["correctItem.mutate(", "captureUnits.mutate(", "rejectItem.mutate("]) {
    assert.ok(!src.includes(silent), silent);
  }
  assert.match(src, /void act\("corr", \(\) => correctItem\.mutateAsync\(correctionPayload\(\)\)\)/);
  assert.match(src, /void act\("units", \(\) => captureUnits\.mutateAsync\(\{ id: item\.id, units: payload \}\)\)/);
  assert.match(src, /void act\("reject", \(\) => rejectItem\.mutateAsync\(item\.id\)\)/);
  for (const at of ["corr", "units", "reject"]) {
    assert.ok(src.includes(`{actError?.at === "${at}" && <Banner kind="error" message={actError.text} />}`), at);
  }
  // 不自動跳下一行:選哪一行只有點清單、建批次 / 換批次會動
  assert.equal(src.match(/setSelectedItemId\(/g)?.length, 5);
});

test("電腦上清單是那一塊自己捲:清單被藏起來(整頁的主檔頁)才在回來時捲回去;一直看得到(商品左右兩欄)不動", () => {
  const win = fakeWindow();
  const body = { scrollTop: 400 };
  const listAt = { current: 0 };
  const stop = trackListScroll(win, body, listAt); // 清單那一塊也照樣記
  assert.equal(listAt.current, 400);
  stop();
  body.scrollTop = 0; // 藏起來位置歸零
  keepListBody(win, body, listAt.current, true, () => true)();
  win.paint();
  assert.equal(body.scrollTop, 400);
  body.scrollTop = 120; // 左右兩欄:看詳情時捲過清單
  keepListBody(win, body, 400, false, () => true)();
  win.paint();
  assert.equal(body.scrollTop, 120);
});

test("電腦上也整頁的主檔頁(全站檢視 V01):來源、廠商、業務員、品牌系列、零件範本;會員、商品照舊左右兩欄", () => {
  for (const path of ["../pages/customers/CustomersPage.tsx", "../pages/suppliers/SuppliersPage.tsx", "../pages/sales-persons/SalesPersonsPage.tsx"]) {
    assert.ok(read(path).includes('? "pc-layout pane-page" : "pc-layout pane-page list-only"'), path);
  }
  for (const path of ["../pages/members/MembersPage.tsx", "../pages/products/ProductsPage.tsx"]) {
    assert.ok(!read(path).includes("pane-page"), path);
  }
  for (const path of ["../pages/products/BrandSeriesPage.tsx", "../pages/products/PartTemplatesPage.tsx"]) {
    const src = read(path);
    assert.ok(src.includes('<div className="entry-body pane-page"'), path);
    assert.ok(src.includes('<div className="pt-list-grid">'), path);
    assert.ok(!/預設選第一筆|setSelectedBrandId\(brands\.data!\[0\]\.id\)/.test(src), path); // 不再自動選第一個:先看清單
  }
  assert.match(read("../pages/products/BrandSeriesPage.tsx"), /<PaneBack open onClose=\{backToBrands\} \/>/);
  assert.match(read("../pages/products/PartTemplatesPage.tsx"), /<PaneBack open onClose=\{cancel\} disabled=\{save\.isPending\} \/>/);
  const css = readAllCss();
  assert.match(css, /\.pc-layout\.pane-page:not\(\.list-only\) > \.pc-master \{ display: none; \}/);
  assert.match(css, /\.pane-page \.pc-pane-back \{\n  display: flex;/);
  assert.match(read("../components/PaneBack.tsx"), /return keepListBody\(window, body, bodyAt\.current, hidden, \(\) => !leaving\.current\);/);
});
