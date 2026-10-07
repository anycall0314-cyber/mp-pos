// 拖拉排序(類別、供應商)的規則。跑法:npm test(Node 22.6 以上,直接讀 .ts)。
// 這段決定「放開之後畫面馬上換、背景存、兩次拖動的存檔不交錯」;錯了畫面跟伺服器的順序會對不起來。
import assert from "node:assert/strict";
import test from "node:test";

import { bySortOrder, changedRows, createReorderQueue, inOrder, moveRow } from "./reorder.ts";

const row = (id, sort_order, code = `C${id}`) => ({ id, sort_order, code, name: `名稱${id}` });
const ids = (rows) => rows.map((r) => r.id);
const numbers = (rows) => rows.map((r) => r.sort_order);

test("畫面上的順序:編號小的在前,一樣的照代碼", () => {
  const list = [row(1, 30), row(2, 10, "B"), row(3, 10, "A"), row(4, 20)];
  assert.deepEqual(ids(inOrder(list)), [3, 2, 4, 1]);
  assert.equal(bySortOrder(row(1, 5), row(2, 5, "C1")) < 0, false); // 一樣的編號比代碼
  assert.deepEqual(ids(list), [1, 2, 3, 4]); // 不動原本那一份
});

test("往下拖:搬到那一列的位置,中間的往上遞補", () => {
  const moved = moveRow([row(1, 10), row(2, 20), row(3, 30), row(4, 40)], 1, 3);
  assert.deepEqual(ids(moved), [2, 3, 1, 4]);
  assert.deepEqual(numbers(moved), [10, 20, 30, 40]);
});

test("往上拖:搬到那一列的位置,中間的往下讓", () => {
  const moved = moveRow([row(1, 10), row(2, 20), row(3, 30), row(4, 40)], 4, 2);
  assert.deepEqual(ids(moved), [1, 4, 2, 3]);
});

test("相鄰兩列互換;別的欄位原樣留著", () => {
  const moved = moveRow([row(1, 10), row(2, 20)], 1, 2);
  assert.deepEqual(ids(moved), [2, 1]);
  assert.equal(moved[0].name, "名稱2");
});

test("沒有東西要動:同一列、找不到其中一列", () => {
  const list = [row(1, 10), row(2, 20)];
  assert.equal(moveRow(list, 1, 1), null);
  assert.equal(moveRow(list, 9, 1), null);
  assert.equal(moveRow(list, 1, 9), null);
  assert.equal(moveRow([], 1, 2), null);
});

test("照畫面上的順序算(不是照傳進來的順序),編號亂的也整份重新編", () => {
  // 編號一樣的三列照代碼排:A、B、C;把 C 拖到 A 上
  const moved = moveRow([row(2, 0, "B"), row(3, 0, "C"), row(1, 0, "A")], 3, 1);
  assert.deepEqual(ids(moved), [3, 1, 2]);
  assert.deepEqual(numbers(moved), [10, 20, 30]);
});

test("要存的只有編號跟伺服器不一樣的那幾列(照編號比,不是照位置)", () => {
  const saved = [row(1, 10), row(2, 20), row(3, 30), row(4, 40)];
  const wanted = moveRow(saved, 2, 3); // 1、3、2、4
  assert.deepEqual(changedRows(saved, wanted), [
    { id: 3, sort_order: 20 },
    { id: 2, sort_order: 30 },
  ]);
  assert.deepEqual(changedRows(saved, saved), []);
  // 伺服器那一份沒有的列一律要存
  assert.deepEqual(changedRows([], [row(7, 10)]), [{ id: 7, sort_order: 10 }]);
});

/** 假的畫面與伺服器:存檔要等測試放行才完成,看得出先後。 */
function world(list) {
  const w = {
    shown: list,
    server: new Map(list.map((r) => [r.id, r.sort_order])),
    log: [],
    open: [], // 還沒放行的存檔
    failIds: new Set(),
    settleFails: false,
    holdSettle: false, // true:重抓要等 releaseSettle() 才回來
    releaseSettle: () => {},
  };
  w.queue = createReorderQueue({
    read: () => w.shown,
    show: (rows) => {
      w.shown = rows;
      w.log.push(`show ${ids(rows).join("")}`);
    },
    save: (change) =>
      new Promise((resolve, reject) => {
        w.log.push(`save ${change.id}=${change.sort_order}`);
        const go = () => {
          if (w.failIds.has(change.id)) return reject(new Error("壞了"));
          w.server.set(change.id, change.sort_order);
          resolve();
        };
        go.id = change.id;
        w.open.push(go);
      }),
    settle: async (ok) => {
      w.log.push(`settle ${ok}`);
      if (w.settleFails) throw new Error("重抓失敗");
      if (w.holdSettle) await new Promise((go) => (w.releaseSettle = go));
      // 重抓:畫面換成伺服器現在的
      w.shown = w.shown.map((r) => ({ ...r, sort_order: w.server.get(r.id) }));
    },
  });
  /** 放行現在開著的存檔,等它們後面接的事跑完 */
  w.release = async () => {
    const batch = w.open.splice(0);
    batch.forEach((go) => go());
    for (let i = 0; i < 20; i++) await Promise.resolve();
  };
  /** 只放行某一列的存檔(其餘還在路上) */
  w.releaseOnly = async (id) => {
    const at = w.open.findIndex((go) => go.id === id);
    w.open.splice(at, 1)[0]();
    for (let i = 0; i < 20; i++) await Promise.resolve();
  };
  w.serverOrder = () =>
    [...w.server.entries()].sort((a, b) => a[1] - b[1]).map(([id]) => id);
  return w;
}
const tick = async () => {
  for (let i = 0; i < 20; i++) await Promise.resolve();
};

test("放開的當下畫面就換,存檔還沒回來", async () => {
  const w = world([row(1, 10), row(2, 20), row(3, 30)]);
  assert.equal(w.queue.move(1, 3), true);
  assert.deepEqual(ids(w.shown), [2, 3, 1]); // 同一刻就換了
  assert.deepEqual(w.log, ["show 231"]);
  await tick();
  assert.deepEqual(w.log, ["show 231", "save 2=10", "save 3=20", "save 1=30"]);
  assert.deepEqual(w.serverOrder(), [1, 2, 3]); // 伺服器還沒收到
  await w.release();
  await w.queue.idle();
  assert.deepEqual(w.serverOrder(), [2, 3, 1]);
  assert.deepEqual(w.log.at(-1), "settle true");
  assert.equal(w.log.filter((l) => l.startsWith("settle")).length, 1); // 只重抓一次
});

test("只存編號有變的那幾列", async () => {
  const w = world([row(1, 10), row(2, 20), row(3, 30), row(4, 40)]);
  w.queue.move(3, 4); // 1、2、4、3:只有 3 與 4 換
  await tick();
  assert.deepEqual(w.log, ["show 1243", "save 4=30", "save 3=40"]);
  await w.release();
  await w.queue.idle();
});

test("連拖兩次:第二次照畫面上換過的順序算,而且等第一次存完才存;全部存完才重抓一次", async () => {
  const w = world([row(1, 10), row(2, 20), row(3, 30)]);
  w.queue.move(1, 3); // 2、3、1
  w.queue.move(2, 1); // 照 2、3、1 算 → 3、1、2
  assert.deepEqual(ids(w.shown), [3, 1, 2]);
  await tick();
  // 第一次的三列送出去了,第二次的還沒送
  assert.deepEqual(w.log, ["show 231", "show 312", "save 2=10", "save 3=20", "save 1=30"]);
  await w.release();
  // 第一次存完才送第二次,而且是跟第一次存完的結果比:3、1、2 對 2、3、1 三列都變
  assert.deepEqual(w.log.slice(5), ["save 3=10", "save 1=20", "save 2=30"]);
  assert.equal(w.log.some((l) => l.startsWith("settle")), false); // 還沒全部存完:不重抓
  await w.release();
  await w.queue.idle();
  assert.deepEqual(w.serverOrder(), [3, 1, 2]);
  assert.deepEqual(w.log.filter((l) => l.startsWith("settle")), ["settle true"]);
});

test("有一列沒存成:後面排隊的不存了,講沒存成、重抓伺服器現在的", async () => {
  const w = world([row(1, 10), row(2, 20), row(3, 30)]);
  w.failIds.add(3);
  w.queue.move(1, 3); // 2、3、1
  w.queue.move(2, 1); // 排在後面
  await tick();
  await w.release();
  await w.queue.idle();
  assert.equal(w.log.filter((l) => l.startsWith("save")).length, 3); // 第二次的一列都沒送
  assert.deepEqual(w.log.filter((l) => l.startsWith("settle")), ["settle false"]);
  // 伺服器:2=10、1=30 存成了,3 沒存成、還是原本的 30
  assert.deepEqual([w.server.get(1), w.server.get(2), w.server.get(3)], [30, 10, 30]);
  // 畫面回到伺服器現在的樣子(不是停在第二次拖的 3、1、2)
  assert.deepEqual(
    w.shown.map((r) => [r.id, r.sort_order]).sort((a, b) => a[0] - b[0]),
    [[1, 30], [2, 10], [3, 30]],
  );
});

test("同一次拖動裡有一列先失敗、其他還在路上:等每一列都有結果才重抓", async () => {
  const w = world([row(1, 10), row(2, 20), row(3, 30)]);
  w.failIds.add(2);
  w.queue.move(1, 3); // 2、3、1:三列都要存
  await tick();
  await w.releaseOnly(2); // 2 先失敗,3 與 1 還在路上
  assert.equal(w.log.some((l) => l.startsWith("settle")), false); // 還不能重抓:晚到的會在重抓之後才寫進去
  await w.release();
  await w.queue.idle();
  assert.deepEqual(w.log.filter((l) => l.startsWith("settle")), ["settle false"]);
  // 重抓到的是全部落定之後的伺服器:3=20、1=30 存成了,2 還是 20
  assert.deepEqual(
    w.shown.map((r) => [r.id, r.sort_order]).sort((a, b) => a[0] - b[0]),
    [[1, 30], [2, 20], [3, 20]],
  );
  // 之後再拖只存有變的(畫面就是伺服器現在的)
  w.failIds.clear();
  w.log.length = 0;
  w.queue.move(1, 2); // 畫面照編號、代碼:2(20)、3(20)、1(30) → 1、2、3
  await tick();
  assert.deepEqual(w.log, ["show 123", "save 1=10", "save 3=30"]);
  await w.release();
  await w.queue.idle();
  assert.deepEqual(w.serverOrder(), [1, 2, 3]);
});

test("存檔的函式當場丟錯(不是回傳失敗的 promise)也算沒存成,不會卡住", async () => {
  let settled = null;
  const list = [row(1, 10), row(2, 20)];
  const queue = createReorderQueue({
    read: () => list,
    show: () => {},
    save: () => {
      throw new Error("當場壞掉");
    },
    settle: (ok) => {
      settled = ok;
    },
  });
  assert.equal(queue.move(1, 2), true);
  await queue.idle();
  assert.equal(settled, false);
});

test("存檔當場丟錯之後修好了:下一次拖動照樣存得進去(鏈沒有斷)", async () => {
  const server = new Map([[1, 10], [2, 20], [3, 30]]);
  let shown = [row(1, 10), row(2, 20), row(3, 30)];
  let broken = true;
  const saves = [];
  const queue = createReorderQueue({
    read: () => shown,
    show: (rows) => {
      shown = rows;
    },
    save: (change) => {
      if (broken) throw new Error("當場壞掉");
      saves.push(`${change.id}=${change.sort_order}`);
      server.set(change.id, change.sort_order);
      return Promise.resolve();
    },
    settle: () => {
      shown = shown.map((r) => ({ ...r, sort_order: server.get(r.id) })); // 重抓:畫面換成伺服器現在的
    },
  });
  queue.move(1, 3); // 2、3、1:一列都沒存成 → 重抓回來還是 1、2、3
  await queue.idle();
  assert.deepEqual(ids(inOrder(shown)), [1, 2, 3]);
  broken = false;
  queue.move(2, 3); // 1、3、2
  await queue.idle();
  assert.deepEqual(saves, ["3=20", "2=30"]);
  assert.deepEqual([...server.entries()].sort((a, b) => a[1] - b[1]).map(([id]) => id), [1, 3, 2]);
});

test("沒存成、重抓也沒成:下一次拖動每一列都存(畫面那一份不能當成伺服器有的)", async () => {
  const w = world([row(1, 10), row(2, 20), row(3, 30), row(4, 40)]);
  w.failIds.add(4);
  w.settleFails = true;
  w.queue.move(3, 4); // 1、2、4、3:4 沒存成,3 存成了(伺服器:1=10 2=20 4=40 3=40)
  await tick();
  await w.release();
  await w.queue.idle();
  w.failIds.clear();
  w.settleFails = false;
  w.log.length = 0;
  w.queue.move(1, 2); // 畫面是 1、2、4、3 → 2、1、4、3
  await tick();
  assert.deepEqual(w.log, ["show 2143", "save 2=10", "save 1=20", "save 4=30", "save 3=40"]);
  await w.release();
  await w.queue.idle();
  assert.deepEqual(w.serverOrder(), [2, 1, 4, 3]);
});

test("沒存成之後重抓回來了:下一次拖動又只存有變的", async () => {
  const w = world([row(1, 10), row(2, 20), row(3, 30), row(4, 40)]);
  w.failIds.add(4);
  w.queue.move(3, 4);
  await tick();
  await w.release();
  await w.queue.idle();
  w.failIds.clear();
  w.log.length = 0;
  // 重抓回來:伺服器是 1=10 2=20 3=40 4=40(4 沒存成)→ 畫面照代碼排 1、2、3、4
  assert.deepEqual(ids(inOrder(w.shown)), [1, 2, 3, 4]);
  w.queue.move(1, 2); // 2、1、3、4 → 編號 10、20、30、40:1、2、3 要存,4 本來就是 40
  await tick();
  assert.deepEqual(w.log, ["show 2134", "save 2=10", "save 1=20", "save 3=30"]);
  await w.release();
  await w.queue.idle();
  assert.deepEqual(w.serverOrder(), [2, 1, 3, 4]);
});

test("沒有東西要動:畫面不換、不存、不重抓", async () => {
  const w = world([row(1, 10), row(2, 20)]);
  assert.equal(w.queue.move(1, 1), false);
  assert.equal(w.queue.move(1, 9), false);
  await w.queue.idle();
  assert.deepEqual(w.log, []);
});

test("兩列編號一樣(照代碼排):拖過之後只存編號要變的那一列", async () => {
  // 兩列都是 10,照代碼 A 在前;把 A 拖到 B 上 → B、A,編號 10、20:只有 A 要存
  const w = world([row(1, 10, "A"), row(2, 10, "B")]);
  w.queue.move(1, 2);
  await tick();
  assert.deepEqual(w.log, ["show 21", "save 1=20"]);
  await w.release();
  await w.queue.idle();
  assert.deepEqual(w.log.at(-1), "settle true");
});

test("重抓失敗不會卡住下一次拖動", async () => {
  const w = world([row(1, 10), row(2, 20)]);
  w.settleFails = true;
  w.queue.move(1, 2);
  await tick();
  await w.release();
  await w.queue.idle();
  w.settleFails = false;
  w.log.length = 0;
  assert.equal(w.queue.move(1, 2), true); // 畫面是 2、1 → 1、2
  await tick();
  await w.release();
  await w.queue.idle();
  assert.deepEqual(w.serverOrder(), [1, 2]);
  assert.deepEqual(w.log.at(-1), "settle true");
});

test("拖過去又拖回來(不等存檔):第二次要跟第一次存完的結果比,不是跟一開始比", async () => {
  const w = world([row(1, 10), row(2, 20), row(3, 30)]);
  w.queue.move(1, 2); // 2、1、3
  w.queue.move(1, 2); // 照 2、1、3 算 → 1、2、3(跟一開始一樣)
  assert.deepEqual(ids(w.shown), [1, 2, 3]);
  await tick();
  await w.release(); // 第一次:2=10、1=20
  assert.deepEqual(w.serverOrder(), [2, 1, 3]);
  await w.release(); // 第二次:要把 1=10、2=20 存回去(跟一開始比的話會以為沒有東西要存)
  await w.queue.idle();
  assert.deepEqual(w.serverOrder(), [1, 2, 3]);
  assert.deepEqual(w.log.filter((l) => l.startsWith("save")), [
    "save 2=10", "save 1=20", "save 1=10", "save 2=20",
  ]);
});

test("沒存成、還在重抓的時候又拖:每一列都存(這時候畫面上是沒存成的那個順序)", async () => {
  const w = world([row(1, 10), row(2, 20), row(3, 30)]);
  w.failIds.add(1);
  w.holdSettle = true;
  w.queue.move(1, 3); // 2、3、1:2=10、3=20 存成,1=30 沒存成 → 伺服器 1=10 2=10 3=20
  await tick();
  await w.release();
  assert.deepEqual(w.log.at(-1), "settle false"); // 正在重抓,還沒回來
  w.failIds.clear();
  w.log.length = 0;
  w.queue.move(2, 3); // 畫面是 2、3、1 → 3、2、1
  await tick();
  w.releaseSettle();
  await tick();
  // 畫面那一份(2=10、3=20、1=30)伺服器並沒有:不能拿它來比,三列都要存
  assert.deepEqual(w.log.filter((l) => l.startsWith("save")), ["save 3=10", "save 2=20", "save 1=30"]);
  w.holdSettle = false;
  await w.release();
  await w.queue.idle();
  assert.deepEqual(w.serverOrder(), [3, 2, 1]);
});
