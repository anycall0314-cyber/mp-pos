import { ReactNode } from "react";

interface ToolbarProps {
  title?: string;
  actions?: ReactNode;
  children?: ReactNode;
}

export function Toolbar({ title, actions, children }: ToolbarProps) {
  return (
    <div className="page-toolbar">
      {title && <div className="page-title">{title}</div>}
      <div className="page-toolbar-mid">{children}</div>
      <div className="page-toolbar-actions">{actions}</div>
    </div>
  );
}
