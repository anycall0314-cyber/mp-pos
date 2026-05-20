import { useEffect, useState } from "react";

import { useCategories, useSaveCategory } from "@/api/hooks";
import type { Category } from "@/api/types";
import { Banner } from "@/components/Banner";
import { Toolbar } from "@/components/Toolbar";

interface EditState {
  code: string;
  name: string;
  is_active: boolean;
}

interface NewCatState {
  code: string;
  name: string;
  sort_order: string; // 字串以便顯示空白為「自動」
}

const EMPTY_NEW: NewCatState = { code: "", name: "", sort_order: "" };

export function CategoriesPage() {
  const { data } = useCategories();
  const saveCategory = useSaveCategory();

  // 本地顯示列表(拖拉時立即更新,送 API 為背景)
  const [items, setItems] = useState<Category[]>([]);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editData, setEditData] = useState<EditState>({
    code: "",
    name: "",
    is_active: true,
  });
  const [draggingId, setDraggingId] = useState<number | null>(null);
  const [dragOverId, setDragOverId] = useState<number | null>(null);

  const [showNew, setShowNew] = useState(false);
  const [newCat, setNewCat] = useState<NewCatState>(EMPTY_NEW);

  const [error, setError] = useState<string | null>(null);

  // 從 API 載入時同步 items(排除正在編輯的情境,避免覆蓋使用者輸入)
  useEffect(() => {
    if (!data || editingId != null) return;
    const sorted = [...data].sort(
      (a, b) => a.sort_order - b.sort_order || a.code.localeCompare(b.code),
    );
    setItems(sorted);
  }, [data, editingId]);

  function onDragStart(e: React.DragEvent, id: number) {
    setDraggingId(id);
    e.dataTransfer.effectAllowed = "move";
    // 必須 setData 才能在某些瀏覽器跑得起來
    e.dataTransfer.setData("text/plain", String(id));
  }

  function onDragOver(e: React.DragEvent, id: number) {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    if (dragOverId !== id) setDragOverId(id);
  }

  function onDragLeave() {
    setDragOverId(null);
  }

  async function onDrop(e: React.DragEvent, targetId: number) {
    e.preventDefault();
    const src = draggingId;
    setDraggingId(null);
    setDragOverId(null);
    if (src == null || src === targetId) return;

    const fromIdx = items.findIndex((x) => x.id === src);
    const toIdx = items.findIndex((x) => x.id === targetId);
    if (fromIdx < 0 || toIdx < 0) return;

    const arr = [...items];
    const [removed] = arr.splice(fromIdx, 1);
    arr.splice(toIdx, 0, removed);
    // 重新發號:10, 20, 30, ...
    const renumbered = arr.map((c, i) => ({ ...c, sort_order: (i + 1) * 10 }));
    setItems(renumbered);

    // 找出排序變動的,平行 PATCH
    const changed = renumbered.filter((c, i) => {
      const before = items[i];
      return !before || before.id !== c.id || before.sort_order !== c.sort_order;
    });
    try {
      await Promise.all(
        changed.map((c) =>
          saveCategory.mutateAsync({ id: c.id, sort_order: c.sort_order }),
        ),
      );
    } catch (err) {
      setError("排序儲存失敗,請重新整理頁面");
    }
  }

  function startEdit(c: Category) {
    setError(null);
    setEditingId(c.id);
    setEditData({
      code: c.code,
      name: c.name,
      is_active: c.is_active,
    });
  }

  function cancelEdit() {
    setEditingId(null);
    setError(null);
  }

  async function saveEdit() {
    if (editingId == null) return;
    const c = items.find((x) => x.id === editingId);
    if (!c) return;
    try {
      await saveCategory.mutateAsync({
        id: editingId,
        code: editData.code.toUpperCase(),
        name: editData.name,
        is_active: editData.is_active,
      });
      setEditingId(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "儲存失敗");
    }
  }

  async function createNew() {
    if (!newCat.code.trim() || !newCat.name.trim()) {
      setError("代碼與名稱必填");
      return;
    }
    const explicit = Number(newCat.sort_order);
    const sort_order =
      Number.isFinite(explicit) && explicit > 0
        ? explicit
        : items.length > 0
        ? Math.max(...items.map((c) => c.sort_order)) + 10
        : 10;
    try {
      await saveCategory.mutateAsync({
        code: newCat.code.trim().toUpperCase(),
        name: newCat.name.trim(),
        sort_order,
      });
      setNewCat(EMPTY_NEW);
      setShowNew(false);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "新增失敗");
    }
  }

  return (
    <div className="page">
      <Toolbar
        title="類別管理"
        actions={
          <button
            className="btn primary"
            onClick={() => {
              setShowNew((v) => !v);
              setError(null);
            }}
          >
            {showNew ? "取消新類別" : "+ 新類別"}
          </button>
        }
      />
      {error && <Banner kind="error" message={error} />}

      {showNew && (
        <div className="list-filterbar">
          <label>
            代碼
            <input
              value={newCat.code}
              onChange={(e) =>
                setNewCat((s) => ({ ...s, code: e.target.value.toUpperCase() }))
              }
              maxLength={8}
              placeholder="例:PH"
              autoFocus
            />
          </label>
          <label>
            名稱
            <input
              value={newCat.name}
              onChange={(e) =>
                setNewCat((s) => ({ ...s, name: e.target.value }))
              }
              maxLength={80}
              placeholder="例:手機"
            />
          </label>
          <label>
            排序(留空自動)
            <input
              type="number"
              step="1"
              value={newCat.sort_order}
              onChange={(e) =>
                setNewCat((s) => ({ ...s, sort_order: e.target.value }))
              }
              placeholder="自動"
              style={{ width: 100 }}
            />
          </label>
          <button
            className="btn primary"
            onClick={createNew}
            disabled={saveCategory.isPending}
          >
            建立
          </button>
        </div>
      )}

      <div className="md-table category-mgr">
        <table>
          <thead>
            <tr>
              <th style={{ width: 32 }}></th>
              <th style={{ width: 70 }} className="num">
                排序
              </th>
              <th style={{ width: 110 }}>代碼</th>
              <th>名稱</th>
              <th style={{ width: 80, textAlign: "center" }}>啟用</th>
              <th style={{ width: 160, textAlign: "center" }}>動作</th>
            </tr>
          </thead>
          <tbody>
            {items.map((c) => {
              const isEditing = editingId === c.id;
              return (
                <tr
                  key={c.id}
                  draggable={!isEditing}
                  onDragStart={(e) => onDragStart(e, c.id)}
                  onDragOver={(e) => onDragOver(e, c.id)}
                  onDragLeave={onDragLeave}
                  onDrop={(e) => onDrop(e, c.id)}
                  onDragEnd={() => {
                    setDraggingId(null);
                    setDragOverId(null);
                  }}
                  className={[
                    draggingId === c.id ? "row-dragging" : "",
                    dragOverId === c.id && draggingId !== c.id
                      ? "row-drag-over"
                      : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  style={{ cursor: isEditing ? "default" : "grab" }}
                >
                  <td className="drag-handle" title="拖拉重排">
                    {isEditing ? "" : "≡"}
                  </td>
                  <td className="num">{c.sort_order}</td>
                  <td>
                    {isEditing ? (
                      <input
                        value={editData.code}
                        onChange={(e) =>
                          setEditData((s) => ({
                            ...s,
                            code: e.target.value.toUpperCase(),
                          }))
                        }
                        maxLength={8}
                        style={{ width: 80 }}
                      />
                    ) : (
                      c.code
                    )}
                  </td>
                  <td>
                    {isEditing ? (
                      <input
                        value={editData.name}
                        onChange={(e) =>
                          setEditData((s) => ({ ...s, name: e.target.value }))
                        }
                        maxLength={80}
                      />
                    ) : (
                      c.name
                    )}
                  </td>
                  <td style={{ textAlign: "center" }}>
                    {isEditing ? (
                      <input
                        type="checkbox"
                        checked={editData.is_active}
                        onChange={(e) =>
                          setEditData((s) => ({
                            ...s,
                            is_active: e.target.checked,
                          }))
                        }
                      />
                    ) : c.is_active ? (
                      "✓"
                    ) : (
                      <span style={{ color: "var(--text-dim)" }}>停用</span>
                    )}
                  </td>
                  <td style={{ textAlign: "center" }}>
                    {isEditing ? (
                      <>
                        <button
                          className="btn primary"
                          onClick={saveEdit}
                          disabled={saveCategory.isPending}
                          style={{ marginRight: 6 }}
                        >
                          儲存
                        </button>
                        <button className="btn" onClick={cancelEdit}>
                          取消
                        </button>
                      </>
                    ) : (
                      <button className="btn" onClick={() => startEdit(c)}>
                        編輯
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
            {items.length === 0 && (
              <tr>
                <td colSpan={6} className="md-empty">
                  尚無類別,點右上方「+ 新類別」開始建立
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
