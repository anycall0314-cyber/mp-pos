"""建立首位平台管理員(或把現有 superuser 升級為 platform_admin)。

用法:
    # 建新帳號
    python manage.py bootstrap_platform_admin --username admin --password xxx

    # 為現有 superuser 加上 platform_admin profile
    python manage.py bootstrap_platform_admin --username admin

實作邏輯:
    1. 帳號不存在 → 建一個 superuser
    2. UserProfile 不存在 → 建一個 role=platform_admin
    3. 已存在 → 印出狀態
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from apps.tenants.models import UserProfile


class Command(BaseCommand):
    help = "建立首位平台管理員(或升級現有 superuser)"

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument(
            "--password",
            help="新帳號的密碼;若 user 已存在則不需要也不會被改",
        )
        parser.add_argument(
            "--email",
            default="",
            help="可選的 email",
        )

    def handle(self, *args, **opts):
        username = opts["username"]
        password = opts.get("password")
        email = opts["email"]

        user = User.objects.filter(username=username).first()
        if user is None:
            if not password:
                raise CommandError(
                    f"使用者 {username} 不存在,需要 --password 才能建立"
                )
            user = User.objects.create_superuser(
                username=username, email=email, password=password
            )
            self.stdout.write(self.style.SUCCESS(f"建立 superuser:{username}"))
        else:
            self.stdout.write(f"使用既有 user:{username}")

        profile, created = UserProfile.objects.get_or_create(
            user=user,
            defaults={
                "role": UserProfile.Role.PLATFORM_ADMIN,
                "tenant": None,
                "is_warehouse_locked": False,
            },
        )
        if not created and profile.role != UserProfile.Role.PLATFORM_ADMIN:
            profile.role = UserProfile.Role.PLATFORM_ADMIN
            profile.tenant = None
            profile.is_warehouse_locked = False
            profile.save()
            self.stdout.write(
                self.style.SUCCESS(f"已將 {username} 升級為 platform_admin")
            )
        elif created:
            self.stdout.write(
                self.style.SUCCESS(f"已建立 platform_admin profile")
            )
        else:
            self.stdout.write(f"{username} 已是 platform_admin,無需動作")

        self.stdout.write(
            self.style.SUCCESS(
                f"\n完成。可以用以下 curl 取得 token:\n"
                f"  curl -X POST http://localhost:8000/api/v1/auth/login/ \\\n"
                f"    -H 'Content-Type: application/json' \\\n"
                f"    -d '{{\"username\":\"{username}\",\"password\":\"<密碼>\"}}'"
            )
        )
