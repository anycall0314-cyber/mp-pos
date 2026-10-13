// kcimos 小幫手(frontend/public/kcimos-helper.js):在 kcimos 的分頁裡把叫貨單送出去。跑法:npm test。
// 這裡把那一份檔**原樣**拿來跑,配假的 kcimos 與假的 POS。真的瀏覽器(讀網頁、畫確認視窗)另外用無頭瀏覽器走過。
// 送出去就是真的訂單、不能自己取消,所以最要緊的幾條:只送一次;不知道結果不重送;東西對不上、帳號不對、人沒按確認都不送。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../../public/kcimos-helper.js", import.meta.url), "utf8");
const load = () => {
  const module = { exports: {} };
  new Function("module", source)(module);
  return module.exports;
};
const H = load();
const CODE = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG";

// ── 假的網頁 ──────────────────────────────────────────────────────────────
const cartDoc = (pks, text) => ({
  querySelectorAll: (sel) => (sel === "[cartpk]" ? pks.map((pk) => ({ getAttribute: () => String(pk) })) : []),
  querySelector: () => null,
  body: { textContent: text ?? (pks.length ? "購物車 某某保護貼 1 x NT$330" : "購物車 無購物清單 $(document).ready(function() { });") },
});
const input = (name, value, more = {}) => ({ name, value, type: "hidden", maxLength: -1, ...more });
const checkoutDoc = ({ account = "77", items, freeFrom = "3500", extra = [] }) => {
  const elements = [
    input("order.pk", "0"),
    input("order.agent_pk", account),
    { name: "", type: "button", value: "取消返回" },
    ...items.flatMap((it, n) => [
      input(`orderItemList[${n}].pk`, "0"),
      input(`orderItemList[${n}].product_pk`, String(it.pk)),
      input(`orderItemList[${n}].price`, String(it.price)),
      input(`orderItemList[${n}].qty`, String(it.qty), { type: "text" }),
    ]),
    input("order.totalAmount", "0"),
    input("order.name", "帳號預設的人", { type: "text" }),
    input("order.tel", "03-0000000", { type: "text", maxLength: 20 }),
    input("order.cell", "", { type: "text", maxLength: 20 }),
    input("order.email", "shop@example.com", { type: "text", maxLength: 60 }),
    input("order.address", "帳號預設的地址", { type: "text", maxLength: 200 }),
    input("order.memo", "", { type: "text", maxLength: 200 }),
    ...extra,
    { name: "btn_editOrder", type: "submit", value: "確認送出" },
  ];
  return {
    querySelector: (sel) => (sel === "#form_editOrder" ? { elements } : sel === "#noDeliveryFeeAmount" && freeFrom !== null ? { value: freeFrom } : null),
    querySelectorAll: () => [],
    body: { textContent: "" },
  };
};
const ordersDoc = (rows) => ({
  querySelectorAll: (sel) => (sel === "tr" ? rows.map((r) => ({ textContent: `明細 ${r.no} 一般 手機玩家 3656`, innerHTML: `<a href="/frontend/order/initViewOrder_${r.pk}.shtml">` })) : []),
  querySelector: () => null,
  body: { textContent: "" },
});

const PRICES = { 2685: 547, 2636: 333 };
const ORDER = () => ({
  order_no: "VO-000012",
  store: "湳雅店",
  lines: [
    { pk: "2685", qty: 5, name: "點膠2.5D窄黑邊 iP 17", spec: "玻璃", shop_name: "IMOS/IP17/玻璃", shop_sku: "A-1", ref_price: "547.00" },
    { pk: "2636", qty: 2, name: "鏡頭貼 iP 17", spec: "鏡頭", shop_name: "", shop_sku: "", ref_price: "333.00" },
  ],
  recipient: { name: "手機玩家", phone: "0925025752", address: "新竹市湳雅街18號一樓" },
  memo: "MP POS VO-000012",
  account: "77",
});

/** 假的 kcimos:記得購物車;`submit` 決定按送出之後回什麼。 */
function fakeSite(over = {}) {
  const site = {
    cart: [],
    nextPk: 340001,
    calls: [],
    account: "77",
    prices: { ...PRICES },
    submit: () => ({ ok: true, text: JSON.stringify({ status: true, msg: "訂單 SO20261013001 已送出", errorCode: "" }) }),
    orders: [],
    details: {},
    tamper: (items) => items,
    ...over,
  };
  const reply = (r) => ({ ok: true, login: false, text: "", doc: null, lost: false, ...r });
  site.post = async (path, params) => {
    site.calls.push([path, params]);
    if (site.loggedOut) return reply({ login: true });
    if (path === H.PATHS.listCart) return site.cartPage ? site.cartPage() : reply({ doc: cartDoc(site.cart.map((c) => c.cartPk)) });
    if (path === H.PATHS.addCart) {
      if (site.refuseAdd === String(params["cart.product_pk"])) return reply({ ok: false });
      site.cart.push({ cartPk: site.nextPk++, pk: String(params["cart.product_pk"]), qty: Number(params["cart.qty"]) });
      return reply({ doc: cartDoc(site.cart.map((c) => c.cartPk)) });
    }
    if (path === H.PATHS.deleteCart) {
      if (!site.stuck) site.cart = site.cart.filter((c) => String(c.cartPk) !== String(params["cart.pk"]));
      return reply({});
    }
    if (path === H.PATHS.submit) {
      const r = site.submit(params);
      if (r.ok && /"status":true/.test(r.text || "")) site.cart = [];
      return reply(r);
    }
    if (path === H.PATHS.listOrder) return reply({ doc: ordersDoc(site.orders) });
    throw new Error("沒想到的路徑 " + path);
  };
  site.get = async (path) => {
    site.calls.push([path]);
    if (path === H.PATHS.checkout) {
      if (site.noCheckout) return reply({ doc: cartDoc([], "系統忙碌中") });
      const items = site.tamper(site.cart.map((c) => ({ pk: c.pk, qty: c.qty, price: site.prices[c.pk] })));
      return reply({ doc: checkoutDoc({ account: site.account, items, freeFrom: site.freeFrom === undefined ? "3500" : site.freeFrom, extra: site.extra }) });
    }
    const m = /initViewOrder_(\d+)\.shtml/.exec(path);
    if (m) return reply({ text: site.details[m[1]] ?? "" });
    throw new Error("沒想到的路徑 " + path);
  };
  site.posted = (path) => site.calls.filter((c) => c[0] === path);
  return site;
}

/** 假的 POS:記下每一步;`answers` 可以指定哪一步回什麼。`release` 跟真的一樣:這一下才放掉的(之前 claim 過)回 `released: true`。 */
function fakePos(order = ORDER(), answers = {}) {
  const pos = { steps: [], asked: 0, claimed: false };
  pos.payload = async () => {
    pos.asked += 1;
    return answers.payload ?? { ok: true, lost: false, data: order, detail: "" };
  };
  pos.step = async (code, step, body) => {
    pos.steps.push([step, body]);
    if (answers[step]) return answers[step];
    if (step === "claim") pos.claimed = true;
    const data = step === "release" ? { ok: true, released: pos.claimed } : { ok: true };
    if (step === "release") pos.claimed = false;
    return { ok: true, lost: false, data, detail: "" };
  };
  pos.names = () => pos.steps.map((s) => s[0]);
  return pos;
}

/** 假的畫面:`confirm` / `ask` 的回答事先講好;記下每一次給人看的東西。 */
function fakeUi({ confirm = true, ask = true } = {}) {
  const ui = { busy: [], ended: null, confirmed: null, asked: null };
  return Object.assign(ui, {
    busy: Object.assign((text) => ui.busy.list.push(text), { list: [] }),
    ask: async (title, lines, yes, no) => ((ui.asked = { title, lines, yes, no }), ask),
    confirm: async (view) => ((ui.confirmed = view), confirm),
    end: async (title, lines, tone) => void (ui.ended = { title, lines, tone }),
  });
}

function env(parts = {}) {
  const kept = { [H.SAVED]: parts.savedCode ?? "" };
  const e = {
    origin: H.SITE,
    path: "/frontend/index.shtml",
    hash: `#mppos=${CODE}`,
    saved: { get: (k) => kept[k] ?? "", set: (k, v) => (kept[k] = v), remove: (k) => delete kept[k] },
    hashCleared: 0,
    site: fakeSite(),
    pos: fakePos(),
    ui: fakeUi(),
    ...parts,
  };
  e.clearHash = () => (e.hashCleared += 1);
  e.kept = kept;
  return e;
}
const fields = (body) => Object.fromEntries(new URLSearchParams(body));

// ── 整段流程 ──────────────────────────────────────────────────────────────
test("照順序:讀單 → 購物車是空的 → 開始 → 放進去 → 核對 → 人確認 → 說要送了 → 送一次 → 記回 POS", async () => {
  const e = env();
  const got = await H.run(e);
  assert.equal(got.outcome, "done");
  assert.deepEqual(e.pos.names(), ["claim", "submitting", "done"]);
  assert.deepEqual(e.pos.steps[1][1], { account: "77", bind: false });                       // 綁過的帳號:不再綁
  assert.deepEqual(e.pos.steps[2][1], { order_no: "SO20261013001", note: "訂單 SO20261013001 已送出" });
  // 對 kcimos:先看購物車,照叫貨單的順序放,讀結帳頁,送出只有一次
  assert.deepEqual(e.site.calls.map((c) => c[0]), [H.PATHS.listCart, H.PATHS.addCart, H.PATHS.addCart, H.PATHS.checkout, H.PATHS.submit]);
  assert.deepEqual(e.site.posted(H.PATHS.addCart).map((c) => c[1]), [
    { "cart.product_pk": "2685", "cart.qty": 5, "cart.saleQty": 0 },
    { "cart.product_pk": "2636", "cart.qty": 2, "cart.saleQty": 0 },
  ]);
  const sent = fields(e.site.posted(H.PATHS.submit)[0][1]);
  assert.equal(sent["order.totalAmount"], String(547 * 5 + 333 * 2));                        // 未稅合計(頁面的程式本來會填)
  assert.equal(sent["order.memo"], "MP POS VO-000012");                                      // 之後靠它認訂單
  assert.deepEqual([sent["order.name"], sent["order.tel"], sent["order.address"]], ["手機玩家", "0925025752", "新竹市湳雅街18號一樓"]);
  assert.deepEqual([sent["order.agent_pk"], sent["order.pk"], sent["order.email"], sent["order.cell"]], ["77", "0", "shop@example.com", ""]);
  assert.deepEqual([sent["orderItemList[0].product_pk"], sent["orderItemList[0].qty"], sent["orderItemList[0].price"]], ["2685", "5", "547"]);
  assert.equal("btn_editOrder" in sent, false);                                              // 按鈕不是表單的內容
  // 人看到的:店內品名、kcimos 的品名、數量、單價、金額、收件、備註
  const view = e.ui.confirmed;
  assert.deepEqual(view.plan.rows.map((r) => [r.shop, r.name, r.qty, r.price, r.changed, r.sub]), [
    ["IMOS/IP17/玻璃", "點膠2.5D窄黑邊 iP 17", 5, 547, false, 2735],
    ["", "鏡頭貼 iP 17", 2, 333, false, 666],
  ]);
  assert.deepEqual([view.plan.sum, view.plan.tax, view.plan.freight, view.plan.total], [3401, 170, 85, 3656]);
  assert.deepEqual(view.sent, { name: "手機玩家", phone: "0925025752", address: "新竹市湳雅街18號一樓", memo: "MP POS VO-000012" });
  assert.equal(view.firstTime, false);
  assert.deepEqual(e.ui.ended, { title: "已送出", lines: ["kcimos 訂單 SO20261013001", "已記回 POS 叫貨單 VO-000012"], tone: "good" });
  assert.equal(e.kept[H.SAVED], undefined);                                                  // 代碼用完就丟
  assert.equal(e.hashCleared, 1);
});

test("說「要送了」一定在送出之前;POS 不答應就不送", async () => {
  const order = [];
  const e = env();
  const step = e.pos.step;
  e.pos.step = async (...a) => (order.push(a[1]), step(...a));
  const post = e.site.post;
  e.site.post = async (...a) => (a[0] === H.PATHS.submit && order.push("送出"), post(...a));
  await H.run(e);
  assert.deepEqual(order, ["claim", "submitting", "送出", "done"]);

  const refused = env({ pos: fakePos(ORDER(), { submitting: { ok: false, lost: false, detail: "這張叫貨單已經傳給廠商了", data: {} } }) });
  assert.equal((await H.run(refused)).outcome, "refused");
  assert.equal(refused.site.posted(H.PATHS.submit).length, 0);
  assert.equal(refused.site.cart.length, 2);                                                  // 這一次可能已經被別人接手:購物車不動
  assert.deepEqual(refused.ui.ended.lines, ["這張叫貨單已經傳給廠商了", "購物車沒有動", "要送的話回 POS 再按一次「自動送單」"]);

  const lost = env({ pos: fakePos(ORDER(), { submitting: { ok: false, lost: true, detail: "連不到 POS", data: null } }) });
  assert.equal((await H.run(lost)).outcome, "pos-lost");
  assert.equal(lost.site.posted(H.PATHS.submit).length, 0);
  assert.equal(lost.ui.ended.title, "連不到 POS,沒有送出");
});

test("人按取消:不送;跟 POS 說不送了,放進去的東西清掉", async () => {
  const e = env({ ui: fakeUi({ confirm: false }) });
  assert.equal((await H.run(e)).outcome, "cancelled");
  assert.deepEqual(e.pos.names(), ["claim", "release"]);
  assert.equal(e.site.posted(H.PATHS.submit).length, 0);
  assert.equal(e.site.cart.length, 0);
  assert.deepEqual(e.ui.ended, { title: "已取消", lines: ["購物車已清空", "要送的話回 POS 再按一次「自動送單」"], tone: "plain" });
});

test("取消時這一次已經不是我們的:購物車不動(現在可能是另一個分頁在用)", async () => {
  // 同一張單在另一個分頁重新送、那一邊接手了:POS 對舊分頁的「不送了」照樣回成功,但講明不是這一下才放掉的(複審抓到的:以前看到成功就清)
  const takenOver = { ok: true, lost: false, detail: "", data: { ok: true, released: false } };
  const refused = { ok: false, lost: false, detail: "不能收回", data: {} };
  for (const release of [takenOver, refused]) {
    const e = env({ ui: fakeUi({ confirm: false }), pos: fakePos(ORDER(), { release }) });
    assert.equal((await H.run(e)).outcome, "cancelled");
    assert.equal(e.site.cart.length, 2);
    assert.equal(e.site.posted(H.PATHS.deleteCart).length, 0);
    assert.deepEqual(e.ui.ended.lines, ["這一次已經被別的分頁接手,購物車沒有動", "要送的話回 POS 再按一次「自動送單」"]);
    assert.equal(e.kept[H.SAVED], undefined);
  }
  // 連不到 POS:不知道還是不是我們的,也不動;代碼留著
  const lost = env({ ui: fakeUi({ confirm: false }), pos: fakePos(ORDER(), { release: { ok: false, lost: true, detail: "連不到 POS", data: null } }) });
  await H.run(lost);
  assert.equal(lost.site.cart.length, 2);
  assert.equal(lost.ui.ended.lines[0], "連不到 POS:購物車沒有動,放進去的東西請到 kcimos 清掉");
  assert.equal(lost.kept[H.SAVED], CODE);
});

test("kcimos 明講不行:記成沒有成立、講原因、購物車清掉;不重送", async () => {
  const site = fakeSite({ submit: () => ({ ok: true, text: JSON.stringify({ status: false, msg: "庫存不足", errorCode: "2685" }) }) });
  const e = env({ site });
  assert.equal((await H.run(e)).outcome, "rejected");
  assert.deepEqual(e.pos.names(), ["claim", "submitting", "failed"]);
  assert.deepEqual(e.pos.steps[2][1], { message: "庫存不足" });
  assert.equal(site.posted(H.PATHS.submit).length, 1);
  assert.equal(site.cart.length, 0);
  assert.deepEqual(e.ui.ended.lines, ["庫存不足", "購物車已清空", "POS 的叫貨單可以再送"]);
});

test("送出之後沒有回應:不重送;靠備註找得到那一張就記回去", async () => {
  const site = fakeSite({
    submit: () => ({ ok: false, lost: true, text: "" }),
    orders: [{ no: "SO20261013009", pk: "9001" }, { no: "SO20261012773", pk: "9000" }],
    details: { 9001: "<td>備註</td><td>MP POS VO-000012</td>", 9000: "<td>備註</td><td></td>" },
  });
  const e = env({ site });
  assert.equal((await H.run(e)).outcome, "done");
  assert.equal(site.posted(H.PATHS.submit).length, 1);
  assert.deepEqual(e.pos.steps.at(-1), ["done", { order_no: "SO20261013009", note: "" }]);
});

test("送出之後沒有回應、也找不到那一張:不重送、不亂記;叫人去查(POS 的叫貨單停在待確認)", async () => {
  for (const submit of [
    () => ({ ok: false, lost: true, text: "" }),                       // 斷線 / 逾時
    () => ({ ok: false, text: "<html>500</html>" }),                    // 伺服器錯誤
    () => ({ ok: true, text: "<html>登入</html>", login: true }),        // 被轉到登入頁
    () => ({ ok: true, text: "not json" }),
    () => ({ ok: true, text: JSON.stringify({ msg: "?" }) }),          // 沒有講成不成立
  ]) {
    const site = fakeSite({ submit, orders: [{ no: "SO20261012773", pk: "9000" }], details: { 9000: "別人的單" } });
    const e = env({ site });
    assert.equal((await H.run(e)).outcome, "unknown");
    assert.equal(site.posted(H.PATHS.submit).length, 1);
    assert.deepEqual(e.pos.names(), ["claim", "submitting"]);           // 沒有 done、沒有 failed
    assert.equal(e.ui.ended.title, "不確定有沒有成立");
    assert.equal(e.ui.ended.lines[0], "不要再送一次");
    assert.match(e.ui.ended.lines[1], /備註「MP POS VO-000012」/);
  }
});

test("成立了但讀不到編號:不猜,叫人去找", async () => {
  const yes = () => ({ ok: true, text: JSON.stringify({ status: true, msg: "訂單已送出" }) });
  const none = env({ site: fakeSite({ submit: yes }) });
  assert.equal((await H.run(none)).outcome, "placed-no-number");
  assert.deepEqual(none.pos.names(), ["claim", "submitting"]);
  assert.match(none.ui.ended.lines[0], /訂單查詢找備註「MP POS VO-000012」那一張/);
});

test("同一個備註找到不只一張(連線斷掉時瀏覽器自己重送的):講出是哪幾張、不替人挑、POS 停在待確認", async () => {
  // 這一支只送一次;但連線在收到回應之前斷掉時,瀏覽器會自己把請求重送,kcimos 那邊每一次都成立一張
  for (const submit of [() => ({ ok: false, lost: true, text: "" }), () => ({ ok: true, text: JSON.stringify({ status: true, msg: "訂單已送出" }) })]) {
    const site = fakeSite({
      submit,
      orders: [{ no: "SO20261013009", pk: "1" }, { no: "SO20261013008", pk: "2" }, { no: "SO20261012773", pk: "3" }],
      details: { 1: "MP POS VO-000012", 2: "MP POS VO-000012", 3: "" },
    });
    const e = env({ site });
    assert.equal((await H.run(e)).outcome, "duplicates");
    assert.equal(site.posted(H.PATHS.submit).length, 1);                  // 這一支自己只送了一次
    assert.deepEqual(e.pos.names(), ["claim", "submitting"]);             // 不記成立、不記失敗:要人處理
    assert.deepEqual(e.ui.ended, {
      title: "kcimos 上有 2 張這張叫貨單的訂單",
      lines: ["SO20261013009、SO20261013008", "連線不穩時瀏覽器自己重送了", "請聯絡 kcimos 取消多的", "留下那一張的編號填回 POS 的叫貨單,按「訂單成立」"],
      tone: "bad",
    });
  }
});

test("成立了、編號也有,但記不回 POS:把編號講給人;POS 說了原因就照講", async () => {
  const e = env({ pos: fakePos(ORDER(), { done: { ok: false, lost: true, detail: "連不到 POS", data: null } }) });
  assert.equal((await H.run(e)).outcome, "done-untold");
  assert.equal(e.ui.ended.title, "kcimos 訂單 SO20261013001 成立了");
  assert.deepEqual(e.ui.ended.lines, ["但沒有記回 POS", "回 POS 看這張叫貨單:寫「待確認」就填這個編號,按「訂單成立」"]);
  // 人先在 POS 選了「沒有成立」又重新送了:這一張是多出來的,POS 的那一句要讓人看到
  const extra = "這張叫貨單已經重新送出了,廠商那邊的訂單 SO20261013001 是多出來的一張,請聯絡廠商取消";
  const late = env({ pos: fakePos(ORDER(), { done: { ok: false, lost: false, detail: extra, data: { detail: extra } } }) });
  await H.run(late);
  assert.equal(late.ui.ended.lines[1], extra);
});

test("說了「要送了」之後最久還會忙多久,要比 POS 不給按「沒有成立」的那段時間短", () => {
  // 那段時間裡小幫手可能還在等 kcimos 回答;過了還在等的話,人去查、查不到、按沒有成立再送,就是兩張訂單
  const busy = H.WAIT.submit + H.WAIT.list + H.LOOK_BACK * H.WAIT.detail + H.WAIT.pos;
  const rule = readFileSync(new URL("../../../backend/apps/vendor_orders/handoff.py", import.meta.url), "utf8");
  const minutes = Number(/^DENY_WAIT_MINUTES = (\d+)$/m.exec(rule)[1]);
  assert.ok(busy < minutes * 60000, `${busy} 毫秒 對 ${minutes} 分鐘`);
  assert.ok(minutes * 60000 - busy >= 60000);                             // 至少留一分鐘
  // 這幾個數字真的有用在請求上
  const code = source.replace(/\/\*[\s\S]*?\*\//g, "");
  for (const use of ["form.body, WAIT.submit)", "WAIT.list,", "PATHS.viewOrder(recent[i].pk), WAIT.detail)", "}, WAIT.pos);", "}, ms || WAIT.site);"]) assert.ok(code.includes(use), use);
});

test("購物車跟叫貨單不一樣就不送:數量不對、多一項、少一項、單價讀不懂", async () => {
  for (const [tamper, problem] of [
    [(items) => items.map((i) => (i.pk === "2685" ? { ...i, qty: 6 } : i)), "「點膠2.5D窄黑邊 iP 17」的數量對不上:叫貨單 5,購物車 6"],
    [(items) => [...items, { pk: "9999", qty: 1, price: 10 }], "購物車裡有這張叫貨單沒有的商品(kcimos 編號 9999)"],
    [(items) => items.slice(0, 1), "「鏡頭貼 iP 17」沒有放進購物車"],
    [(items) => items.map((i) => (i.pk === "2636" ? { ...i, price: "洽詢" } : i)), "讀不懂「鏡頭貼 iP 17」的單價(洽詢)"],
    [(items) => [...items, items[0]], "kcimos 的購物車裡同一個商品出現兩次(編號 2685)"],
    [(items) => items.map((i) => (i.pk === "2685" ? { ...i, qty: "5.5" } : i)), "「點膠2.5D窄黑邊 iP 17」的數量對不上:叫貨單 5,購物車 5.5"],
  ]) {
    const e = env({ site: fakeSite({ tamper }) });
    assert.equal((await H.run(e)).outcome, "failed", problem);
    assert.equal(e.ui.ended.lines[0], problem);
    assert.equal(e.ui.confirmed, null);                                 // 連確認視窗都不出
    assert.equal(e.site.posted(H.PATHS.submit).length, 0);
    assert.deepEqual(e.pos.names(), ["claim", "release"]);
    assert.equal(e.site.cart.length, 0);
  }
});

test("單價跟參考價不一樣、沒有參考價:照 kcimos 的,標出來給人看", async () => {
  const order = ORDER();
  order.lines[1].ref_price = null;
  const site = fakeSite({ prices: { 2685: 560, 2636: 333 } });
  const e = env({ site, pos: fakePos(order) });
  assert.equal((await H.run(e)).outcome, "done");
  assert.deepEqual(e.ui.confirmed.plan.rows.map((r) => [r.price, r.ref, r.changed]), [[560, 547, true], [333, null, false]]);
  assert.equal(fields(site.posted(H.PATHS.submit)[0][1])["order.totalAmount"], String(560 * 5 + 333 * 2));
});

test("運費:未稅合計不到免運門檻才有;讀不到門檻就不估", async () => {
  const big = ORDER();
  big.lines[0].qty = 6;                                                  // 547 × 6 + 333 × 2 = 3948 ≥ 3500
  const free = env({ pos: fakePos(big) });
  await H.run(free);
  assert.deepEqual([free.ui.confirmed.plan.sum, free.ui.confirmed.plan.freight, free.ui.confirmed.plan.total], [3948, 0, 3948 + 197]);
  const edge = env({ site: fakeSite({ freeFrom: "3401" }) });           // 剛好到門檻:免運(頁面的寫法是「不到」才收)
  await H.run(edge);
  assert.equal(edge.ui.confirmed.plan.freight, 0);
  const blind = env({ site: fakeSite({ freeFrom: null }) });
  await H.run(blind);
  assert.deepEqual([blind.ui.confirmed.plan.freight, blind.ui.confirmed.plan.total], [null, 3401 + 170]);
});

test("帳號:綁的不是這一個就不送;還沒綁的要人看過那一句才綁", async () => {
  const wrong = env({ site: fakeSite({ account: "88" }) });
  assert.equal((await H.run(wrong)).outcome, "failed");
  assert.equal(wrong.ui.ended.lines[0], "這個瀏覽器登入的不是「湳雅店」綁定的 kcimos 帳號");
  assert.equal(wrong.site.posted(H.PATHS.submit).length, 0);
  assert.equal(wrong.ui.confirmed, null);

  const fresh = ORDER();
  fresh.account = "";
  const first = env({ pos: fakePos(fresh) });
  assert.equal((await H.run(first)).outcome, "done");
  assert.equal(first.ui.confirmed.firstTime, true);
  assert.deepEqual(first.pos.steps[1], ["submitting", { account: "77", bind: true }]);

  const blank = env({ site: fakeSite({ account: "" }) });
  assert.equal((await H.run(blank)).outcome, "failed");
  assert.equal(blank.ui.ended.lines[0], "讀不到 kcimos 的帳號編號");
});

test("購物車本來就有東西:問過才清;不清就什麼都不動、代碼留著", async () => {
  const stay = env({ site: fakeSite({ cart: [{ cartPk: 1, pk: "5", qty: 1 }] }), ui: fakeUi({ ask: false }) });
  assert.equal((await H.run(stay)).outcome, "cart-kept");
  assert.deepEqual([stay.ui.asked.title, stay.ui.asked.yes, stay.ui.asked.no], ["購物車裡已經有 1 項", "清空再送", "取消返回"]);
  assert.equal(stay.site.cart.length, 1);
  assert.deepEqual(stay.pos.names(), []);
  assert.equal(stay.kept[H.SAVED], CODE);                               // 清掉之後再按一次書籤還能用

  const wipe = env({ site: fakeSite({ cart: [{ cartPk: 1, pk: "5", qty: 1 }, { cartPk: 2, pk: "6", qty: 3 }] }) });
  assert.equal((await H.run(wipe)).outcome, "done");
  assert.deepEqual(wipe.site.posted(H.PATHS.deleteCart).map((c) => c[1]), [{ "cart.pk": "1" }, { "cart.pk": "2" }]);
  assert.equal(Object.keys(fields(wipe.site.posted(H.PATHS.submit)[0][1])).filter((k) => /product_pk$/.test(k)).length, 2);

  const stuck = env({ site: fakeSite({ cart: [{ cartPk: 1, pk: "5", qty: 1 }], stuck: true }) });
  assert.equal((await H.run(stuck)).outcome, "cart-stuck");
  assert.deepEqual(stuck.pos.names(), []);
});

test("還沒開始就停的:不是 kcimos、沒有代碼、還沒登入、POS 不給、購物車看不懂、放不進去、讀不到結帳頁", async () => {
  const elsewhere = env({ origin: "https://example.com" });
  assert.equal((await H.run(elsewhere)).outcome, "wrong-site");
  assert.equal(elsewhere.pos.asked, 0);

  const nothing = env({ hash: "" });
  assert.equal((await H.run(nothing)).outcome, "no-code");
  assert.deepEqual(nothing.ui.ended.lines, ["回 POS,在叫貨單按「自動送單」"]);

  // 在登入頁按:先把代碼記在這個分頁(登入會換頁、# 後面的字會不見),登入後再按一次
  const login = env({ path: "/frontend/login.html" });
  assert.equal((await H.run(login)).outcome, "login");
  assert.equal(login.kept[H.SAVED], CODE);
  assert.equal(login.pos.asked, 0);
  const after = env({ hash: "", savedCode: CODE });
  assert.equal((await H.run(after)).outcome, "done");

  const expired = env({ site: fakeSite({ loggedOut: true }) });
  assert.equal((await H.run(expired)).outcome, "login");
  assert.deepEqual(expired.pos.names(), []);

  const used = env({ pos: fakePos(ORDER(), { payload: { ok: false, lost: false, detail: "這個代碼已經用過或過期了,請回 POS 重新按「自動送單」", data: {} } }) });
  assert.equal((await H.run(used)).outcome, "refused");
  assert.equal(used.kept[H.SAVED], undefined);                           // 用不了的代碼不留
  assert.equal(used.site.calls.length, 0);
  const otherPos = env({ posHost: "pos-test.example", pos: fakePos(ORDER(), { payload: { ok: false, lost: false, detail: "代碼不對", data: {} } }) });
  await H.run(otherPos);
  assert.deepEqual(otherPos.ui.ended.lines, ["代碼不對", "這顆書籤連的是 pos-test.example"]);   // 拿到另一套 POS 的書籤時看得出來
  const offline = env({ pos: fakePos(ORDER(), { payload: { ok: false, lost: true, detail: "連不到 POS", data: null } }) });
  await H.run(offline);
  assert.equal(offline.kept[H.SAVED], CODE);

  const odd = env({ site: fakeSite({ cartPage: () => ({ ok: true, login: false, text: "", doc: cartDoc([], "系統維護中"), lost: false }) }) });
  assert.equal((await H.run(odd)).outcome, "unreadable");
  assert.deepEqual(odd.pos.names(), []);

  const busy = env({ pos: fakePos(ORDER(), { claim: { ok: false, lost: false, detail: "另一張叫貨單(VO-000011)正在送,等它處理完再送這一張", data: {} } }) });
  assert.equal((await H.run(busy)).outcome, "refused");
  assert.equal(busy.site.posted(H.PATHS.addCart).length, 0);            // POS 沒答應就不動購物車

  const noAdd = env({ site: fakeSite({ refuseAdd: "2636" }) });
  assert.equal((await H.run(noAdd)).outcome, "failed");
  assert.equal(noAdd.ui.ended.lines[0], "「鏡頭貼 iP 17」放不進購物車");
  assert.equal(noAdd.site.cart.length, 0);
  assert.deepEqual(noAdd.pos.names(), ["claim", "release"]);

  const noPage = env({ site: fakeSite({ noCheckout: true }) });
  assert.equal((await H.run(noPage)).outcome, "failed");
  assert.equal(noPage.ui.ended.lines[0], "讀不到 kcimos 的結帳頁");
  assert.equal(noPage.site.posted(H.PATHS.submit).length, 0);
});

test("收件資料:POS 沒填的用 kcimos 帳號預設的;超過 kcimos 上限不送(不默默切掉)", async () => {
  const bare = ORDER();
  bare.recipient = { name: "", phone: " ", address: "" };
  const kept = env({ pos: fakePos(bare) });
  await H.run(kept);
  assert.deepEqual(kept.ui.confirmed.sent, { name: "帳號預設的人", phone: "03-0000000", address: "帳號預設的地址", memo: "MP POS VO-000012" });

  const long = ORDER();
  long.recipient.phone = "0925025752 轉 123456789012";
  const stop = env({ pos: fakePos(long) });
  assert.equal((await H.run(stop)).outcome, "failed");
  assert.equal(stop.ui.ended.lines[0], "收件電話超過 kcimos 的上限(20 個字),請到 POS 的叫貨串接改短");
  assert.equal(stop.site.posted(H.PATHS.submit).length, 0);
});

test("中途出錯:送出之前 → 沒有送出;送出之後 → 當成不知道,不重送", async () => {
  const before = env();
  before.site.get = async () => {
    throw new Error("boom");
  };
  assert.equal((await H.run(before)).outcome, "crashed");
  assert.equal(before.site.posted(H.PATHS.submit).length, 0);
  assert.deepEqual(before.pos.names(), ["claim", "release"]);           // 讓 POS 馬上放開,別張單不用等

  const after = env();
  const step = after.pos.step;
  after.pos.step = async (code, name, body) => {
    if (name === "done") throw new Error("boom");
    return step(code, name, body);
  };
  assert.equal((await H.run(after)).outcome, "unknown");
  assert.equal(after.site.posted(H.PATHS.submit).length, 1);
});

// ── 讀東西 ────────────────────────────────────────────────────────────────
test("代碼:網址 # 後面的優先;樣子不對的不算", () => {
  assert.equal(H.codeFrom(`#mppos=${CODE}`, ""), CODE);
  assert.equal(H.codeFrom(`#x=1&mppos=${CODE}&y=2`, "old"), CODE);
  assert.equal(H.codeFrom("", "old-code"), "old-code");
  assert.equal(H.codeFrom("#mppos=short", ""), "");
  assert.equal(H.codeFrom(`#mppos=${CODE}<script>`, ""), "");
  assert.equal(H.codeFrom(`#notmppos=${CODE}`, ""), "");
});

test("購物車:空的、有東西、看不懂三種分清楚", () => {
  assert.deepEqual(H.readCart(cartDoc([])), { state: "empty", pks: [] });
  assert.deepEqual(H.readCart(cartDoc([340792, 340793, 340792])), { state: "items", pks: ["340792", "340793"] });
  assert.deepEqual(H.readCart(cartDoc([], "請先登入")), { state: "unknown", pks: [] });
  assert.deepEqual(H.readCart(null), { state: "unknown", pks: [] });
});

test("結帳表單:只收會被送出的那幾格(不收按鈕、停用的、沒勾的)", () => {
  const doc = checkoutDoc({
    items: [{ pk: 2685, qty: 5, price: 547 }],
    extra: [
      { name: "off", value: "x", type: "text", disabled: true },
      { name: "agree", value: "1", type: "checkbox", checked: false },
      { name: "pay", value: "cod", type: "radio", checked: true },
    ],
  });
  const got = H.readCheckout(doc);
  const names = got.fields.map((f) => f[0]);
  assert.equal(names.includes("btn_editOrder"), false);
  assert.equal(names.includes("off"), false);
  assert.equal(names.includes("agree"), false);
  assert.deepEqual(got.fields.find((f) => f[0] === "pay"), ["pay", "cod"]);
  assert.deepEqual(got.items, [{ pk: "0", product_pk: "2685", price: "547", qty: "5" }]);
  assert.deepEqual([got.account, got.freeFrom, got.limits["order.tel"]], ["77", 3500, 20]);
  assert.equal(H.readCheckout(cartDoc([])), null);
});

test("kcimos 回的結果:成立 / 明講不行 / 不知道", () => {
  const r = (text, more = {}) => H.readResult({ ok: true, login: false, text, ...more });
  assert.deepEqual(r('{"status":true,"msg":"訂單編號 SO20261013001 已成立"}'), { placed: true, msg: "訂單編號 SO20261013001 已成立", orderNo: "SO20261013001" });
  assert.deepEqual(r('{"status":"true","msg":"ok"}'), { placed: true, msg: "ok", orderNo: "" });
  assert.deepEqual(r('{"status":false,"msg":"庫存不足 SO20261013001"}'), { placed: false, msg: "庫存不足 SO20261013001", orderNo: "" });
  for (const odd of ['{"msg":"x"}', '{"status":1}', "null", "[]x", ""]) assert.equal(r(odd).placed, null, odd);
  assert.equal(r('{"status":true}', { ok: false }).placed, null);
  assert.equal(r('{"status":true}', { login: true }).placed, null);
  assert.equal(H.readResult(null).placed, null);
});

test("訂單查詢:只看最新幾張;同一張不重複", () => {
  const rows = [{ no: "SO20261013003", pk: "3" }, { no: "SO20261013003", pk: "3" }, { no: "SO20261013002", pk: "2" }, { no: "SO20261013001", pk: "1" }];
  assert.deepEqual(H.recentOrders(ordersDoc(rows), 2), [{ no: "SO20261013003", pk: "3" }, { no: "SO20261013002", pk: "2" }]);
  assert.deepEqual(H.recentOrders(null, 5), []);
});

test("送出去的字:中文、空白、符號都照表單的寫法編", () => {
  assert.equal(H.encode([["order.memo", "MP POS VO-1"], ["order.address", "新竹市 A&B=1"]]),
    "order.memo=MP+POS+VO-1&order.address=%E6%96%B0%E7%AB%B9%E5%B8%82+A%26B%3D1");
  assert.equal(H.money(1234567), "1,234,567");
  assert.equal(H.money(85), "85");
});

// ── 這一份檔本身 ──────────────────────────────────────────────────────────
test("小幫手不跳瀏覽器的對話框、不碰登入頁上的格子;送出只有一個地方", () => {
  const code = source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  assert.doesNotMatch(code, /(?<![.\w])(alert|prompt|confirm)\s*\(/);     // `ui.confirm(` 是自己畫的那一層,不是瀏覽器的
  assert.doesNotMatch(code, /window\.(alert|prompt|confirm)/);
  assert.doesNotMatch(code, /password|captcha|verifyCode|checkCode/i);
  assert.equal((code.match(/PATHS\.submit/g) || []).length, 1);
  assert.doesNotMatch(code, /innerHTML\s*=/);                             // 叫貨單與 kcimos 來的字不當成網頁內容塞進去
  assert.match(code, /if \(typeof module === "object" && module && module\.exports\) module\.exports = api;\s*else start\(\);/);
});

test("對 POS 的請求:不帶登入、用 text/plain 送 JSON(不會先發預檢);連不上不丟例外", async () => {
  const seen = [];
  const ok = async (url, init) => (seen.push([url, init]), { ok: true, json: async () => ({ ok: true }) });
  const pos = H.posClient(ok, "https://pos.example/api/v1");
  await pos.payload(CODE);
  await pos.step(CODE, "claim", { a: 1 });
  assert.equal(seen[0][0], `https://pos.example/api/v1/site-handoff/${CODE}/`);
  assert.equal(seen[1][0], `https://pos.example/api/v1/site-handoff/${CODE}/claim/`);
  assert.deepEqual([seen[1][1].method, seen[1][1].credentials, seen[1][1].headers["Content-Type"], seen[1][1].body], ["POST", "omit", "text/plain", '{"a":1}']);
  assert.equal(seen[0][1].headers, undefined);

  const refused = H.posClient(async () => ({ ok: false, json: async () => ({ detail: "不行" }) }), "x");
  assert.deepEqual(await refused.step(CODE, "claim"), { ok: false, lost: false, data: { detail: "不行" }, detail: "不行" });
  const down = H.posClient(async () => Promise.reject(new Error("net")), "x");
  assert.deepEqual(await down.payload(CODE), { ok: false, lost: true, data: null, detail: "連不到 POS" });
});

test("對 kcimos 的請求:帶著人的登入、照頁面的寫法送;被轉到登入頁認得出來;連不上不丟例外", async () => {
  const seen = [];
  const page = (url, body) => ({ ok: true, url, headers: { get: () => "text/html;charset=UTF-8" }, arrayBuffer: async () => new TextEncoder().encode(body).buffer });
  const site = H.siteClient(async (path, init) => (seen.push([path, init]), page("http://kcimos.kv.idv.tw" + path, "購物車 無購物清單")), (html) => ({ html }), "utf-8");
  const got = await site.post("/frontend/order/addCart.shtml", { "cart.product_pk": "2685", "cart.qty": 5 });
  assert.deepEqual([got.ok, got.login, got.text, got.doc], [true, false, "購物車 無購物清單", { html: "購物車 無購物清單" }]);
  assert.deepEqual([seen[0][1].method, seen[0][1].credentials, seen[0][1].body], ["POST", "same-origin", "cart.product_pk=2685&cart.qty=5"]);
  assert.equal(seen[0][1].headers["Content-Type"], "application/x-www-form-urlencoded; charset=UTF-8");
  await site.post("/x", "a=1&b=2");
  assert.equal(seen[1][1].body, "a=1&b=2");

  const bounced = H.siteClient(async () => page("http://kcimos.kv.idv.tw/frontend/login.html", "登入"), () => null, "utf-8");
  assert.equal((await bounced.get("/frontend/order/cart2Order.shtml")).login, true);
  const down = H.siteClient(async () => Promise.reject(new Error("net")), () => null, "utf-8");
  assert.deepEqual(await down.get("/x"), { ok: false, login: false, text: "", doc: null, lost: true });
});
