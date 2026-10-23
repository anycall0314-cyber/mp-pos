import { ReactNode, useContext } from "react";
import { createPortal } from "react-dom";

import { ModuleActionsSlot } from "@/components/shell/moduleActions";

interface ToolbarProps {
  title?: string;
  actions?: ReactNode;
  children?: ReactNode;
}

export function Toolbar({ title, actions, children }: ToolbarProps) {
  // 上面有分頁列(而且正在看分頁本身):不再多一排大標題,按鈕放到分頁列最右邊;頁內的篩選 / 小分頁照舊留在這一排
  const slot = useContext(ModuleActionsSlot);
  if (slot) {
    return (
      <>
        {actions ? createPortal(<div className="page-toolbar-actions">{actions}</div>, slot) : null}
        {children ? (
          <div className="page-toolbar slim">
            <div className="page-toolbar-mid">{children}</div>
          </div>
        ) : null}
      </>
    );
  }
  return (
    <div className="page-toolbar">
      {title && <div className="page-title">{title}</div>}
      <div className="page-toolbar-mid">{children}</div>
      <div className="page-toolbar-actions">{actions}</div>
    </div>
  );
}
