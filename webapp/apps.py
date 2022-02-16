from django.apps import AppConfig
import sys


class WebappConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "webapp"

    def ready(self):
        # 커스터마이즈. runserver 일때만 배치가 돌도록 조치
        if "runserver" in sys.argv:
            setInitialPermissionData()
            startPriceDetectorBatch()
        else:
            return


def setInitialPermissionData():
    from django.contrib.auth.models import Group, Permission

    # 앱 ready 시점에서 그룹 추가 1회 실행
    springbank, created = Group.objects.get_or_create(name="Springbank_Quant_Staff")

    if created:
        # # Now what - Say I want to add 'Can add project' permission to new_group?
        permissions = [
            Permission.objects.get(codename="view_asset"),
            Permission.objects.get(codename="change_botproperties"),
            Permission.objects.get(codename="view_botproperties"),
            Permission.objects.get(codename="change_botpropertiesadvanced"),
            Permission.objects.get(codename="view_botpropertiesadvanced"),
            Permission.objects.get(codename="view_incomefunding"),
            Permission.objects.get(codename="view_incomecapital"),
            Permission.objects.get(codename="add_targetcoin"),
            Permission.objects.get(codename="view_targetcoin"),
            Permission.objects.get(codename="delete_targetcoin"),
            Permission.objects.get(codename="change_targetcoin"),
            Permission.objects.get(codename="change_userdetail"),
            Permission.objects.get(codename="view_userdetail"),
            Permission.objects.get(codename="view_usersummary"),
        ]
        springbank.permissions.add(*permissions)


def startPriceDetectorBatch():
    from webapp.batch import PriceDetector

    PriceDetector.startPriceDetector()
