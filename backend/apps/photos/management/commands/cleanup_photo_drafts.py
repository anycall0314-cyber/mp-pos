from django.core.management.base import BaseCommand

from apps.photos.services import cleanup


class Command(BaseCommand):
    help = "清掉結束一陣子、或放太久沒存的商品照片作業(連同還沒掛到商品的暫存檔)"

    def handle(self, *args, **options):
        self.stdout.write(f"清掉 {cleanup()} 份照片作業")
