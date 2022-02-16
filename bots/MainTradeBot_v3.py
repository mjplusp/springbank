from tools.LogicFunctions_v2 import LogicFunctions
from webapp import models
import time
import datetime
import logging
from tools import NTP

logger = logging.getLogger("django")

##### 이니셜라이즈 봇! #####
def rebalancingBot(userId):
    # logger.info("========== 재분배 봇 동작 ===========")

    lf = LogicFunctions(userId)

    logger.info("[STEP 1] : [신규투자] ===============================")
    #### 메인 로직을 여기다가 짤 것
    lf.binanceApiWrappers.updateAccountStatus()
    logger.info("투자 코인 목록: ", lf.newInvestmentCoinPairs)

    # 투자 전에 혹시 추가된 코인이 있을 수 있으니 격리마진 및 레버리지 재산정
    for coins in list(set(lf.targetCoinPairs + lf.newInvestmentCoinPairs)):
        lf.binanceApiWrappers.setSymbolLeverage(coins, lf.leverage)
        lf.binanceApiWrappers.setMarginType(coins, "ISOLATED")

    lf.investResidualUSDT()

    # 선/현물 개수 Sync 맞추기
    logger.info("[STEP 2] : [코인개수 동기화] ===========================")
    lf.binanceApiWrappers.updateAccountStatus()
    lf.syncSpotFuturesQty()


def liquidationPreventionBot(userId):
    # logger.info("========== 청산방지 봇 동작 ===========")
    lf = LogicFunctions(userId)

    lf.binanceApiWrappers.updateAccountStatus()
    lf.readBotProperties()
    totalBalanceInfo = lf.binanceApiWrappers.getTotalBalanceInfo()

    while True:
        logger.info("[담보비율 확인 / 청산 방지] ================")
        repeatflag = False  # 이게 True로 바뀌면 한번 더돌면서 delta 만큼 마진 추가

        logger.info("현재 서버 시간: %s" % str(lf.getServerTimeObject()))
        lf.readBotProperties()
        logger.info("관리 코인 목록: %s" % str(lf.targetCoinPairs))
        logger.info("<담보 비율>")

        lf.binanceApiWrappers.updateAccountStatus()
        futurePos = lf.binanceApiWrappers.getCurrentFuturesPositions().get("positions")

        for coin in list(set(lf.targetCoinPairs + lf.newInvestmentCoinPairs)):
            if futurePos.get(coin) != None:  # 이게 None이면 아무 포지션이 없다는 말
                collateralRatio = float(futurePos.get(coin).get("collateralRatio"))
                # 담보비율 업데이트
                models.CollateralRatio.objects.update_or_create(user=lf.userObject, symbol=str(coin), defaults={'collateral_ratio':collateralRatio})

                logger.info("\t%s 담보비율:\t%s" % (str(coin), str(collateralRatio)))

                if collateralRatio < lf.threshold_margin_lower:
                    logger.info("\t>> %s 마진조정 실행" % str(coin))
                    lf.increaseMargin(coin, lf.marginDelta)

                    repeatflag = True
            else:
                logger.info("\t %s 포지션 없음" % (coin))
                try:
                    need_to_delete_instance = models.CollateralRatio.objects.get(user=lf.userObject, symbol=str(coin))
                    need_to_delete_instance.delete()
                except models.CollateralRatio.DoesNotExist as Error:
                    continue

        if repeatflag:
            continue
        else:
            break


def ntpBot():

    # difference = NTP.getNTPtime(domain = 'time.google.com', time_threshold = 0.1, verbose = True, retry = False)
    # if difference.get('needServertimeSync'):
    #   NTP._linux_set_time(difference.get('ntpTime'))

    NTP.adjustTime(time_threshold=0.1, verbose=False)

def assetRecordingBot(userId):
    # logger.info("========== 자산 기록 봇 동작 ===========")

    lf = LogicFunctions(userId)
    lf.saveAssetSnapshot()

def fundingFeeRecordingBot(userId):
    # logger.info("========== 자산 기록 봇 동작 ===========")

    lf = LogicFunctions(userId)
    lf.save_funding_income()
