/** 密碼的規則(跟伺服器 apps/tenants/auth_views.py 的 MIN_PASSWORD_LENGTH 同一條)。伺服器才是真的擋的那一個。 */
export const MIN_PASSWORD_LENGTH = 4;

/** 一個新密碼本身哪裡不行(老闆重設店員密碼也用這一條);可以就回空字串 */
export function passwordProblem(next: string): string {
  if (next.length < MIN_PASSWORD_LENGTH) return `新密碼至少 ${MIN_PASSWORD_LENGTH} 碼`;
  // 登入那一格會把前後的空白去掉,存了就登不進去
  if (next !== next.trim()) return "密碼前後不能有空白";
  return "";
}

/** 改自己的密碼那一頁:哪裡還不能送;可以送就回空字串 */
export function changeProblem(current: string, next: string, again: string): string {
  if (!current) return "請輸入目前的密碼";
  const bad = passwordProblem(next);
  if (bad) return bad;
  if (next === current) return "新密碼跟目前的一樣";
  if (again !== next) return "兩次輸入的新密碼不一樣";
  return "";
}
