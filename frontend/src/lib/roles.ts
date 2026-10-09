// 誰算管理員。畫面上「只有管理員能改」的地方都問這一支,名單跟後端 `tenants/permissions.py` 的 ADMIN_ROLES 同一份。
// 畫面只是不把按鈕給店員看;真正擋的是伺服器(店員自己送請求一樣被拒絕)。

export const MANAGER_ROLES: readonly string[] = ["tenant_admin", "platform_admin"];

/** 公司管理員或平台管理員。還不知道是誰(沒登入、資料還沒回來)一律當成不是。 */
export function isManager(role: string | null | undefined): boolean {
  return typeof role === "string" && MANAGER_ROLES.includes(role);
}
