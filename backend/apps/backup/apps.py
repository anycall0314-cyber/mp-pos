from pathlib import Path

from django.apps import AppConfig
from django.core import checks


def _inside(child, parent) -> bool:
    child, parent = Path(child).resolve(), Path(parent).resolve()
    return child == parent or parent in child.parents


@checks.register(checks.Tags.security)
def backup_root_is_private(app_configs, **kwargs):
    """備份目錄跟媒體 / 靜態檔目錄不能互相包含。

    備份檔裡有會員與維修資料;放進會被網頁伺服器直接送出去的目錄,等於繞過
    下載端點的權限檢查。
    """
    from django.conf import settings

    root = getattr(settings, "BACKUP_ROOT", None)
    if not root:
        return [checks.Error("BACKUP_ROOT 沒有設定", id="backup.E001")]
    problems = []
    for name in ("MEDIA_ROOT", "STATIC_ROOT"):
        other = getattr(settings, name, None)
        if other and (_inside(root, other) or _inside(other, root)):
            problems.append(checks.Error(
                f"BACKUP_ROOT({root})跟 {name}({other})重疊。備份檔不能放在會被"
                "網頁伺服器直接送出的目錄。",
                id="backup.E002",
            ))
    return problems


class BackupConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.backup"
    verbose_name = "公司備份與還原"
