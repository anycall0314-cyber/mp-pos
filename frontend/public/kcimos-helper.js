/*
 * MP POS · kcimos 小幫手
 *
 * 人在 POS 的叫貨單按「自動送單」→ 開 kcimos 的分頁(網址 # 後面帶一次性的代碼)→ 人在那一頁按書籤列的這一支。
 * 它在**人已經登入的那個 kcimos 分頁**裡做:讀這張叫貨單要送什麼 → 放進購物車 → 讀結帳頁、核對跟叫貨單一模一樣 →
 * 跳出確認(店內品名、數量、kcimos 現在的單價)→ 人按「確認送出」才送 → 把 kcimos 的訂單編號記回 POS。
 *
 * 不做的:登入(那是人做的,這一支不碰登入頁上的任何一格);不知道結果時再送一次(送出去就是真的訂單、不能自己取消)。
 * 這一支只送一次,但**瀏覽器自己會重送**:連線在收到任何回應之前斷掉時,Chrome 會把同一個請求再送一兩次(這一支管不到,
 * kcimos 自己的頁面也一樣)。所以結果不明時去訂單查詢找備註 —— 找到不只一張就明講,請人聯絡 kcimos 取消多的。
 * 哪一步可以做由 POS 決定:backend/apps/vendor_orders/handoff.py。kcimos 的表單長相:docs/kcimos_下單流程實測.md。
 * 測試:frontend/src/lib/kcimosHelper.test.mjs(假的 kcimos 與假的 POS;這一份檔原樣拿去跑)。
 */
(function () {
  "use strict";

  var SITE = "http://kcimos.kv.idv.tw";
  var PATHS = {
    login: "/frontend/login.html",
    listCart: "/frontend/order/listCart.shtml",
    addCart: "/frontend/order/addCart.shtml",
    deleteCart: "/frontend/order/deleteCart.shtml",
    checkout: "/frontend/order/cart2Order.shtml",
    submit: "/frontend/order/editOrder.shtml",
    listOrder: "/frontend/order/listOrder.shtml",
    viewOrder: function (pk) {
      return "/frontend/order/initViewOrder_" + pk + ".shtml";
    },
  };
  // 代碼記在這個分頁(登入會換頁,# 後面的字會不見)
  var SAVED = "mppos_code";
  // 結帳頁的程式寫死的運費(未稅合計不到免運門檻時)。只拿來給人看,實際以 kcimos 算的為準
  var FREIGHT = 85;
  // 找訂單編號時只看最新的幾張
  var LOOK_BACK = 5;
  // 每一種請求最久等多久(毫秒)。**說了「要送了」之後最久還會忙 submit + list + LOOK_BACK × detail + pos**,
  // 要比 POS 的 `handoff.DENY_WAIT_MINUTES` 短:那段時間 POS 不給人按「沒有成立」(有測試對這兩邊的數字)
  var WAIT = { site: 30000, submit: 60000, list: 60000, detail: 15000, pos: 20000 };
  var NOT_LOGGED_IN = ["登入之後再按一次這個書籤"];

  // ── 讀東西(不碰網路)────────────────────────────────────────────────────
  /** 代碼:先看網址 # 後面的,沒有才用這個分頁記著的。 */
  function codeFrom(hash, saved) {
    var m = /(?:^#|&)mppos=([A-Za-z0-9_-]{20,80})(?:&|$)/.exec(hash || "");
    return m ? m[1] : saved || "";
  }

  function textOf(node) {
    return String((node && node.textContent) || "").replace(/\s+/g, " ").trim();
  }

  function money(n) {
    return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  }

  /** "330"、"330.0" → 330;其餘(空的、負的、有小數、不是數字)→ null。 */
  function whole(value) {
    var m = /^(\d{1,9})(?:\.0+)?$/.exec(String(value == null ? "" : value).trim());
    return m ? parseInt(m[1], 10) : null;
  }

  /** 購物車那一塊:`empty` 空的 / `items` 有東西(每一項的 cartPk)/ `unknown` 看不懂(不是預期的頁面)。 */
  function readCart(doc) {
    if (!doc) return { state: "unknown", pks: [] };
    var pks = [];
    Array.prototype.forEach.call(doc.querySelectorAll("[cartpk]"), function (el) {
      var pk = String(el.getAttribute("cartpk") || "").trim();
      if (/^\d+$/.test(pk) && pks.indexOf(pk) < 0) pks.push(pk);
    });
    if (pks.length) return { state: "items", pks: pks };
    return { state: textOf(doc.body).indexOf("無購物清單") >= 0 ? "empty" : "unknown", pks: [] };
  }

  var ITEM_FIELD = /^orderItemList\[(\d+)\]\.(pk|product_pk|price|qty)$/;
  var SKIPPED_TYPES = ["button", "submit", "reset", "image", "file"];

  /**
   * 結帳頁的那張表單:會被送出去的每一格(照表單的順序)、每一項商品、這個帳號的編號、免運門檻。
   * 讀不到表單回 null。
   */
  function readCheckout(doc) {
    var form = doc && doc.querySelector("#form_editOrder");
    if (!form) return null;
    var fields = [];
    var limits = {};
    var byIndex = {};
    var order = [];
    var account = "";
    Array.prototype.forEach.call(form.elements, function (el) {
      var type = String(el.type || "").toLowerCase();
      if (!el.name || el.disabled || SKIPPED_TYPES.indexOf(type) >= 0) return;
      if ((type === "checkbox" || type === "radio") && !el.checked) return;
      var value = el.value == null ? "" : String(el.value);
      fields.push([el.name, value]);
      if (el.maxLength > 0) limits[el.name] = el.maxLength;
      if (el.name === "order.agent_pk") account = value.trim();
      var m = ITEM_FIELD.exec(el.name);
      if (!m) return;
      if (!byIndex[m[1]]) {
        byIndex[m[1]] = {};
        order.push(m[1]);
      }
      byIndex[m[1]][m[2]] = value.trim();
    });
    var free = doc.querySelector("#noDeliveryFeeAmount");
    return {
      fields: fields,
      limits: limits,
      items: order.map(function (n) {
        return byIndex[n];
      }),
      account: account,
      freeFrom: free ? whole(free.value) : null,
    };
  }

  /**
   * 結帳頁上的東西要跟叫貨單**一模一樣**(同樣的商品、同樣的數量、不多不少)才送。
   * 對得上回每一行(照叫貨單的順序)與金額;對不上回原因。
   */
  function plan(order, checkout) {
    var inCart = {};
    var problem = "";
    checkout.items.forEach(function (item) {
      if (problem) return;
      var pk = String(item.product_pk || "");
      if (inCart[pk]) problem = "kcimos 的購物車裡同一個商品出現兩次(編號 " + pk + ")";
      inCart[pk] = item;
    });
    var rows = [];
    var sum = 0;
    order.lines.forEach(function (line) {
      if (problem) return;
      var item = inCart[String(line.pk)];
      if (!item) {
        problem = "「" + line.name + "」沒有放進購物車";
        return;
      }
      var qty = whole(item.qty);
      var price = whole(item.price);
      if (qty === null || qty !== line.qty) {
        problem = "「" + line.name + "」的數量對不上:叫貨單 " + line.qty + ",購物車 " + item.qty;
        return;
      }
      if (price === null) {
        problem = "讀不懂「" + line.name + "」的單價(" + item.price + ")";
        return;
      }
      var ref = line.ref_price == null || line.ref_price === "" ? null : Number(line.ref_price);
      if (ref !== null && !isFinite(ref)) ref = null;
      rows.push({
        pk: String(line.pk),
        name: line.name,
        spec: line.spec || "",
        shop: line.shop_name || "",
        qty: qty,
        price: price,
        ref: ref,
        changed: ref !== null && ref !== price,
        sub: price * qty,
      });
      sum += price * qty;
      delete inCart[String(line.pk)];
    });
    if (!problem) {
      var extra = Object.keys(inCart);
      if (extra.length) problem = "購物車裡有這張叫貨單沒有的商品(kcimos 編號 " + extra[0] + ")";
    }
    if (problem) return { ok: false, problem: problem };
    var tax = Math.round(sum * 0.05);
    var freight = checkout.freeFrom === null ? null : sum < checkout.freeFrom ? FREIGHT : 0;
    return { ok: true, rows: rows, sum: sum, tax: tax, freight: freight, total: sum + tax + (freight || 0) };
  }

  function encode(pairs) {
    return pairs
      .map(function (p) {
        return encodeURIComponent(p[0]).replace(/%20/g, "+") + "=" + encodeURIComponent(p[1]).replace(/%20/g, "+");
      })
      .join("&");
  }

  var RECIPIENT = [
    ["order.name", "name", "收件人"],
    ["order.tel", "phone", "收件電話"],
    ["order.address", "address", "收件地址"],
  ];

  /**
   * 要送出去的那一張表單:結帳頁原本的每一格照送,只換 未稅合計(頁面的程式本來會填)、備註(POS 的叫貨單號)、
   * 收件人 / 電話 / 地址(POS 的叫貨串接有填才換;沒填用 kcimos 帳號預設的)。
   * 回 `sent` = 實際會送出去的收件資料與備註(確認視窗給人看的就是它)。
   */
  function orderBody(checkout, order, sum) {
    var put = { "order.totalAmount": String(sum), "order.memo": String(order.memo || "") };
    var who = order.recipient || {};
    RECIPIENT.forEach(function (r) {
      var value = String(who[r[1]] == null ? "" : who[r[1]]).trim();
      if (value) put[r[0]] = value;
    });
    var present = {};
    var pairs = checkout.fields.map(function (f) {
      present[f[0]] = f[1];
      return [f[0], Object.prototype.hasOwnProperty.call(put, f[0]) ? put[f[0]] : f[1]];
    });
    var problem = "";
    Object.keys(put).forEach(function (name) {
      if (problem) return;
      if (!Object.prototype.hasOwnProperty.call(present, name)) problem = "kcimos 的結帳頁少了「" + name + "」這一格";
      else if (checkout.limits[name] && put[name].length > checkout.limits[name]) {
        var label = name === "order.memo" ? "備註" : RECIPIENT.filter(function (r) { return r[0] === name; })[0][2];
        problem = label + "超過 kcimos 的上限(" + checkout.limits[name] + " 個字),請到 POS 的叫貨串接改短";
      }
    });
    if (problem) return { ok: false, problem: problem };
    var final = {};
    pairs.forEach(function (p) {
      final[p[0]] = p[1];
    });
    return {
      ok: true,
      body: encode(pairs),
      sent: { name: final["order.name"] || "", phone: final["order.tel"] || "", address: final["order.address"] || "", memo: final["order.memo"] },
    };
  }

  function orderNoIn(text) {
    var m = /SO\d{8,20}/.exec(text || "");
    return m ? m[0] : "";
  }

  /** 送出之後 kcimos 回的:`placed` true 成立 / false 明講不行 / null 不知道(沒有回應、看不懂)。 */
  function readResult(reply) {
    var unknown = { placed: null, msg: "", orderNo: "" };
    if (!reply || !reply.ok || reply.login) return unknown;
    var data;
    try {
      data = JSON.parse(reply.text);
    } catch (e) {
      return unknown;
    }
    if (!data || typeof data !== "object") return unknown;
    var placed = data.status === true || data.status === "true" ? true : data.status === false || data.status === "false" ? false : null;
    var msg = typeof data.msg === "string" ? data.msg : "";
    return { placed: placed, msg: msg, orderNo: placed === true ? orderNoIn(msg) : "" };
  }

  /** 訂單查詢那一頁最新的幾張:訂單編號與明細頁的編號。 */
  function recentOrders(doc, limit) {
    var out = [];
    var seen = {};
    if (!doc) return out;
    Array.prototype.forEach.call(doc.querySelectorAll("tr"), function (tr) {
      if (out.length >= limit) return;
      var no = orderNoIn(textOf(tr));
      var m = /initViewOrder_(\d+)\.shtml/.exec(String(tr.innerHTML || ""));
      if (!no || !m || seen[no]) return;
      seen[no] = true;
      out.push({ no: no, pk: m[1] });
    });
    return out;
  }

  // ── 主流程 ──────────────────────────────────────────────────────────────
  /**
   * `env`:`origin` / `path` / `hash`(現在這一頁)、`saved`(這個分頁記東西:get / set / remove)、`clearHash()`、
   * `site`(對 kcimos:get(path) / post(path, 欄位或字串) → { ok, login, text, doc })、
   * `pos`(對 POS:payload(code) / step(code, 哪一步, 內容) → { ok, lost, detail, data })、
   * `ui`(busy(字) / ask(標題, 幾行, 好, 不要) / confirm(內容) / end(標題, 幾行, 語氣))。
   * 回 { outcome }(給測試看的)。
   */
  async function run(env) {
    var ui = env.ui;
    var site = env.site;
    var pos = env.pos;
    var code = "";
    var sent = false;

    async function finish(outcome, title, lines, tone) {
      await ui.end(title, (lines || []).filter(Boolean), tone || "bad");
      return { outcome: outcome };
    }

    /** 把 kcimos 的購物車清空。回清乾淨了沒。 */
    async function clearCart() {
      var now = await site.post(PATHS.listCart, {});
      var cart = now.login ? { state: "unknown", pks: [] } : readCart(now.doc);
      if (cart.state === "unknown") return false;
      for (var i = 0; i < cart.pks.length; i++) await site.post(PATHS.deleteCart, { "cart.pk": cart.pks[i] });
      var after = await site.post(PATHS.listCart, {});
      return !after.login && readCart(after.doc).state === "empty";
    }

    /**
     * 還沒說「要送了」之前的放棄:先跟 POS 說不送了。**POS 明講這一下才放掉的(到剛才為止購物車還是這一次的),才把放進去的東西清掉。**
     * 早就不是這一次的了(同一張單在別的分頁重新送、放太久被收掉)或連不到 POS:購物車現在可能是別的分頁在用,不動。
     */
    async function giveUp(outcome, title, reason) {
      ui.busy("取消中…");
      var freed = await pos.step(code, "release", { reason: reason || "人按了取消" });
      var mine = freed.ok && !!freed.data && freed.data.released === true;
      var cartLine;
      if (mine) cartLine = (await clearCart()) ? "購物車已清空" : "購物車沒有清乾淨,請到 kcimos 自己清掉";
      else if (freed.lost) cartLine = "連不到 POS:購物車沒有動,放進去的東西請到 kcimos 清掉";
      else cartLine = "這一次已經被別的分頁接手,購物車沒有動";
      if (!freed.lost) env.saved.remove(SAVED);
      return finish(outcome, title, [reason, cartLine, "要送的話回 POS 再按一次「自動送單」"], outcome === "cancelled" ? "plain" : "bad");
    }

    /** 靠備註裡的 POS 單號,從最新的幾張訂單裡找出這張叫貨單的訂單。回找到的訂單編號(可能不只一張);查不了回 []。 */
    async function findOrders(memo) {
      try {
        var list = await site.post(
          PATHS.listOrder,
          { "condition.oid": "", "condition.beginDT": "", "condition.endDT": "", "condition.queryType": "0", "condition.isShip": "-1" },
          WAIT.list,
        );
        if (!list.ok || list.login) return [];
        var recent = recentOrders(list.doc, LOOK_BACK);
        var found = [];
        for (var i = 0; i < recent.length; i++) {
          var detail = await site.get(PATHS.viewOrder(recent[i].pk), WAIT.detail);
          if (detail.ok && !detail.login && String(detail.text || "").indexOf(memo) >= 0) found.push(recent[i].no);
        }
        return found;
      } catch (e) {
        return [];
      }
    }

    try {
      if (env.origin !== SITE) return finish("wrong-site", "請在 kcimos 的頁面按這個書籤");
      code = codeFrom(env.hash, env.saved.get(SAVED));
      if (!code) return finish("no-code", "找不到要送的叫貨單", ["回 POS,在叫貨單按「自動送單」"]);
      env.saved.set(SAVED, code);
      env.clearHash();
      if (env.path === PATHS.login) return finish("login", "還沒登入 kcimos", NOT_LOGGED_IN, "plain");

      ui.busy("讀取叫貨單…");
      var got = await pos.payload(code);
      if (!got.ok) {
        if (!got.lost) env.saved.remove(SAVED);
        // 測試站與正式站各有一顆書籤:拿錯的話代碼對不上,講出這一顆連的是哪一套
        return finish("refused", "不能送", [got.detail || "POS 沒有回應", env.posHost ? "這顆書籤連的是 " + env.posHost : ""]);
      }
      var order = got.data;

      ui.busy("檢查購物車…");
      var first = await site.post(PATHS.listCart, {});
      if (first.login) return finish("login", "還沒登入 kcimos", NOT_LOGGED_IN, "plain");
      var cart = readCart(first.doc);
      if (cart.state === "unknown") return finish("unreadable", "讀不懂 kcimos 的購物車", ["沒有送出。頁面跟預期的不一樣,請通知管理員"]);
      if (cart.state === "items") {
        var wipe = await ui.ask("購物車裡已經有 " + cart.pks.length + " 項", ["不是這一次放的。清空才能送這張叫貨單。"], "清空再送", "取消返回");
        if (!wipe) return finish("cart-kept", "沒有送出", ["購物車沒有動。清掉之後再按一次這個書籤"], "plain");
        ui.busy("清空購物車…");
        if (!(await clearCart())) return finish("cart-stuck", "購物車清不乾淨", ["沒有送出。請到 kcimos 自己清掉,再按一次這個書籤"]);
      }

      // 跟 POS 說要開始動購物車了(同一家門市同時只准一張)
      var claim = await pos.step(code, "claim", {});
      if (!claim.ok) {
        if (claim.lost) await pos.step(code, "release", { reason: "連不到 POS" });
        else env.saved.remove(SAVED);
        return finish("refused", "不能送", [claim.detail || "POS 沒有回應"]);
      }

      for (var i = 0; i < order.lines.length; i++) {
        var line = order.lines[i];
        ui.busy("放進購物車 " + (i + 1) + " / " + order.lines.length);
        var added = await site.post(PATHS.addCart, { "cart.product_pk": line.pk, "cart.qty": line.qty, "cart.saleQty": 0 });
        if (!added.ok || added.login) return giveUp("failed", "沒有送出", "「" + line.name + "」放不進購物車");
      }

      ui.busy("核對結帳內容…");
      var page = await site.get(PATHS.checkout);
      var checkout = page.ok && !page.login ? readCheckout(page.doc) : null;
      if (!checkout) return giveUp("failed", "沒有送出", "讀不到 kcimos 的結帳頁");
      var p = plan(order, checkout);
      if (!p.ok) return giveUp("failed", "沒有送出", p.problem);
      if (!/^[A-Za-z0-9_-]{1,40}$/.test(checkout.account)) return giveUp("failed", "沒有送出", "讀不到 kcimos 的帳號編號");
      if (order.account && order.account !== checkout.account) {
        return giveUp("failed", "沒有送出", "這個瀏覽器登入的不是「" + order.store + "」綁定的 kcimos 帳號");
      }
      var form = orderBody(checkout, order, p.sum);
      if (!form.ok) return giveUp("failed", "沒有送出", form.problem);

      var go = await ui.confirm({ order: order, plan: p, sent: form.sent, firstTime: !order.account });
      if (!go) return giveUp("cancelled", "已取消", "");

      // 先跟 POS 說「要送了」:從這一刻起沒有回報結果,POS 的叫貨單就是待確認、不能再送
      ui.busy("送出中…");
      var saying = await pos.step(code, "submitting", { account: checkout.account, bind: !order.account });
      if (!saying.ok) {
        if (saying.lost) {
          return finish("pos-lost", "連不到 POS,沒有送出", ["購物車裡的東西還在", "回 POS 看這張叫貨單:寫「待確認」就按「沒有成立」,再重新送"]);
        }
        env.saved.remove(SAVED);
        return finish("refused", "沒有送出", [saying.detail, "購物車沒有動", "要送的話回 POS 再按一次「自動送單」"]);
      }

      // 只送這一次。之後不管回什麼都不重送
      sent = true;
      var result = readResult(await site.post(PATHS.submit, form.body, WAIT.submit));
      env.saved.remove(SAVED);

      if (result.placed === false) {
        var noted = await pos.step(code, "failed", { message: result.msg });
        var cleared = await clearCart();
        return finish("rejected", "kcimos 沒有收這張單", [
          result.msg || "(沒有說原因)",
          cleared ? "購物車已清空" : "購物車沒有清乾淨,請到 kcimos 自己清掉",
          noted.ok ? "POS 的叫貨單可以再送" : "沒有記回 POS:回 POS 的叫貨單按「沒有成立」",
        ]);
      }

      var orderNo = result.orderNo;
      if (!orderNo) {
        ui.busy("找訂單編號…");
        var found = await findOrders(order.memo);
        if (found.length > 1) {
          // 連線在回應前斷掉、瀏覽器自己重送了:每一次都成立了一張。不替人挑,POS 的叫貨單停在待確認
          return finish("duplicates", "kcimos 上有 " + found.length + " 張這張叫貨單的訂單", [
            found.join("、"),
            "連線不穩時瀏覽器自己重送了",
            "請聯絡 kcimos 取消多的",
            "留下那一張的編號填回 POS 的叫貨單,按「訂單成立」",
          ]);
        }
        orderNo = found[0] || "";
      }
      if (orderNo) {
        var told = await pos.step(code, "done", { order_no: orderNo, note: result.msg });
        if (told.ok) return finish("done", "已送出", ["kcimos 訂單 " + orderNo, "已記回 POS 叫貨單 " + order.order_no], "good");
        // POS 不收:多半是連不到;也可能是人先選了「沒有成立」又重新送了 —— POS 的那一句照樣講給人
        return finish("done-untold", "kcimos 訂單 " + orderNo + " 成立了", [
          "但沒有記回 POS",
          told.lost ? "" : told.detail,
          "回 POS 看這張叫貨單:寫「待確認」就填這個編號,按「訂單成立」",
        ]);
      }
      if (result.placed === true) {
        return finish("placed-no-number", "訂單成立了,但讀不到訂單編號", [
          "到 kcimos 的訂單查詢找備註「" + order.memo + "」那一張",
          "把編號填回 POS 的叫貨單,按「訂單成立」",
        ]);
      }
      return finish("unknown", "不確定有沒有成立", [
        "不要再送一次",
        "到 kcimos 的訂單查詢看有沒有備註「" + order.memo + "」的訂單",
        "有:把編號填回 POS 的叫貨單,按「訂單成立」",
        "沒有:在 POS 的叫貨單按「沒有成立」",
      ]);
    } catch (e) {
      if (sent) {
        return finish("unknown", "不確定有沒有成立", ["不要再送一次", "到 kcimos 的訂單查詢確認,再回 POS 的叫貨單按「訂單成立」或「沒有成立」"]);
      }
      try {
        if (code) await pos.step(code, "release", { reason: "小幫手出錯" });      // 讓 POS 馬上放開,不用等它自己過期
      } catch (ignored) {
        // 講不到也沒關係:POS 那邊放一陣子會自己收掉
      }
      return finish("crashed", "小幫手出錯,沒有送出", ["購物車裡可能有放到一半的東西,請到 kcimos 看一下", "要送的話回 POS 再按一次「自動送單」"]);
    }
  }

  // ── 接到瀏覽器 ──────────────────────────────────────────────────────────
  function decode(buffer, contentType, fallback) {
    var m = /charset=([\w-]+)/i.exec(contentType || "");
    var labels = [m && m[1], fallback, "utf-8"];
    for (var i = 0; i < labels.length; i++) {
      if (!labels[i]) continue;
      try {
        return new TextDecoder(labels[i]).decode(buffer);
      } catch (e) {
        // 不認得的編碼名稱:試下一個
      }
    }
    return "";
  }

  /** 對 kcimos(同一個網站,帶著人的登入)。不丟例外:連不上回 { ok: false, lost: true }。 */
  function siteClient(fetchFn, parse, charset) {
    function call(method, path, params, ms) {
      var controller = new AbortController();
      var timer = setTimeout(function () {
        controller.abort();
      }, ms || WAIT.site);
      var init = { method: method, credentials: "same-origin", cache: "no-store", signal: controller.signal, headers: { "X-Requested-With": "XMLHttpRequest" } };
      if (method === "POST") {
        init.headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8";
        init.body =
          typeof params === "string"
            ? params
            : encode(
                Object.keys(params || {}).map(function (k) {
                  return [k, String(params[k])];
                }),
              );
      }
      return fetchFn(path, init)
        .then(function (res) {
          return res.arrayBuffer().then(function (buffer) {
            var text = decode(buffer, res.headers.get("Content-Type"), charset);
            var login = /\/frontend\/login\.html(?:$|[?#])/.test(String(res.url || ""));
            return { ok: res.ok, login: login, text: text, doc: parse(text), lost: false };
          });
        })
        .catch(function () {
          return { ok: false, login: false, text: "", doc: null, lost: true };
        })
        .then(function (reply) {
          clearTimeout(timer);
          return reply;
        });
    }
    return {
      get: function (path, ms) {
        return call("GET", path, null, ms);
      },
      post: function (path, params, ms) {
        return call("POST", path, params, ms);
      },
    };
  }

  /** 對 POS(跨網站、不帶登入;認的是代碼)。內容用 text/plain 送 JSON:不會先發預檢。 */
  function posClient(fetchFn, api) {
    function call(method, path, body) {
      var controller = new AbortController();
      var timer = setTimeout(function () {
        controller.abort();
      }, WAIT.pos);
      var init = { method: method, mode: "cors", credentials: "omit", cache: "no-store", signal: controller.signal };
      if (method === "POST") {
        init.headers = { "Content-Type": "text/plain" };
        init.body = JSON.stringify(body || {});
      }
      return fetchFn(api + path, init)
        .then(function (res) {
          return res
            .json()
            .catch(function () {
              return {};
            })
            .then(function (data) {
              return { ok: res.ok, lost: false, data: data, detail: data && typeof data.detail === "string" ? data.detail : "" };
            });
        })
        .catch(function () {
          return { ok: false, lost: true, data: null, detail: "連不到 POS" };
        })
        .then(function (reply) {
          clearTimeout(timer);
          return reply;
        });
    }
    return {
      payload: function (code) {
        return call("GET", "/site-handoff/" + code + "/");
      },
      step: function (code, step, body) {
        return call("POST", "/site-handoff/" + code + "/" + step + "/", body);
      },
    };
  }

  var CSS = [
    "#mppos-helper{position:fixed;inset:0;z-index:2147483647;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.6);}",
    "#mppos-helper,#mppos-helper *{box-sizing:border-box;font-family:-apple-system,'Segoe UI','Microsoft JhengHei',sans-serif;line-height:1.5;letter-spacing:0;}",
    "#mppos-helper .mp-box{width:min(760px,94vw);max-height:92vh;overflow:auto;padding:20px 24px;background:#fff;color:#111;border-radius:10px;font-size:16px;text-align:left;}",
    "#mppos-helper .mp-title{margin:0 0 4px;font-size:22px;font-weight:700;color:#111;}",
    "#mppos-helper .mp-title.good{color:#0a7a3d;}#mppos-helper .mp-title.bad{color:#b42318;}",
    "#mppos-helper .mp-sub{margin:0 0 12px;color:#555;font-size:14px;}",
    "#mppos-helper .mp-line{margin:6px 0;color:#111;font-size:16px;}",
    "#mppos-helper table{width:100%;margin:8px 0;border-collapse:collapse;font-size:16px;color:#111;}",
    "#mppos-helper th,#mppos-helper td{padding:8px 6px;border-bottom:1px solid #ddd;vertical-align:top;text-align:left;background:#fff;color:#111;}",
    "#mppos-helper th{font-size:14px;color:#555;font-weight:600;}",
    "#mppos-helper .mp-num{text-align:right;white-space:nowrap;}",
    "#mppos-helper .mp-small{display:block;color:#666;font-size:13px;}",
    "#mppos-helper .mp-warn,#mppos-helper .mp-warn .mp-small{color:#b42318;font-weight:700;}",
    "#mppos-helper .mp-sum td{border-bottom:0;padding:3px 6px;}",
    "#mppos-helper .mp-sum .mp-total td{font-weight:700;font-size:18px;border-top:1px solid #111;}",
    "#mppos-helper .mp-acts{display:flex;gap:12px;justify-content:flex-end;margin-top:16px;}",
    "#mppos-helper button{min-height:44px;min-width:7em;padding:0 18px;font-size:16px;font-weight:600;border-radius:8px;border:2px solid #111;background:#fff;color:#111;cursor:pointer;}",
    "#mppos-helper button.mp-main{background:#111;color:#fff;}",
    "#mppos-helper button:disabled{opacity:.5;cursor:default;}",
  ].join("");

  /** 蓋在 kcimos 頁面上的那一層。字一律用 textContent 放(叫貨單與 kcimos 來的字不當成網頁內容)。 */
  function makeUi(doc) {
    var old = doc.getElementById("mppos-helper");
    if (old) old.remove();
    var root = doc.createElement("div");
    root.id = "mppos-helper";
    var style = doc.createElement("style");
    style.textContent = CSS;
    var box = doc.createElement("div");
    box.className = "mp-box";
    root.appendChild(style);
    root.appendChild(box);
    doc.body.appendChild(root);

    function el(tag, className, text) {
      var node = doc.createElement(tag);
      if (className) node.className = className;
      if (text != null) node.textContent = String(text);
      return node;
    }

    /** 換掉視窗裡的內容;有按鈕就回「按了哪一顆」。 */
    function show(parts, buttons) {
      box.textContent = "";
      parts.forEach(function (part) {
        box.appendChild(part);
      });
      if (!buttons) return Promise.resolve(null);
      return new Promise(function (resolve) {
        var acts = el("div", "mp-acts");
        buttons.forEach(function (b) {
          var button = el("button", b.main ? "mp-main" : "", b.label);
          button.type = "button";
          button.addEventListener("click", function () {
            Array.prototype.forEach.call(acts.querySelectorAll("button"), function (other) {
              other.disabled = true;
            });
            resolve(b.value);
          });
          acts.appendChild(button);
        });
        box.appendChild(acts);
      });
    }

    function lines(list) {
      return list.map(function (text) {
        return el("p", "mp-line", text);
      });
    }

    return {
      busy: function (text) {
        show([el("p", "mp-title", "MP POS 小幫手"), el("p", "mp-line", text)]);
      },
      ask: function (title, list, yes, no) {
        return show([el("p", "mp-title", title)].concat(lines(list)), [
          { label: no, value: false },
          { label: yes, value: true, main: true },
        ]);
      },
      end: function (title, list, tone) {
        return show([el("p", "mp-title " + (tone || ""), title)].concat(lines(list)), [{ label: "關閉", value: true, main: true }]).then(function () {
          root.remove();
        });
      },
      confirm: function (view) {
        var order = view.order;
        var p = view.plan;
        var table = el("table");
        var head = el("tr");
        ["品名", "數量", "單價", "小計"].forEach(function (name, i) {
          head.appendChild(el("th", i ? "mp-num" : "", name));
        });
        table.appendChild(head);
        p.rows.forEach(function (row) {
          var tr = el("tr");
          var name = el("td", "", row.shop || row.name);
          name.appendChild(el("span", "mp-small", (row.shop ? row.name + " " : "") + row.spec));
          tr.appendChild(name);
          tr.appendChild(el("td", "mp-num", row.qty));
          var price = el("td", "mp-num" + (row.changed ? " mp-warn" : ""), money(row.price));
          if (row.changed) price.appendChild(el("span", "mp-small", "參考 " + money(row.ref)));
          else if (row.ref === null) price.appendChild(el("span", "mp-small", "無參考價"));
          tr.appendChild(price);
          tr.appendChild(el("td", "mp-num", money(row.sub)));
          table.appendChild(tr);
        });
        var sums = el("table", "mp-sum");
        [
          ["合計(未稅)", money(p.sum), ""],
          ["稅額 5%", money(p.tax), ""],
          ["運費", p.freight === null ? "照 kcimos" : money(p.freight), ""],
          ["總金額", money(p.total), "mp-total"],
        ].forEach(function (r) {
          var tr = el("tr", r[2]);
          tr.appendChild(el("td", "mp-num", r[0]));
          tr.appendChild(el("td", "mp-num", r[1]));
          sums.appendChild(tr);
        });
        var parts = [
          el("p", "mp-title", "送到 kcimos"),
          el("p", "mp-sub", "叫貨單 " + order.order_no + " · " + order.store + " · 金額以 kcimos 為準"),
          table,
          sums,
          el("p", "mp-line", "收件 " + [view.sent.name, view.sent.phone].filter(Boolean).join(" · ")),
          el("p", "mp-line", view.sent.address),
          el("p", "mp-line", "備註 " + view.sent.memo),
        ];
        if (view.firstTime) parts.push(el("p", "mp-line mp-warn", "第一次送單:這個 kcimos 帳號會綁到「" + order.store + "」"));
        return show(parts, [
          { label: "取消返回", value: false },
          { label: "確認送出", value: true, main: true },
        ]);
      },
    };
  }

  function start() {
    if (window.__mpposHelperBusy) return;
    window.__mpposHelperBusy = true;
    var script = document.currentScript;
    var home = new URL(script ? script.src : location.href);
    var api = home.origin + "/api/v1";
    var fetchFn = window.fetch.bind(window);
    var store = {
      get: function (key) {
        try {
          return window.sessionStorage.getItem(key) || "";
        } catch (e) {
          return "";
        }
      },
      set: function (key, value) {
        try {
          window.sessionStorage.setItem(key, value);
        } catch (e) {
          // 記不住也照做:只是登入換頁之後要回 POS 重按
        }
      },
      remove: function (key) {
        try {
          window.sessionStorage.removeItem(key);
        } catch (e) {
          // 同上
        }
      },
    };
    var free = function () {
      window.__mpposHelperBusy = false;
    };
    run({
      origin: location.origin,
      path: location.pathname,
      hash: location.hash,
      posHost: home.host,
      saved: store,
      clearHash: function () {
        try {
          history.replaceState(null, "", location.pathname + location.search);
        } catch (e) {
          // 改不了網址不影響送單
        }
      },
      site: siteClient(fetchFn, function (html) {
        return new DOMParser().parseFromString(html, "text/html");
      }, document.characterSet),
      pos: posClient(fetchFn, api),
      ui: makeUi(document),
    }).then(free, free);
  }

  var api = {
    SITE: SITE,
    PATHS: PATHS,
    SAVED: SAVED,
    WAIT: WAIT,
    LOOK_BACK: LOOK_BACK,
    codeFrom: codeFrom,
    readCart: readCart,
    readCheckout: readCheckout,
    plan: plan,
    orderBody: orderBody,
    readResult: readResult,
    recentOrders: recentOrders,
    encode: encode,
    money: money,
    run: run,
    siteClient: siteClient,
    posClient: posClient,
  };
  if (typeof module === "object" && module && module.exports) module.exports = api;
  else start();
})();
