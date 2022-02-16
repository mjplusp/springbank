# -*- coding: utf-8 -*-
import os, django
from celery import Celery
from celery.beat import crontab

# Celery 모듈을 위한 Django 기본세팅
if os.environ.get("DJANGO_MODE", "DEVELOP") == "DEPLOY":
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'springbank.settings_prod')
else:
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'springbank.settings')
    
app = Celery("config")
# 여기서 문자열을 사용하는것은 작업자가가 자식 프로세스 직렬화 구성을 하지 않는것을 의미
# -namespace='CELERY' 의 의미는 셀러리와 관련된 모든 설정은 CELERY_ 라는 prefix로 시작함을 의미
app.config_from_object("django.conf:settings", namespace="CELERY")

# Django 도 세팅한다.
django.setup()

# Django 에 등록된 모든 task 모듈을 로드
app.autodiscover_tasks()

from webapp import tasks


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):

    from django_celery_beat.models import PeriodicTask
    botName = 'Price_Detecting_Bot'

    if not PeriodicTask.objects.filter(name=botName).exists():
        
        sender.add_periodic_task(
            crontab(),
            tasks.priceDetectBotTask.s(),
            name = botName
        )

#     # 리밸런싱봇 : 매일 0/50, 8/50, 16/50 에 실행
#     sender.add_periodic_task(
#         crontab(minute="*/50", hour="0,8,16"),
#         tasks.rebalancingBotTask.s(),
#         name="rebalancing_bot",
#     )
#     print("Rebalancing Schedule Added")
    
#     # 청산방지 봇 : 매번 10분마다 실행.
#     sender.add_periodic_task(
#         crontab(),  # crontab(minute='*/10'),
#         tasks.liquidationPreventionBotTask.s(),
#         name="liquidation_prevention_bot",  # 청산 방지 봇
#     )
#     print("Liquidation Prevention Schedule Added")

# # NTP Bot 매 분마다 1번씩 실행.
    # sender.add_periodic_task(crontab(), tasks.ntpBotTask.s(), name="ntp_bot")
    # print("NTP Schedule Added")


    # 현재 더미
    # 정산 봇
    # 매일 새벽 2시에 실행.
    # sender.add_periodic_task(
    #   crontab(hour='2'),
    #   tasks.botTest.s("Bot Message"),
    #   name='calculate_bot'
    # )

    # print("Calculating Schedule Added")

    # 단순 테스트 # 매 1분 // 초는 안 되네
    # sender.add_periodic_task(
    #   crontab(minute='*/1'),
    #   tasks.botTest.s("Bot Message"),
    #   name='test_bot'
    # )
    # print("Test Bot Schedule Added")