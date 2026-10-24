import { useState } from "react";

import { Toolbar } from "@/components/Toolbar";
import { Button, ControlBar, IconButton, SegmentedControl, StatusBadge, TabPanel, Tabs, ToolbarField } from "@/components/ui";
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
              { key: "map", label: "對照" },
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
