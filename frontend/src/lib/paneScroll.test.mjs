// 主檔頁窄畫面:選了一筆整頁換成那一筆、× 回清單(全站檢視 R01)。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { openPaneAtTop, trackListScroll } from "./paneScroll.ts";

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

  const back = openPaneAtTop(win, page, listAt.current, () => true);
  assert.equal(page.scrollTop, 0); // 從最上面看那一筆
  back();
  assert.equal(page.scrollTop, 0); // 清單還沒畫回來,先不捲
  win.paint();
  assert.equal(page.scrollTop, 500);
});

test("整頁換掉(去別的頁)就不捲", () => {
  const win = fakeWindow();
  const page = { scrollTop: 0 };
  const back = openPaneAtTop(win, page, 500, () => false);
  back();
  page.scrollTop = 40;
  win.paint();
  assert.equal(page.scrollTop, 40);
});

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");

test("五個主檔頁窄畫面都有回清單的 ×;樣式在窄畫面把清單藏起來、右邊整頁", () => {
  const pages = {
    "../pages/members/MembersPage.tsx": "isEditing || isNew",
    "../pages/customers/CustomersPage.tsx": "isEditing || isNew",
    "../pages/suppliers/SuppliersPage.tsx": "isEditing || isNew",
    "../pages/sales-persons/SalesPersonsPage.tsx": "isEditing || isNew",
    "../pages/products/ProductsPage.tsx": "!!selection",
  };
  for (const [path, open] of Object.entries(pages)) {
    const src = read(path);
    assert.match(src, /className=\{[^}]*"pc-layout"/, path);
    // 來源頁改過沒存要按兩次(全站檢視 R02),× 一樣走那一條
    const close = path.includes("CustomersPage")
      ? `<PaneBack open={${open}} onClose={() => leave("close", () => setSelection(null))}`
      : `<PaneBack open={${open}} onClose={() => setSelection(null)}`;
    assert.ok(src.includes(close), path);
  }
  const css = read("../styles.css");
  const narrow = css.slice(css.indexOf(".pc-pane-back { display: none; }"));
  assert.match(narrow, /^\.pc-pane-back \{ display: none; \}\n@media \(max-width: 768px\) \{/);
  assert.match(narrow, /\.pc-layout:not\(\.list-only\):not\(\.solo\) \{ grid-template-columns: minmax\(0, 1fr\); \}/);
  assert.match(narrow, /\.pc-layout:not\(\.list-only\):not\(\.solo\) > \.pc-master \{ display: none; \}/);
  assert.match(narrow, /\.pc-pane-back \{\n\s+display: flex;/);
});
