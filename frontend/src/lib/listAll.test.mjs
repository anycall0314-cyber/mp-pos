// 清單怎麼拿:整份都要(一頁一頁拿完、超過上限報錯),還是只要最前面那一頁。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { MAX_ROWS, PAGE, TooManyRows, byId, cutNote, firstPage, latestDay, listAll, pagePath, topPage } from "./listAll.ts";

/** 假的伺服器:`total` 筆(編號 1..total),照網址上的頁數與一頁幾筆給。記下被問過哪些網址。 */
function server(total, { sizeCap = PAGE } = {}) {
  const asked = [];
  const fetchPage = async (path) => {
    asked.push(path);
    const q = new URLSearchParams(path.split("?")[1] ?? "");
    const size = Math.min(Number(q.get("page_size") ?? 50), sizeCap);
    const page = Number(q.get("page") ?? 1);
    const results = [];
    for (let id = (page - 1) * size + 1; id <= Math.min(page * size, total); id += 1) results.push({ id });
    return { count: total, next: page * size < total ? "http://別的主機/下一頁" : null, results };
  };
  return { fetchPage, asked };
}

test("網址:加上一頁幾筆,原本的條件留著", () => {
  assert.equal(pagePath("/brands/", 1), `/brands/?page_size=${PAGE}`);
  assert.equal(pagePath("/phone-series/?brand=3&is_active=true", 1), `/phone-series/?brand=3&is_active=true&page_size=${PAGE}`);
  assert.equal(pagePath("/brands/", 3), `/brands/?page_size=${PAGE}&page=3`);
  assert.equal(pagePath("/brands/", 2, 100), "/brands/?page_size=100&page=2");
});

test("網址:原本寫的一頁幾筆、第幾頁會被換掉", () => {
  assert.equal(pagePath("/repair-orders/?status=done&page_size=200", 1), `/repair-orders/?status=done&page_size=${PAGE}`);
  assert.equal(pagePath("/x/?page=7&q=a", 1), `/x/?q=a&page_size=${PAGE}`);
  assert.equal(pagePath("/x/?page=7&q=a", 2), `/x/?page=2&q=a&page_size=${PAGE}`);
});

test("網址:中文與空白的條件原樣帶過去", () => {
  const q = new URLSearchParams(pagePath("/members/?search=%E7%8E%8B%20%E5%B0%8F%E6%98%8E", 1).split("?")[1]);
  assert.equal(q.get("search"), "王 小明");
});

test("整份都要:一頁就拿完的只問一次", async () => {
  const { fetchPage, asked } = server(120);
  const rows = await listAll(fetchPage, "/suppliers/");
  assert.equal(rows.length, 120);
  assert.deepEqual(asked, [`/suppliers/?page_size=${PAGE}`]);
});

test("整份都要:超過一頁就一頁一頁拿到沒有下一頁(以前只拿第一頁)", async () => {
  const { fetchPage, asked } = server(1234);
  const rows = await listAll(fetchPage, "/sim-cards/?status=in_stock");
  assert.equal(rows.length, 1234);
  assert.deepEqual(rows.map((r) => r.id), Array.from({ length: 1234 }, (_, i) => i + 1));
  assert.deepEqual(asked, [1, 2, 3].map((n) => pagePath("/sim-cards/?status=in_stock", n)));
});

test("整份都要:下一頁用自己拼的網址,不用伺服器給的(那個可能是別的主機 / http)", async () => {
  const { fetchPage, asked } = server(600);
  await listAll(fetchPage, "/brands/");
  assert.ok(asked.every((path) => path.startsWith("/brands/?")), asked.join(" "));
});

test("整份都要:剛好在上限 —— 全部給", async () => {
  const { fetchPage, asked } = server(MAX_ROWS);
  assert.equal((await listAll(fetchPage, "/members/")).length, MAX_ROWS);
  assert.equal(asked.length, MAX_ROWS / PAGE);
});

test("整份都要:超過上限就報錯,不給一部分", async () => {
  const { fetchPage, asked } = server(MAX_ROWS + 1);
  await assert.rejects(listAll(fetchPage, "/members/"), (e) => {
    assert.ok(e instanceof TooManyRows);
    assert.equal(e.count, MAX_ROWS + 1);
    assert.equal(e.message, "超過 5,000 筆,無法一次列出");
    assert.equal(String(e), "超過 5,000 筆,無法一次列出");       // 畫面直接印錯誤:不要多出英文的類別名稱
    return true;
  });
  assert.equal(asked.length, 1);                                   // 第一頁就知道了,不用拿完才講
});

test("整份都要:超過上限時講人可以怎麼辦", async () => {
  const { fetchPage } = server(9000);
  await assert.rejects(listAll(fetchPage, "/phone-bills/", "請把期間縮小"), { message: "超過 5,000 筆,請把期間縮小" });
});

test("整份都要:伺服器一直說還有下一頁 —— 報錯,不會拿不完", async () => {
  let calls = 0;
  const fetchPage = async () => {
    calls += 1;
    return { count: 10, next: "還有", results: [{ id: calls }] };
  };
  await assert.rejects(listAll(fetchPage, "/x/"), TooManyRows);
  assert.ok(calls <= MAX_ROWS / PAGE + 1, String(calls));
});

test("整份都要:說還有下一頁卻給空的 —— 停", async () => {
  const fetchPage = async () => ({ count: 0, next: "還有", results: [] });
  assert.deepEqual(await listAll(fetchPage, "/x/"), []);
});

test("整份都要:拿到一半有人新增(同一列在下一頁又出現)—— 不重複,而且整份重拿一次", async () => {
  // 第一輪:第 1 頁拿完之後有人新增一筆排在最前面 → 第 2 頁的第一列是第 1 頁的最後一列
  let walks = 0;
  const fetchPage = async (path) => {
    const page = Number(new URLSearchParams(path.split("?")[1]).get("page") ?? 1);
    if (page === 1) walks += 1;
    const ids = Array.from({ length: 501 }, (_, i) => i + 1);          // 原本 501 筆
    if (walks === 1 && page === 1) return { count: 501, next: "有", results: ids.slice(0, 500).map((id) => ({ id })) };
    if (walks === 1) return { count: 502, next: null, results: [{ id: 500 }, { id: 501 }] };
    const now = [999, ...ids];                                         // 第二輪:清單不再變
    return { count: 502, next: page === 1 ? "有" : null, results: now.slice((page - 1) * 500, page * 500).map((id) => ({ id })) };
  };
  const rows = await listAll(fetchPage, "/x/");
  assert.equal(walks, 2);
  assert.equal(rows.length, 502);
  assert.equal(new Set(rows.map((r) => r.id)).size, 502);
  assert.ok(rows.some((r) => r.id === 999));
});

test("整份都要:沒有編號的列不會被當成重複", async () => {
  const fetchPage = async () => ({ count: 3, next: null, results: [{ name: "甲" }, { name: "甲" }, { name: "乙" }] });
  assert.equal((await listAll(fetchPage, "/x/")).length, 3);
});

test("只要最前面那一頁:只問一次,網址不動", async () => {
  const { fetchPage, asked } = server(300, { sizeCap: 100 });
  const rows = await firstPage(fetchPage, "/sales-orders/?page_size=100");
  assert.equal(rows.length, 100);
  assert.deepEqual(asked, ["/sales-orders/?page_size=100"]);
});

test("最前面那一頁 + 總共幾筆", async () => {
  const { fetchPage } = server(26916, { sizeCap: 100 });
  const top = await topPage(fetchPage, "/members/?ordering=name&page_size=100");
  assert.equal(top.rows.length, 100);
  assert.equal(top.count, 26916);
});

test("少列了才講,而且講列了幾筆", () => {
  assert.equal(cutNote({ rows: new Array(100), count: 26916 }, "只列前", "位"), "只列前 100 位");
  assert.equal(cutNote({ rows: new Array(100), count: 101 }, "只列最近", "張"), "只列最近 100 張");
  assert.equal(cutNote({ rows: new Array(100), count: 100 }, "只列前", "位"), "");
  assert.equal(cutNote({ rows: new Array(3), count: 3 }, "只列前", "位"), "");
  assert.equal(cutNote({ rows: [], count: 0 }, "只列前", "位"), "");
  assert.equal(cutNote(undefined, "只列前", "位"), "");
});

test("最晚的那一天:空的不算", () => {
  assert.equal(latestDay("2026-10-01", "2026-10-13", "2026-09-30"), "2026-10-13");
  assert.equal(latestDay(null, undefined, "", "2025-01-02"), "2025-01-02");
  assert.equal(latestDay("2026-10-13", null), "2026-10-13");
  assert.equal(latestDay(), null);
  assert.equal(latestDay(null, ""), null);
});

test("顯示誰:編號對得上的那一個;對不上寧可不顯示", () => {
  const picked = { id: 7, name: "點名單時記下來的" };
  const fetched = { id: 7, name: "另外讀到的" };
  assert.equal(byId(7, picked, fetched), picked);                  // 手上那一位優先(名單換了他也不換)
  assert.equal(byId(7, null, fetched), fetched);                   // 從別頁連過來:用另外讀到的
  assert.equal(byId(7, { id: 3, name: "上一位" }, fetched), fetched);
  assert.equal(byId(9, { id: 3, name: "上一位" }, { id: 7, name: "上上一位" }), null);   // 都不是他:不給(不能把別人放進表單)
  assert.equal(byId(7, null, undefined), null);                    // 還沒讀到
  assert.equal(byId(null, picked, fetched), null);                 // 沒有選人
});

// ── 每一處讀清單都要明講是哪一種(`api/hooks.ts`)────────────────────────
const hooks = readFileSync(new URL("../api/hooks.ts", import.meta.url), "utf8");

/** `名稱<型別>(` 後面第一個出現的端點(例:/brands/)。 */
function endpoints(name) {
  const found = [];
  const pattern = new RegExp(`\\b${name}<\\w+>\\(([\\s\\S]{0,200}?)[\`"](/[a-z-]+(?:/[a-z-]+)?/)`, "g");
  for (const match of hooks.matchAll(pattern)) found.push(match[2]);
  return found.sort();
}

test("共用的四支各自做的事", () => {
  assert.match(hooks, /function listAll<T>\(path: string, hint\?: string\) \{\s*return walkAll<T>\(fetchPage, path, hint\);/);
  assert.match(hooks, /function firstPage<T>\(path: string\) \{\s*return onlyFirstPage<T>\(fetchPage, path\);/);
  assert.match(hooks, /function topPage<T>\(path: string\) \{\s*return onlyTopPage<T>\(fetchPage, path\);/);
  assert.match(hooks, /function listSome<T>\(whole: boolean, path: string\) \{\s*return whole \? listAll<T>\(path\) : firstPage<T>\(path\);/);
  assert.match(hooks, /firstPage as onlyFirstPage,\s*listAll as walkAll,\s*topPage as onlyTopPage,/);
});

test("沒有只拿第一頁、又不講的那一支了", () => {
  assert.doesNotMatch(hooks, /\blist<\w+>\(/);
  assert.equal(hooks.match(/api<Paginated</g).length, 1);          // 只有共用的那一支直接讀分頁的回應
});

test("只要最前面那一頁的,就是這幾處(新的清單要整份的不能寫在這裡)", () => {
  assert.deepEqual(endpoints("firstPage"), ["/identity/intakes/", "/products/", "/serials/", "/serials/"]);
  assert.deepEqual(endpoints("topPage"), ["/members/", "/sales-orders/"]);
  assert.deepEqual(endpoints("listSome"), ["/purchase-orders/", "/sales-orders/", "/sales-returns/", "/transfer-orders/"]);
});

test("下拉的選項、管理頁、有合計的清單都是整份都要", () => {
  const whole = endpoints("listAll");
  for (const path of [
    "/brands/", "/carriers/", "/cash-adjustments/", "/categories/", "/conditions/", "/customers/", "/identity/aliases/",
    "/invoice-tracks/", "/invoice-types/", "/legacy-purchases/", "/part-templates/", "/payment-methods/", "/petty-expenses/",
    "/phone-bills/", "/phone-series/", "/platform/tenants/", "/platform/users/", "/platform/warehouses/", "/product-types/",
    "/repair-items/", "/repair-orders/", "/sales-persons/", "/sim-cards/", "/suppliers/", "/telecom-plans/", "/warehouses/",
  ]) assert.ok(whole.includes(path), `${path} 不是整份都要`);
});

test("雜支 / 現金調整 / 代收話費:帶期間,超過上限講「請把期間縮小」", () => {
  for (const path of ["/petty-expenses/", "/cash-adjustments/", "/phone-bills/"]) {
    assert.ok(hooks.includes(`(inPeriod("${path}", range), NARROW)`), path);
  }
  assert.match(hooks, /const NARROW = "請把期間縮小";/);
  assert.match(hooks, /buildQS\(\{ doc_date__gte: range\.from, doc_date__lte: range\.to \}\)/);
});

test("單據清單:有選日期才整份都要", () => {
  assert.match(hooks, /listSome<PurchaseOrder>\(\s*!!\(range\?\.from \|\| range\?\.to\),/);
  assert.match(hooks, /listSome<SalesOrder>\(\s*!!\(filter\?\.from \|\| filter\?\.to\),/);
  assert.match(hooks, /listSome<SalesReturn>\(\s*!!\(filter\?\.from \|\| filter\?\.to \|\| filter\?\.original_so\),/);
  assert.match(hooks, /listSome<TransferOrder>\(\s*!!\(params\?\.doc_date_gte \|\| params\?\.doc_date_lte \|\| params\?\.status\),/);
});

test("會員名單問伺服器:照姓名、一次 100 位、打的字交給伺服器查", () => {
  assert.match(hooks, /export const MEMBER_PAGE = 100;/);
  assert.match(hooks, /new URLSearchParams\(\{ ordering: "name", page_size: String\(MEMBER_PAGE\) \}\)/);
  assert.match(hooks, /if \(search\.trim\(\)\) q\.set\("search", search\.trim\(\)\);/);
});

test("會員 / 客戶的幾張、累計、最近:問伺服器算全部的那一支", () => {
  assert.match(hooks, /api<OrderSummary>\(`\/sales-orders\/summary\/\$\{buildQS\(\{ member: who\?\.member, customer: who\?\.customer \}\)\}`\)/);
  for (const page of ["../pages/members/MembersPage.tsx", "../pages/customers/CustomersPage.tsx"]) {
    const source = readFileSync(new URL(page, import.meta.url), "utf8");
    assert.match(source, /count: summary\.data\?\.count \?\? 0,/, page);
    assert.match(source, /total: Number\(summary\.data\?\.total \?\? 0\),/, page);
    assert.doesNotMatch(source, /useSalesOrders/, page);
  }
});

test("三頁現金的單:清單跟著起日 / 迄日,預設本月到今天", () => {
  for (const [page, hook] of [
    ["../pages/cash/PettyExpensesPage.tsx", "usePettyExpenses"],
    ["../pages/cash/CashAdjustmentsPage.tsx", "useCashAdjustments"],
    ["../pages/phone-bills/PhoneBillsPage.tsx", "usePhoneBills"],
  ]) {
    const source = readFileSync(new URL(page, import.meta.url), "utf8");
    assert.ok(source.includes(`= ${hook}({ from, to });`), page);
    assert.match(source, /const \[from, setFrom\] = useState\(monthStart\);/, page);
    assert.match(source, /const \[to, setTo\] = useState\(localDay\);/, page);
    // 換期間會重新載入、清單那一塊整個重裝:搜尋框顯示的字要跟實際在篩的同一份,不然框空了、清單與合計卻還照舊的字篩
    assert.match(source, /onSearch=\{setQuery\}\s*searchValue=\{query\}/, page);
  }
  const shared = readFileSync(new URL("../components/master-detail/MasterDetail.tsx", import.meta.url), "utf8");
  assert.match(shared, /placeholder=\{searchPlaceholder\}\s*value=\{searchValue\}\s*onChange=\{\(e\) => onSearch\?\.\(e\.target\.value\)\}/);
});

test("會員頁:右邊顯示誰、還沒讀到不給表單、存檔後換成存好的那一份", () => {
  const source = readFileSync(new URL("../pages/members/MembersPage.tsx", import.meta.url), "utf8");
  assert.match(source, /const selected = useMemo\(\(\) => byId\(selectedId, picked, one\.data\), \[selectedId, picked, one\.data\]\);/);
  assert.match(source, /const one = useMember\(selectedId != null && picked\?\.id !== selectedId \? selectedId : null\);/);
  assert.match(source, /\{\(isNew \|\| \(isEditing && selected\)\) && \(/);
  assert.doesNotMatch(source, /\{\(isEditing \|\| isNew\) && \(/);
  assert.match(source, /setPicked\(saved\);\s*setSelection\(\{ kind: "member", id: saved\.id \}\);/);
  assert.match(source, /const result = useMemberList\(search\);/);
  assert.match(source, /lastVisit: latestDay\(summary\.data\?\.last_date, \.\.\.legacyList\.map\(\(lp\) => lp\.doc_date\)\),/);
});
