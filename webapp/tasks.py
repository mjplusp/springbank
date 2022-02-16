from django_celery_beat import models
from springbank.celery_settings import app
from celery import shared_task
from bots import MainTradeBot_v3
from tools.LogicFunctions_v2 import LogicFunctions
from tools.PriceDetect_v2 import PriceDetector
from django_celery_beat.models import PeriodicTask, CrontabSchedule
from django.contrib.auth.models import User
from celery.exceptions import SoftTimeLimitExceeded

from celery.beat import crontab
import json
import logging
import time

logger = logging.getLogger("django")


# @shared_task
# def recordInitialPositionsBotTask(userId):
#     logger.info("==[Recording Positions Bot Triggered]==")
#     MainTradeBot_v3.recordInitialPositionsBot(userId=userId)

@shared_task
def botTest(args):
    logger.info("TEST")

@shared_task(time_limit=1800)
def enterPositionTask(username, symbol, notional_amount):
    lf = LogicFunctions(username)

    total_amt = float(notional_amount)
    atomic_amt = float(lf.minimumInvestmentNotional)
    

    while True:
        if total_amt >= atomic_amt:
            lf.enter_position(symbol, atomic_amt)
            logger.info("총 진입 투자금: %f, 잔여 투자 액수: %f" %(float(notional_amount), total_amt))
            total_amt = total_amt - atomic_amt
            time.sleep(1)
        else:
            break

@shared_task(time_limit=1800)
def leavePositionTask(username, symbol, notional_amount):
    lf = LogicFunctions(username)

    total_amt = float(notional_amount)
    atomic_amt = float(lf.minimumInvestmentNotional)

    while True:
        if total_amt >= atomic_amt:
            lf.leave_position(symbol, atomic_amt)
            logger.info("총 종료 투자금: %f, 잔여 종료 액수: %f" %(float(notional_amount), total_amt))
            total_amt = total_amt - atomic_amt
            time.sleep(1)
        else:
            break


@shared_task
def rebalancingBotTask(userId):
    logger.info("==[Rebalancing Bot Triggered]==")
    try:
        User.objects.get(username = userId)
        MainTradeBot_v3.rebalancingBot(userId=userId)
    except User.DoesNotExist as e:
        
        try:
            PeriodicTask.objects.get(name=getRebalancingBotName(userId)).delete()
            logger.info("==[%s Rebalancing Bot Deleted]==" %userId)
        except PeriodicTask.DoesNotExist:
            logger.info("==[%s Rebalancing Bot Already Deleted]==" %userId)     


@shared_task
def liquidationPreventionBotTask(userId):
    logger.info("==[Liquidation Prevention Bot Triggered]==")
    try:
        User.objects.get(username = userId)
        MainTradeBot_v3.liquidationPreventionBot(userId=userId)
    except User.DoesNotExist as e:
        
        try:
            PeriodicTask.objects.get(name=getLiquidationPreventionBotName(userId)).delete()
            logger.info("==[%s Liquidation Prevention Bot Deleted]==" %userId)
        except PeriodicTask.DoesNotExist:
            logger.info("==[%s Liquidation Prevention Bot Already Deleted]==" %userId)     


@shared_task
def assetRecordingBotTask(userId):
    logger.info("==[Asset Recording Bot Triggered]==")
    try:
        User.objects.get(username = userId)
        MainTradeBot_v3.assetRecordingBot(userId=userId)
    except User.DoesNotExist as e:
        
        try:
            PeriodicTask.objects.get(name=getAssetRecordingBotName(userId)).delete()
            logger.info("==[%s Asset Recording Bot Deleted]==" %userId)
        except PeriodicTask.DoesNotExist:
            logger.info("==[%s Asset Recording Bot Already Deleted]==" %userId)

@shared_task
def fundingFeeRecordingBotTask(userId):
    logger.info("==[Funding Fee Recording Bot Triggered]==")
    try:
        User.objects.get(username = userId)
        MainTradeBot_v3.fundingFeeRecordingBot(userId=userId)
    except User.DoesNotExist as e:
        
        try:
            PeriodicTask.objects.get(name=getFundingFeeRecordingBotName(userId)).delete()
            logger.info("==[%s Funding Fee Recording Bot Deleted]==" %userId)
        except PeriodicTask.DoesNotExist:
            logger.info("==[%s Funding Fee Recording Bot Already Deleted]==" %userId)


@shared_task
def ntpBotTask():
    logger.info("==[NTP Sync BOT Triggered]==")
    MainTradeBot_v3.ntpBot()

# @shared_task
# def priceDetectBotTask():
#     logger.info("==[Price Detect BOT Triggered]==")
#     PriceDetect.updatePriceDistribution()


# 봇마다 개인마다 동적으로 이름 할당
# 재분배, 투자봇
def getRebalancingBotName(userId):
    return userId + "_rebalancing_bot"


def getCrontabSchedule_RebalncingBot():
    try:
        schedule = CrontabSchedule.objects.get(minute="*/50", hour="0,8,16")
        return schedule
    except CrontabSchedule.DoesNotExist:
        schedule = CrontabSchedule(minute="*/50", hour="0,8,16")
        schedule.save()
        return schedule


def scheduleRebalancingBotTask(userId):
    botName = getRebalancingBotName(userId)
    if PeriodicTask.objects.filter(name=botName).exists():
        PeriodicTask.objects.get(name=botName).delete()

    PeriodicTask.objects.create(
        crontab=getCrontabSchedule_RebalncingBot(),
        name=botName,
        task="webapp.tasks.rebalancingBotTask",
        args=json.dumps([userId]),
        enabled=False,
    )


# 청산 방지봇
def getLiquidationPreventionBotName(userId):
    return userId + "_liquidationPrevention_bot"


def getCrontabSchedule_LiquidationPreventionBot():
    try:
        schedule = CrontabSchedule.objects.get(minute="*/10")
        return schedule
    except CrontabSchedule.DoesNotExist:
        schedule = CrontabSchedule(minute="*/10")
        schedule.save()
        return schedule


def scheduleLiquidationPreventionBotTask(userId):
    botName = getLiquidationPreventionBotName(userId)
    if PeriodicTask.objects.filter(name=botName).exists():
        PeriodicTask.objects.get(name=botName).delete()

    PeriodicTask.objects.create(
        # crontab=crontab(minute="*/50", hour="0,8,16"),
        crontab=getCrontabSchedule_LiquidationPreventionBot(),
        name=botName,
        task="webapp.tasks.liquidationPreventionBotTask",
        args=json.dumps([userId]),
        enabled=False,
    )


# 자산 기록봇
def getAssetRecordingBotName(userId):
    return userId + "_assetRecording_bot"


def getCrontabSchedule_AssetRecordingBot():
    try:
        schedule = CrontabSchedule.objects.get(minute="0", hour = '*')
        return schedule
    except CrontabSchedule.DoesNotExist:
        schedule = CrontabSchedule(minute="0")
        schedule.save()
        return schedule


def scheduleAssetRecordingBotTask(userId):
    botName = getAssetRecordingBotName(userId)
    if PeriodicTask.objects.filter(name=botName).exists():
        PeriodicTask.objects.get(name=botName).delete()

    PeriodicTask.objects.create(
        # crontab=crontab(minute="*/50", hour="0,8,16"),
        crontab=getCrontabSchedule_AssetRecordingBot(),
        name=botName,
        task="webapp.tasks.assetRecordingBotTask",
        args=json.dumps([userId]),
        enabled=False,
    )

# 자산 기록봇
def getFundingFeeRecordingBotName(userId):
    return userId + "_fundingFeeRecording_bot"


def getCrontabSchedule_FundingFeeRecordingBot():
    try:
        schedule = CrontabSchedule.objects.get(minute="1", hour="1,9,17")
        return schedule
    except CrontabSchedule.DoesNotExist:
        schedule = CrontabSchedule(minute="1", hour="1,9,17")
        schedule.save()
        return schedule


def scheduleFundingFeeRecordingBotTask(userId):
    botName = getFundingFeeRecordingBotName(userId)
    if PeriodicTask.objects.filter(name=botName).exists():
        PeriodicTask.objects.get(name=botName).delete()

    PeriodicTask.objects.create(
        # crontab=crontab(minute="*/50", hour="0,8,16"),
        crontab=getCrontabSchedule_FundingFeeRecordingBot(),
        name=botName,
        task="webapp.tasks.fundingFeeRecordingBotTask",
        args=json.dumps([userId]),
        enabled=False,
    )