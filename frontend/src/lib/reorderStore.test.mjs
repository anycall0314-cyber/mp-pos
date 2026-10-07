// 拖拉排序接到清單快取的那一段(切頁、重抓、換登入狀態)。跑法:npm test(Node 22.6 以上,直接讀 .ts)。
// 用**真的** QueryClient / QueryObserver:這幾條規則靠的是它「沒有畫面在用就不重抓」「取消時回到之前那一份」的行為,
// 用假的替身會把「說是重抓了」當成「真的抓到了」。
import assert from "node:assert/strict";
import test from "node:test";

import { QueryClient, QueryObserver } from "@tanstack/query-core";

import { inOrder } from "./reorder.ts";
import { listReorder, MESSAGES } from "./reorderStore.ts";

let serial = 0;
const flush = async (times = 6) => {
  for (let i = 0; i < times; i++) await new Promise((r) => setTimeout(r, 0));
};

function world(rows, queryOptions = {}) {
  const key = ["reorder-test", ++serial]; // 佇列是照清單的鑰匙記的:每個測試用自己的一份
  const w = {
    key,
    server: new Map(rows.map((r) => [r.id, { ...r }])),
    gets: 0,
    sent: [], // 送出去的存檔:「編號=新的排序@第幾次登入狀態」
    open: [],
    failIds: new Set(),
    failGet: false,
    holdGet: false,
    releaseGet: () => {},
    sessionNo: 1,
  };
  w.qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 30_000, gcTime: Infinity } },
  });
  w.queryFn = async () => {
    w.gets += 1;
    if (w.holdGet) await new Promise((go) => (w.releaseGet = go));
    if (w.failGet) throw new Error("清單抓不到");
    return [...w.server.values()].map((r) => ({ ...r }));
  };
  /** 畫面掛上去(有人在用這一份清單);回傳「卸載」 */
  w.mount = () =>
    new QueryObserver(w.qc, { queryKey: key, queryFn: w.queryFn, ...queryOptions }).subscribe(() => {});
  w.env = {
    session: () => w.sessionNo,
    save: (path, body) =>
      new Promise((resolve, reject) => {
        const id = Number(path.match(/\/(\d+)\/$/)[1]);
        w.sent.push(`${id}=${body.sort_order}@${w.sessionNo}`);
        const go = () => {
          if (w.failIds.has(id)) return reject(new Error("壞了"));
          w.server.get(id).sort_order = body.sort_order;
          resolve();
        };
        go.id = id;
        w.open.push(go);
      }),
  };
  w.list = () => listReorder(w.env, w.qc, { queryKey: key, path: (id) => `/rows/${id}/` });
  w.shown = () => inOrder(w.qc.getQueryData(key) ?? []).map((r) => r.id);
  w.serverOrder = () => inOrder([...w.server.values()]).map((r) => r.id);
  /** 放行現在開著的存檔(一直放到沒有新的為止) */
  w.release = async () => {
    await flush();
    while (w.open.length) {
      w.open.splice(0).forEach((go) => go());
      await flush();
    }
  };
  return w;
}
const row = (id, sort_order) => ({ id, sort_order, code: `C${id}`, name: `名稱${id}` });
const four = () => [row(1, 10), row(2, 20), row(3, 30), row(4, 40)];

test("放開的當下快取就換;存完真的重抓一次,畫面與伺服器一致", async () => {
  const w = world(four());
  w.mount();
  await flush();
  assert.equal(w.gets, 1);
  const list = w.list();
  assert.equal(list.move(4, 3), true);
  assert.deepEqual(w.shown(), [1, 2, 4, 3]); // 還沒存
  assert.deepEqual(w.serverOrder(), [1, 2, 3, 4]);
  await w.release();
  await list.idle();
  assert.deepEqual(w.sent, ["4=30@1", "3=40@1"]);
  assert.equal(w.gets, 2); // 只重抓一次
  assert.deepEqual(w.shown(), [1, 2, 4, 3]);
  assert.deepEqual(w.serverOrder(), [1, 2, 4, 3]);
  assert.equal(list.message(), null);
});

test("同一份清單拿到的是同一條佇列(畫面卸載再掛回來也一樣)", async () => {
  const w = world(four());
  const unmount = w.mount();
  await flush();
  const first = w.list();
  unmount();
  w.mount();
  assert.equal(w.list(), first);
});

test("存到一半切到別頁、有一列沒存成:沒有畫面在用也真的重抓;訊息留著;回來再拖不會少存", async () => {
  const w = world(four());
  const unmount = w.mount();
  await flush();
  const list = w.list();
  w.failIds.add(4);
  list.move(4, 3); // 1、2、4、3:4=30 沒存成,3=40 存成 → 伺服器 3、4 都是 40
  unmount(); // 人切到別頁了
  await w.release();
  await list.idle();
  assert.equal(w.gets, 2); // 沒有畫面在用,還是去抓了
  assert.deepEqual(w.qc.getQueryData(w.key).map((r) => [r.id, r.sort_order]), [
    [1, 10], [2, 20], [3, 40], [4, 40],
  ]); // 快取是伺服器現在的,不是沒存成的那個順序
  assert.equal(list.message(), MESSAGES.reloaded); // 切走了訊息也還在
  // 回來再拖
  w.failIds.clear();
  w.sent.length = 0;
  w.mount();
  await flush();
  const again = w.list();
  assert.equal(again, list);
  assert.equal(again.move(1, 2), true); // 畫面 1、2、3、4 → 2、1、3、4
  assert.equal(again.message(), null); // 真的有動才收掉訊息
  await w.release();
  await again.idle();
  assert.deepEqual(w.sent, ["2=10@1", "1=20@1", "3=30@1"]); // 3 要從 40 改回 30:沒有漏
  assert.deepEqual(w.serverOrder(), [2, 1, 3, 4]);
  assert.deepEqual(w.shown(), [2, 1, 3, 4]);
});

test("沒存成、重抓也沒成:講「請重新整理頁面」;下一次拖動每一列都存", async () => {
  const w = world(four());
  w.mount();
  await flush();
  const list = w.list();
  w.failIds.add(4);
  w.failGet = true;
  list.move(4, 3);
  await w.release();
  await list.idle();
  assert.equal(list.message(), MESSAGES.stale);
  assert.deepEqual(w.shown(), [1, 2, 4, 3]); // 畫面還是剛剛拖的(伺服器不是)
  w.failIds.clear();
  w.failGet = false;
  w.sent.length = 0;
  list.move(1, 2); // 2、1、4、3
  await w.release();
  await list.idle();
  assert.deepEqual(w.sent, ["2=10@1", "1=20@1", "4=30@1", "3=40@1"]); // 畫面那一份不能當成伺服器有的
  assert.deepEqual(w.serverOrder(), [2, 1, 4, 3]);
  assert.deepEqual(w.shown(), [2, 1, 4, 3]);
  assert.equal(list.message(), null);
});

test("沒存成、重抓還在路上又拖:畫面不會被蓋回去,上一輪的訊息不再講,最後一致", async () => {
  const w = world(four());
  w.mount();
  await flush();
  const list = w.list();
  w.failIds.add(4);
  w.holdGet = true;
  list.move(4, 3); // 沒存成
  await w.release();
  assert.equal(list.message(), MESSAGES.reloading); // 一沒存成就講,重抓還沒回來
  assert.equal(w.gets, 2);
  w.failIds.clear();
  list.move(1, 2); // 畫面 1、2、4、3 → 2、1、4、3
  assert.equal(list.message(), null);
  assert.deepEqual(w.shown(), [2, 1, 4, 3]);
  w.holdGet = false;
  w.releaseGet(); // 上一輪那一次重抓現在才回來:已經被取消,不能蓋掉畫面
  await flush();
  assert.deepEqual(w.shown(), [2, 1, 4, 3]);
  assert.equal(list.message(), null);
  await w.release();
  await list.idle();
  assert.deepEqual(w.serverOrder(), [2, 1, 4, 3]);
  assert.deepEqual(w.shown(), [2, 1, 4, 3]);
  assert.equal(list.message(), null);
});

test("拖回同一列(什麼都沒做):訊息留著;訊息變了會通知", async () => {
  const w = world(four());
  w.mount();
  await flush();
  const list = w.list();
  const heard = [];
  const stop = list.subscribe(() => heard.push(list.message()));
  w.failIds.add(4);
  list.move(4, 3);
  await w.release();
  await list.idle();
  assert.deepEqual(heard, [MESSAGES.reloading, MESSAGES.reloaded]);
  assert.equal(list.move(1, 1), false);
  assert.equal(list.message(), MESSAGES.reloaded);
  stop();
  w.failIds.clear();
  list.move(1, 2);
  assert.equal(list.message(), null);
  assert.equal(heard.length, 2); // 取消訂閱之後不再通知
  await w.release();
  await list.idle();
});

test("換了登入狀態:還沒送的不送(不會用下一個人的身分存),舊的收尾不碰新的快取;新的登入狀態是新的一條", async () => {
  const w = world(four());
  w.mount();
  await flush();
  const old = w.list();
  old.move(4, 3); // 第一輪:送出去了
  old.move(1, 2); // 第二輪:排著
  await flush();
  assert.deepEqual(w.sent, ["4=30@1", "3=40@1"]);
  // 登出、換人登入(畫面那一側會把快取整個清掉),新的人已經開著這一頁
  w.sessionNo = 2;
  w.qc.clear();
  w.mount();
  await flush();
  const fresh = w.list();
  assert.notEqual(fresh, old);
  assert.equal(fresh.session, 2);
  const getsBefore = w.gets;
  const shownBefore = w.qc.getQueryData(w.key);
  await w.release(); // 第一輪的回應回來了
  await old.idle();
  await flush();
  assert.deepEqual(w.sent, ["4=30@1", "3=40@1"]); // 第二輪一列都沒送
  assert.equal(w.gets, getsBefore); // 舊的收尾沒有去重抓新登入狀態的清單
  assert.equal(w.qc.getQueryData(w.key), shownBefore); // 也沒有動新登入狀態的快取
  assert.equal(fresh.message(), null);
  assert.equal(old.move(2, 1), false); // 作廢的那一條不能再用
  assert.equal(w.qc.getQueryData(w.key), shownBefore);
  // 新的登入狀態照常用:重新抓一次(伺服器現在是第一輪存成的順序)
  await w.qc.invalidateQueries({ queryKey: w.key });
  assert.deepEqual(w.shown(), [1, 2, 4, 3]);
  w.sent.length = 0;
  fresh.move(1, 2);
  await w.release();
  await fresh.idle();
  assert.deepEqual(w.sent, ["2=10@2", "1=20@2"]);
  assert.deepEqual(w.serverOrder(), [2, 1, 4, 3]);
});

test("快取裡已經沒有這一份(被清掉了):不算沒抓到,回來之後照常只存有變的", async () => {
  const w = world(four());
  const unmount = w.mount();
  await flush();
  const list = w.list();
  list.move(4, 3);
  unmount();
  w.qc.removeQueries({ queryKey: w.key }); // 例:放太久被回收
  await w.release();
  await list.idle();
  assert.equal(list.message(), null);
  w.mount();
  await flush();
  assert.deepEqual(w.shown(), [1, 2, 4, 3]);
  w.sent.length = 0;
  list.move(1, 2);
  await w.release();
  await list.idle();
  assert.deepEqual(w.sent, ["2=10@1", "1=20@1"]);
});

test("設定成不會重抓的清單:沒存成時不能說「已重新載入」", async () => {
  const w = world(four(), { staleTime: "static" });
  w.mount();
  await flush();
  const list = w.list();
  w.failIds.add(4);
  list.move(4, 3);
  await w.release();
  await list.idle();
  assert.equal(w.gets, 1); // 真的沒有去抓
  assert.equal(list.message(), MESSAGES.stale);
});

test("全部存完順便重抓別的清單(不等它)", async () => {
  const w = world(four());
  w.mount();
  await flush();
  let others = 0;
  let letOtherFinish = () => {};
  new QueryObserver(w.qc, {
    queryKey: ["other", w.key[1]],
    queryFn: async () => {
      others += 1;
      if (others > 1) await new Promise((go) => (letOtherFinish = go)); // 第二次起:卡著不回來
      return [];
    },
  }).subscribe(() => {});
  await flush();
  assert.equal(others, 1);
  const first = w.list(); // 先用沒有「順便重抓」的設定開起來
  const list = listReorder(w.env, w.qc, {
    queryKey: w.key,
    path: (id) => `/rows/${id}/`,
    alsoRefresh: [["other", w.key[1]]],
  });
  assert.equal(list, first); // 同一條;設定以最後一次畫面給的為準
  list.move(4, 3);
  list.move(1, 2);
  await w.release();
  let done = false;
  void list.idle().then(() => (done = true));
  await flush();
  assert.equal(others, 2); // 連拖兩次也只多抓一次
  assert.equal(done, true); // 別的清單還卡著,排序這一邊已經收尾完了
  assert.deepEqual(w.shown(), [2, 1, 4, 3]);
  letOtherFinish();
  await flush();
});
