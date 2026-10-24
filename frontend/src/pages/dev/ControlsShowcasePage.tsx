import { useState } from "react";

import { Toolbar } from "@/components/Toolbar";
import { Button, ChoiceGroup, ControlBar, GroupCheckbox, IconButton, SegmentedControl, StatusBadge, TabPanel, Tabs, ToolbarField } from "@/components/ui";
import { ArmButton } from "@/components/workbench/ArmButton";

/**
 * 共用控制項展示頁(只在開發模式掛路由;docs/ui-controls.md §6「已在元件展示頁找到同類範例」)。
 * 每一種用途列出 一般 / 選中 / 停用 / 處理中 / 再按一次(作廢按一下)/ 錯誤;切明暗主題、改視窗寬度都在這一頁看。不連後端、不寫任何資料。
 */
export function ControlsShowcasePage() {
  const [tab, setTab] = useState<"order" | "log" | "map">("order");
  const [way, setWay] = useState<"all" | "self" | "out">("all");
  const [store, setStore] = useState("");
  const [returnOnly, setReturnOnly] = useState(false);
  const [busy, setBusy] = useState(false);
  const [pay, setPay] = useState<string | null>("cash");
  const [stores, setStores] = useState<number[]>([1]);
  const [picked, setPicked] = useState<number[]>([1]);
  const toggle = (list: number[], v: number) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);
  return (
    <div className="page">
      <Toolbar title="共用控制項" />
      <div className="entry-body dev-controls">
        <section>
          <h3>執行動作 Button</h3>
          <div className="dev-row">
            <Button variant="primary">確認叫貨</Button>
            <Button>匯出</Button>
            <Button variant="danger">作廢</Button>
            <Button variant="text">清除條件</Button>
            <Button size="sm">編輯</Button>
            <Button size="lg" variant="primary">結帳</Button>
            <Button disabled>停用</Button>
            <Button
              variant="primary"
              pending={busy}
              pendingLabel="儲存中…"
              onClick={() => {
                setBusy(true);
                window.setTimeout(() => setBusy(false), 2000);
              }}
            >
              儲存
            </Button>
            <ArmButton label="作廢" className="btn danger" onConfirm={() => undefined} />
          </div>
        </section>
        <section>
          <h3>只有圖示 IconButton</h3>
          <div className="dev-row">
            <IconButton label="移除第 2 筆商品">×</IconButton>
            <IconButton label="關閉維修歷史">×</IconButton>
            <IconButton label="上一張照片">‹</IconButton>
            <IconButton label="下一張照片" disabled>
              ›
            </IconButton>
          </div>
        </section>
        <section>
          <h3>換工作區 Tabs</h3>
          <Tabs
            id="dev-tabs"
            label="廠商叫貨"
            value={tab}
            onChange={setTab}
            items={[
              { key: "order", label: "叫貨" },
              { key: "log", label: "紀錄", note: "3" },
              { key: "map", label: "對照", note: "2", noteTone: "alert" },
            ]}
          />
          <TabPanel id="dev-tabs" k="order" active={tab === "order"}>
            <p>叫貨的內容</p>
          </TabPanel>
          <TabPanel id="dev-tabs" k="log" active={tab === "log"}>
            <p>紀錄的內容</p>
          </TabPanel>
          <TabPanel id="dev-tabs" k="map" active={tab === "map"}>
            <p>對照的內容</p>
          </TabPanel>
        </section>
        <section>
          <h3>查詢工具列 ControlBar + ToolbarField + SegmentedControl + 勾選</h3>
          <ControlBar label="維修單篩選">
            <ToolbarField label="門市">
              <select value={store} onChange={(e) => setStore(e.target.value)}>
                <option value="">全部門市</option>
                <option value="a">巨城店</option>
                <option value="b">湳雅店</option>
              </select>
            </ToolbarField>
            <SegmentedControl
              label="維修方式"
              value={way}
              onChange={setWay}
              options={[
                { value: "all", label: "全部" },
                { value: "self", label: "自修" },
                { value: "out", label: "委外" },
              ]}
            />
            <label className="ui-tf">
              <input type="checkbox" checked={returnOnly} onChange={(e) => setReturnOnly(e.target.checked)} />
              <span>只看返修</span>
            </label>
            <Button>查詢</Button>
          </ControlBar>
        </section>
        <section>
          <h3>直接點的選項 ChoiceGroup(單選 / 多選)</h3>
          <div className="dev-row">
            <ChoiceGroup
              label="付款方式"
              value={pay}
              onChange={setPay}
              options={[
                { value: "cash", label: "現金" },
                { value: "card", label: "刷卡" },
                { value: "line", label: "LINE Pay" },
                { value: "off", label: "停用的", disabled: true },
              ]}
            />
          </div>
          <div className="dev-row">
            <ChoiceGroup
              multiple
              label="要看的門市"
              value={stores}
              onChange={(v) => setStores((l) => toggle(l, v))}
              options={[
                { value: 1, label: "湳雅店" },
                { value: 2, label: "民生店" },
                { value: 3, label: "巨城店" },
              ]}
            />
            <ChoiceGroup
              multiple
              size="sm"
              label="挑設備"
              value={picked}
              onChange={(v) => setPicked((l) => toggle(l, v))}
              options={[1, 2, 3].map((v) => ({ value: v, label: `…12${v}4`, title: `序號尾碼 12${v}4` }))}
            />
          </div>
          <div className="dev-row">
            <label className="ui-tf">
              <GroupCheckbox
                picked={picked.length}
                total={3}
                aria-label="全選 挑設備"
                onChange={() => setPicked(picked.length === 3 ? [] : [1, 2, 3])}
              />
              <span>全選(選一部分是半選)</span>
            </label>
          </div>
        </section>
        <section>
          <h3>狀態 StatusBadge(不能按)</h3>
          <div className="dev-row">
            <StatusBadge>一般</StatusBadge>
            <StatusBadge tone="warn">未開通</StatusBadge>
            <StatusBadge tone="danger">已停用</StatusBadge>
            <StatusBadge tone="info">限管理</StatusBadge>
            <StatusBadge tone="success">已存</StatusBadge>
          </div>
        </section>
      </div>
    </div>
  );
}
