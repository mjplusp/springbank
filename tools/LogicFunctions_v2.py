from decimal import Decimal as dec
from typing import DefaultDict
import numpy
import time
import sys
import tools.LogicFuncionApi as LogicFuncionApi

sys.path.append("./")
# from bot_v2.BinanceApiWrappers import BinanceApiWrappers
from tools.BinanceApiWrappers_v2 import BinanceApiWrappers
from datetime import datetime, date
from dateutil import tz
from webapp import models
from django.contrib.auth.models import User
from exceptions import botExcpetions
from django.db import transaction
from django.utils import timezone


import logging

logger = logging.getLogger("django")


class LogicFunctions:
    def __init__(self, userId):
        self.userObject = User.objects.get(username=userId)
        self.userDetail = models.UserDetail.objects.get(user=self.userObject)

        self.binanceApiWrappers = BinanceApiWrappers(
            self.userDetail
        )
        self.binance = self.binanceApiWrappers.apiManager.binance
        self.futureBinance = self.binanceApiWrappers.apiManager.futureBinance

        self.readBotProperties()

    ########################################################################################
    # 1. 자릿수 조정, Legal Order 생성 등 전처리작업 함수
    ########################################################################################
    # 설정값 읽어오기

    def readBotProperties(self):
        try:
            # bot properties 먼저 세팅
            botpropertiesSet = self.userObject.botproperties  # _set.all()
            if not (botpropertiesSet):
                raise botExcpetions.NoBotPropertiesException
            else:
                self.setBotProperties(botpropertiesSet)

            # 다음으로 bot properties Advaced 세팅
            botpropertiesAdvancedSet = (
                self.userObject.botpropertiesadvanced
            )  # _set.all()
            if not (botpropertiesAdvancedSet):
                raise botExcpetions.NoBotPropertiesAdvancedException
            else:
                self.setBotPropertiesAdvanced(botpropertiesAdvancedSet)

            # 마지막으로 target coin 세팅
            self.setTatgetCoin(self.userObject.targetcoin_set.all())

        except models.User.DoesNotExist as e:
            raise e

    def setBotProperties(self, botProperties):
        # 봇이 돌아가는 주기 (seconds)
        self.bot_interval = (
            botProperties.liquidation_bot_interval
        )  # 봇이 돌아가는 주기 (seconds)
        self.fundingOptimizationMinute = botProperties.funding_optimization_minute
        self.leverage = botProperties.leverage  # 레버리지

    def setBotPropertiesAdvanced(self, botPropertiesAdvanced):
        # 상방 제한 증거금 비율 (추후 레버리지와 연동)'
        self.threshold_margin_upper = botPropertiesAdvanced.margin_upper_bound
        # 하방 제한 증거금 비율 (추후 레버리지와 연동)
        self.threshold_margin_lower = botPropertiesAdvanced.margin_lower_bound
        # 1회의 반복에서 Rebalancing 하는 자산의 비율
        self.marginDelta = botPropertiesAdvanced.margin_delta
        # usdt를 관리할 소수점
        self.usdtDecimal = botPropertiesAdvanced.usdt_decimal
        # Spot 지갑에 항상 남겨둘 USDT 비율 (총 자산 기준)
        self.usdtReserveRatio = botPropertiesAdvanced.usdt_reserve_ratio
        # 이 수량의 USDT 단위로 투자가 됨 (현물 + 선물의 Notional USDT
        self.minimumInvestmentNotional = botPropertiesAdvanced.minimum_investment
        # 급격한 가격변동에 주문이 실패하지 않도록 주문 가능 개수에 이 비율을 곱해서 최종 주문을 넣음
        self.safeInvestmentRatio = botPropertiesAdvanced.safe_investment_ratio
        # Premium Index들의 표준편차를 구할 때 사용되는 데이터 수 (분 단위)
        self.premiumIndexWindow = botPropertiesAdvanced.deviation_window
        # 몇 sigma 보다 큰 premium index를 보일 때 long/short 포지션 진입할 지 선택
        self.premiumIndexTriggerSigma = botPropertiesAdvanced.threshold_sigma

    def setTatgetCoin(self, targetCoins):
        self.targetCoinPairs = []
        self.newInvestmentCoinPairs = []

        for targetCoin in targetCoins:
            self.targetCoinPairs.append(targetCoin.symbol)
            if targetCoin.is_investing:
                self.newInvestmentCoinPairs.append(targetCoin.symbol)

    # usdt amount를 원하는 자리수까지 trim (내림)
    def trimUSDTAmount(self, amount):
        amount = dec(str(amount))
        trimmer = dec(str(self.usdtDecimal))
        return str((amount // trimmer) * trimmer)

    # trimUSDTAmount(1.2342)
    # '1.23'

    # 코인의 현재 usdt 가격 조회하는 함수 (수수료가 코인으로 나갈 경우 현가 계산을 위함)
    def getCurrentCoinPrice(self, symbol):
        tickers = self.binance.public_get_ticker_price()
        return str(
            dec(
                next(
                    filter(lambda l: l.get("symbol") == symbol, tickers), {"price": "1"}
                ).get("price")
            )
        )

    # 주문가능하도록 코인 수량 정보 조절
    def adjustOrderQuantity(self, symbol, coin_quantity):
        legalOrdersInfo = self.binanceApiWrappers.getSingleLegalOrdersInfo(symbol)
        minQty = dec(legalOrdersInfo.get("minOrderQty"))
        minNotional = dec(legalOrdersInfo.get("minNotional"))
        stepSize = dec(legalOrdersInfo.get("stepSize"))

        coin_quantity = dec(str(coin_quantity))
        avgPrice = dec(self.binanceApiWrappers.getAvgPrice5min(symbol).get("price"))

        if minQty > coin_quantity:
            return self.adjustOrderQuantity(symbol, str(minQty))
        elif minNotional > coin_quantity * avgPrice:
            newQty = ((minNotional / avgPrice) // stepSize) * stepSize + stepSize
            return self.adjustOrderQuantity(symbol, str(newQty))
        else:
            adjustedQuantity = (
                (coin_quantity - minQty) // stepSize
            ) * stepSize + minQty
            return {"symbol": symbol, "amount": str(adjustedQuantity)}

    # adjustOrderQuantity('DOGEUSDT', '10.80301')
    # {'symbol': 'DOGEUSDT', 'amount': '21'}

    # 선물지갑의 usdt 짤짤이들 spot 지갑으로 이동
    def cleanFuturesUSDT(self):
        self.binanceApiWrappers.updateAccountStatus()
        futuresUSDTBalance = (
            self.binanceApiWrappers.getCurrentFuturesPositions()
            .get("assets")
            .get("USDT")
        )
        movingUSDT = self.trimUSDTAmount(futuresUSDTBalance)
        if dec(movingUSDT) > dec("0"):
            logger.info(
                "\t>> 선물 지갑의 잔여 USDT를 SPOT 지갑으로 이동. 이동 금액: %s USDT" % (movingUSDT)
            )
            return self.binanceApiWrappers.transferFromUsdtMToSpot(movingUSDT)
        # else: print('no money to transfer')

    # 선물 포지션을 가지고 있는지 조회하는 함수
    def hasPosition(self, symbol):
        return bool(
            self.binanceApiWrappers.getTotalBalanceInfo()
            .get("futures")
            .get("positions")
            .get(symbol)
        )
        # return float(self.binanceApiWrappers.getPositionRisk(symbol).get("positionAmt")) != 0

    # 현물 자산을 가지고 있는지 조회하는 함수
    def hasAsset(self, symbol):
        asset = symbol.replace("USDT", "")
        return bool(
            self.binanceApiWrappers.getTotalBalanceInfo()
            .get("spot")
            .get("assets")
            .get(asset)
        )

    # 선물과 현물 진입 포지션들의 수량 차이를 조회하는 함수 (spotDeficit이 True라면 현물을 더 작은 수량만큼 가지고 있다는 뜻, False라면 현물을 더 큰 수량만큼 가지고 있다는 뜻)
    def spotFuturesDifference(self, symbol):
        if self.hasPosition(symbol) and self.hasAsset(symbol):

            asset = symbol.replace("USDT", "")
            spotBalance = (
                self.binanceApiWrappers.getTotalBalanceInfo()
                .get("spot")
                .get("assets")
                .get(asset)
                .get("qty")
            )
            futuresBalance = (
                self.binanceApiWrappers.getTotalBalanceInfo()
                .get("futures")
                .get("positions")
                .get(symbol)
                .get("positionAmt")
            )

            return {
                "symbol": symbol,
                "spotDeficit": True
                if dec(spotBalance) < dec(futuresBalance) * dec("-1")
                else False,
                "difference": str(abs(dec(spotBalance) + dec(futuresBalance))),
            }
        else:
            logger.info("동시 진입 포지션이 없음")
            return {"symbol": symbol, "spotDeficit": False, "difference": "0"}

    # 선물/현물 포지션 숫자를 조회해, 해당 차이가 주문가능한 Threshold보다 크다면 현물 수량을 조절해 현/선물 수량을 맞추는 함수 (주문이 들어가기에 여유자금이 있어야 함)
    def syncSpotFuturesQty(self):
        syncResult = {}
        for symbol in self.targetCoinPairs:
            difference = self.spotFuturesDifference(symbol)
            differenceAmt = difference.get("difference")
            thresholdAmt = self.adjustOrderQuantity(symbol, "0").get("amount")

            if dec(differenceAmt) > dec(thresholdAmt):
                logger.info(
                    "\t%s\t현/선물 수량 차이 조절 필요.\t 차이: %s,\t최소 주문 가능: %s"
                    % (symbol, differenceAmt, thresholdAmt)
                )

                if difference.get(
                    "spotDeficit"
                ):  # spotDeficit이 True라면 Spot이 Futures보다 작은 상태이므로 현물 추가구입
                    buyAmt = self.adjustOrderQuantity(
                        symbol, str(dec(differenceAmt) / dec("0.999"))
                    ).get("amount")
                    spotBuyOrderNo = self.binanceApiWrappers.orderSpotBuy(
                        symbol, buyAmt
                    ).get(
                        "orderId"
                    )  # API 호출

                    orderlist = [
                        {
                            "order_id": spotBuyOrderNo,
                            "symbol": symbol,
                            "is_spot": True,
                            "is_buyer": True,
                        }
                    ]
                    # 실행 결과 저장
                    spotBuySummary = self.save_action(
                        action_type="COIN_SYNC", symbol=symbol, orders=orderlist
                    )
                    syncResult[symbol] = spotBuySummary

                else:  # spotDeficit이 False라면 Spot이 Futures보다 큰 상태이므로 현물 매도
                    sellAmt = self.adjustOrderQuantity(symbol, differenceAmt).get(
                        "amount"
                    )
                    spotSellOrderNo = self.binanceApiWrappers.orderSpotSell(
                        symbol, sellAmt
                    ).get(
                        "orderId"
                    )  # API 호출

                    orderlist = [
                        {
                            "order_id": spotSellOrderNo,
                            "symbol": symbol,
                            "is_spot": True,
                            "is_buyer": False,
                        }
                    ]
                    # 실행 결과 저장
                    spotSellSummary = self.save_action(
                        action_type="COIN_SYNC", symbol=symbol, orders=orderlist
                    )
                    syncResult[symbol] = spotSellSummary
            else:
                logger.info(
                    "\t%s\t현/선물 수량 차이 조절 불필요.\t 차이: %s,\t최소 주문 가능: %s"
                    % (symbol, differenceAmt, thresholdAmt)
                )

        return syncResult

    ########################################################################################
    # 2. 주문번호 바탕으로 거래 내역 정보 읽어오는 함수
    ########################################################################################

    # 현물 long/short 결과에서 판매대금과 commission 읽어오기
    def spotOrderSummary(self, symbol, orderId, isBuyer=True):
        (coinIncome, usdtIncome, commission) = (dec("0"), dec("0"), dec("0"))
        buyerFlag = dec("1") if isBuyer else dec("-1")

        tradeResult = self.binanceApiWrappers.apiManager.binance.private_get_mytrades(
            {"symbol": symbol, "orderId": orderId}
        )
        for elements in tradeResult:
            coinIncome = coinIncome + (dec(elements.get("qty")) * buyerFlag)
            usdtIncome = usdtIncome - (dec(elements.get("quoteQty")) * buyerFlag)
            commission = commission + dec(elements.get("commission"))

        logger.info(
            "\t\t[%s Spot] Asset: %s, Coin: %s, USDT: %s, orderNo: %s"
            % (
                "Long" if isBuyer else "Short",
                symbol,
                str(coinIncome - commission) if isBuyer else str(coinIncome),
                str(usdtIncome) if isBuyer else str(usdtIncome - commission),
                orderId,
            )
        )

        return {
            "usdtIncome": str(usdtIncome),
            "coinIncome": str(coinIncome),
            "commission": str(commission),
            "netUSDTIncome": str(usdtIncome)
            if isBuyer
            else str(usdtIncome - commission),
            "netCoinIncome": str(coinIncome - commission)
            if isBuyer
            else str(coinIncome),
        }

    # spotOrderSummary('VETUSDT', '966771724', True)
    # {'usdtIncome': '-65.05636000',
    # 'coinIncome': '389.00000000',
    # 'commission': '0.38900000',
    # 'netUSDTIncome': '-65.05636000',
    # 'netCoinIncome': '388.61100000'}

    # 선물 거래결과에서 총 PnL과 Commission 읽어오기
    def futuresOrderSummary(self, symbol, orderId, isBuyer):
        (pnl, commission) = (dec("0"), dec("0"))

        tradeResult = (
            self.binanceApiWrappers.apiManager.futureBinance.fapiPrivate_get_usertrades(
                {"symbol": symbol, "orderId": orderId}
            )
        )
        for elements in tradeResult:
            pnl = pnl + dec(elements.get("realizedPnl"))
            commission = commission + dec(elements.get("commission"))

        logger.info(
            "\t\t[%s Futures] Asset: %s, PnL: %s, Commission: %s, NetIncome: %s, orderNo: %s"
            % (
                "Long" if isBuyer else "Short",
                symbol,
                str(pnl),
                str(commission),
                str(pnl - commission),
                orderId,
            )
        )

        return {
            "realizedPnL": str(pnl),
            "commission": str(commission),
            "totalIncome": str(pnl - commission),
        }

    # futuresOrderSummary('XRPUSDT', '13895146854')
    # {'realizedPnL': '-0.13575262',
    # 'commission': '0.00543996',
    # 'totalIncome': '-0.14119258'}

    ########################################################################################
    # 3. 펀딩비 인출, 재투자용 마진 조회 및 전송 관련 함수
    ########################################################################################

    # 포지션 별로 설정한 Threshold Margin Upper 비율보다 높은 증거금 액수 (Margin 줄이기가 가능한 Amount) 읽어오기
    # 내가 가지고 있는 포지션의 symbol만 input으로 넣어야 함
    def getMarginDecreaseAmt(self, symbol):
        self.binanceApiWrappers.updateAccountStatus()

        # 최대 마진 제거 가능액 조회
        futurePositionInfo = self.binanceApiWrappers.getFuturePositions(symbol)
        isolatedWalletBalance = dec(futurePositionInfo.get("isolatedWallet"))
        maintenanceMargin = dec(futurePositionInfo.get("maintMargin"))
        unrealizedPnL = dec(futurePositionInfo.get("unrealizedProfit"))
        notional = dec(futurePositionInfo.get("notional"))

        candidate1 = (isolatedWalletBalance - maintenanceMargin) * dec(
            self.safeInvestmentRatio
        )
        candidate2 = (
            isolatedWalletBalance
            + unrealizedPnL
            - abs(notional * dec(self.threshold_margin_upper))
        )
        max_removable = self.trimUSDTAmount(
            str(max(dec("0"), min(candidate1, candidate2)))
        )
        return max_removable

    # getMarginDecreaseAmt('XRPUSDT')
    # '0'

    # 특정 symbol 코인에 대해 upper limit 을 초과하는 금액을 마진 인출하고, 이를 usdt 현물 지갑으로 이동
    # 여기서 symbol은 보유 코인 (관리 코인) 목록에 있어야 함
    def decreaseMargin(self, symbol):  # API 총 2회 호출
        # upper limit 초과하는 마진 조회

        marginDecreaseUSDT = self.getMarginDecreaseAmt(symbol)
        logger.info("\t\t%s 마진 축소 가능 액수: %s USDT" % (symbol, marginDecreaseUSDT))
        # 0보다 큰 금액을 줄일 수 있는 경우 마진 인출, 현물지갑으로 이동
        if dec(marginDecreaseUSDT) > dec("0"):
            self.binanceApiWrappers.apiManager.futureBinance.fapiPrivate_post_positionmargin(
                {"symbol": symbol, "amount": marginDecreaseUSDT, "type": 2}
            )  # API 호출
            # print('executed margin decrease amount for %s: %s USDT' %(symbol, marginDecreaseUSDT))
            # 인출한 마진 선물 -> 현물지갑으로 이동
            self.binanceApiWrappers.transferFromUsdtMToSpot(
                marginDecreaseUSDT
            )  # API 호출
            logger.info("\t\t마진 인출 후 %s USDT를 Spot 지갑으로 이동" % (marginDecreaseUSDT))
        # else:
        #   print('no margin decrease available for %s' %(symbol))

    ########################################################################################
    # 4. 신규 long/short 포지션 진입 관련 함수들
    ########################################################################################

    # 주어진 코인 리스트, 혹은 전체 코인 리스트에서 현재 펀딩비가 가장 높은 코인 페어 조회
    def getMaxFundingSymbol(self, newInvestmentCoinPairs=None):
        realtimeFundingFeeInfo = (
            self.binanceApiWrappers.apiManager.futureBinance.fapiPublic_get_premiumindex()
        )  # API 호출
        targetFundingFeeInfo = (
            list(
                filter(
                    lambda element: element.get("symbol") in newInvestmentCoinPairs,
                    realtimeFundingFeeInfo,
                )
            )
            if newInvestmentCoinPairs != None
            else realtimeFundingFeeInfo
        )
        maxFundingSymbolInfo = max(
            targetFundingFeeInfo, key=lambda x: dec(x["lastFundingRate"])
        )

        return {
            "symbol": maxFundingSymbolInfo["symbol"],
            "fundingRate": maxFundingSymbolInfo["lastFundingRate"],
        }

    # getMaxFundingSymbol(newInvestmentCoinPairs)
    # {'symbol': 'VETUSDT', 'fundingRate': '0.00035379'}

    # 주어진 코인의 x분동안의 프리미엄 인덱스 표준편차 구하기
    def getPremiumIndexThreshold(
        self, symbol
    ):  # API 총 1회 호출 주어진 코인의 x분동안의 프리미엄 인덱스 표준편차 구하기
        piList = self.binanceApiWrappers.getPremiumIndexValue(symbol)[
            -1 * int(self.premiumIndexWindow) - 1 : -1
        ]
        closeValues10000 = list(
            map(lambda element: float(element["close"]) * 10000, piList)
        )
        stdev = numpy.std(closeValues10000) / 10000
        mean = numpy.mean(closeValues10000) / 10000

        return {
            "symbol": symbol,
            "meanPremiumIndex": str(mean),
            "std": str(stdev),
            "upper": str(mean + float(self.premiumIndexTriggerSigma) * stdev),
            "lower": str(mean - float(self.premiumIndexTriggerSigma) * stdev),
        }

    # getPremiumIndexThreshold('VETUSDT')
    # {'symbol': 'VETUSDT',
    # 'meanPremiumIndex': '0.001484905',
    # 'std': '0.000434747430279927',
    # 'upper': '0.0021370261454198903',
    # 'lower': '0.0008327838545801094'}

    # input 금액 만큼의 usdt로 살 수 있는 수량 구하기 (안전비율 곱해 자금 부족하지 않도록)
    def calculateInvestmentQty(self, symbol, minimumInvestmentNotional):  # 총 API 2회 호출

        _lev = dec(str(self.leverage))
        _commF = dec(
            self.binanceApiWrappers.getFutureCommissionFee(symbol).get(
                "takerCommissionRate"
            )
        )
        _commS = dec(self.binanceApiWrappers.getTradeFee(symbol).get("takerCommission"))

        _futuresPriceMultiplier = (dec("1") + _lev * _commF) / _lev
        _spotPriceMultiplier = dec("1") / (dec("1") - _commS)

        _safeR = dec(str(self.safeInvestmentRatio))

        _notional = dec(str(minimumInvestmentNotional))
        _priceF = dec(
            self.binanceApiWrappers.getFutureOrderBookTicker(symbol).get("bidPrice")
        )  # API 호출
        _priceS = dec(
            self.binanceApiWrappers.getSpotOrderBookTicker(symbol).get("askPrice")
        )  # API 호출

        _investmentQty = _notional / (
            (_priceF * _futuresPriceMultiplier) + (_priceS * _spotPriceMultiplier)
        )
        spotUSDTAmt = self.trimUSDTAmount(
            str(_priceS * _investmentQty * _spotPriceMultiplier)
        )
        futuresUSDTAmt = self.trimUSDTAmount(
            str(_priceF * _investmentQty * _futuresPriceMultiplier)
        )

        adjustedInvestmentQty = self.adjustOrderQuantity(
            symbol, str(_investmentQty * _safeR)
        ).get("amount")

        return {
            "symbol": symbol,
            "amount": adjustedInvestmentQty,
            "spotUSDT": spotUSDTAmt,
            "futuresUSDT": futuresUSDTAmt,
            "totalInvestingUSDT": str(dec(spotUSDTAmt) + dec(futuresUSDTAmt)),
        }

    # calculateInvestmentQty('VETUSDT', leverage, minimumInvestmentNotional)
    # {'symbol': 'VETUSDT',
    # 'amount': '390',
    # 'spotUSDT': '66.63',
    # 'futuresUSDT': '33.36',
    # 'totalInvestingUSDT': '99.99'}

    # 주어진 투자금에 대해 프리미엄 인덱스 1초에 1번 조회하다가 threshold를 넘으면 그 시점의 가격을 참고해 레버리지 비율에 해당하는 만큼을 분배해 선물계좌로 옮기고, buy / sell
    def enterPosition(self, symbol, investmentNotional):
        seconds = 0
        while True:
            piThreshold = float(
                self.getPremiumIndexThreshold(symbol).get("upper")
            )  # API 호출
            premiumIndex = float(
                self.binanceApiWrappers.getLatestPremiumIndexValue(symbol).get("close")
            )  # API 호출

            if premiumIndex > piThreshold:
                logger.info("\t\tEntering Positions in %f seconds" % (seconds))
                logger.info(
                    "\t\tCurrent Premium Index: %f, Threshold: %f"
                    % (premiumIndex, piThreshold)
                )

                # 조회 시점에서 선/현물 투자 금액 계산 및 분배
                investmentInfo = self.calculateInvestmentQty(
                    symbol, investmentNotional
                )  # API 2회 호출
                # 필요 증거금을 현물 -> 선물지갑으로 이동
                self.binanceApiWrappers.transferFromSpotToUsdtM(
                    investmentInfo.get("futuresUSDT")
                )  # API 호출
                logger.info(
                    "\t\ttransfer %s USDT from spot wallet to futures wallet"
                    % (investmentInfo.get("futuresUSDT"))
                )
                # 현물 매수, 선물 매도==================================================================
                spotBuyOrderNo = self.binanceApiWrappers.orderSpotBuy(
                    symbol, investmentInfo.get("amount")
                ).get(
                    "orderId"
                )  # API 호출
                futuresSellOrderNo = self.binanceApiWrappers.orderFutureSell(
                    symbol, investmentInfo.get("amount")
                ).get(
                    "orderId"
                )  # API 호출

                spotSummary = self.spotOrderSummary(
                    symbol, spotBuyOrderNo, True
                )  # API 호출
                futuresSummary = self.futuresOrderSummary(
                    symbol, futuresSellOrderNo, False
                )  # API 호출
                time.sleep(5)

                return {"spotOrder": spotSummary, "futuresOrder": futuresSummary}
                break

            seconds = seconds + 1
            time.sleep(1)

    # === Entering Positions in 289.000000 seconds ===
    # [Premium Index Info] Current Index: 0.000541, Threshold: 0.000388
    # transfer 33.32 USDT from spot wallet to futures wallet
    # [Long Spot] Asset: LTCUSDT, Coin: 0.35164800, USDT: -65.31008000, orderNo: 1814867378
    # [Short Futures] Asset: LTCUSDT, PnL: 0, Commission: 0.02609507, NetIncome: -0.02609507, orderNo: 12548783620
    # {'spotOrder': {'usdtIncome': '-65.31008000',
    # 'coinIncome': '0.35200000',
    # 'commission': '0.00035200',
    # 'netUSDTIncome': '-65.31008000',
    # 'netCoinIncome': '0.35164800'},
    # 'futuresOrder': {'realizedPnL': '0',
    # 'commission': '0.02609507',
    # 'totalIncome': '-0.02609507'}}

    # 주어진 코인 수량 대해 프리미엄 인덱스 1초에 1번 조회하다가 lower threshold를 넘으면 그 시점의 가격을 참고해 양 포지션 종료
    def leavePosition(self, symbol, qty):
        seconds = 0
        while True:
            piThreshold = float(
                self.getPremiumIndexThreshold(symbol).get("lower")
            )  # API 호출
            premiumIndex = float(
                self.binanceApiWrappers.getLatestPremiumIndexValue(symbol).get("close")
            )  # API 호출
            if premiumIndex < piThreshold:
                logger.info("=== Leaving Positions in %f seconds ===" % (seconds))
                logger.info(
                    "[Premium Index Info] Current Index: %f, Threshold: %f"
                    % (premiumIndex, piThreshold)
                )

                # Legal Orders를 위한 Qty 계산
                adjustedQty = self.adjustOrderQuantity(symbol, qty).get("amount")
                # 현물 매도, 선물 매수==================================================================
                spotSellOrderNo = self.binanceApiWrappers.orderSpotSell(
                    symbol, adjustedQty
                ).get(
                    "orderId"
                )  # API 호출
                futuresBuyOrderNo = self.binanceApiWrappers.orderFutureBuy(
                    symbol, adjustedQty
                ).get(
                    "orderId"
                )  # API 호출

                spotSummary = self.spotOrderSummary(
                    symbol, spotSellOrderNo, False
                )  # API 호출
                futuresSummary = self.futuresOrderSummary(
                    symbol, futuresBuyOrderNo, True
                )  # API 호출
                time.sleep(5)

                return {"spotOrder": spotSummary, "futuresOrder": futuresSummary}
            seconds = seconds + 1
            time.sleep(1)

    # === Leaving Positions in 179.000000 seconds ===
    # [Premium Index Info] Current Index: -0.001114, Threshold: -0.000933
    # [Short Spot] Asset: XRPUSDT, Coin: 0, USDT: 0, orderNo: 2478295138
    # [Long Futures] Asset: XRPUSDT, PnL: 0.09683505, Commission: 0.00451719, NetIncome: 0.09231786, orderNo: 14096397278
    # {'spotOrder': {'usdtIncome': '0',
    # 'coinIncome': '0',
    # 'commission': '0',
    # 'netUSDTIncome': '0',
    # 'netCoinIncome': '0'},
    # 'futuresOrder': {'realizedPnL': '0.09683505',
    # 'commission': '0.00451719',
    # 'totalIncome': '0.09231786'}}

    ########################################################################################
    # 5. 청산 방지를 위한 함수들
    ########################################################################################

    # 증거금 비율을 선물 포지션 보유량의 단위 %만큼 조정하는 함수 (청산 방지).
    # 조정 비율만큼 현물 매도, 선물 포지션 종료 -> 현물 매도금 선물지갑으로 전송 -> 계약 마진에 투입
    # min qty 보다 보유량이 크고, 그 달러 환산액이 Min Notional보다 큰 경우에 동작

    # 코인 개수의 delta 비율만큼을 계산 (1회 조정 금액)
    def increaseMargin(self, symbol, changeDelta):  # 1번 실행에 API 총 6번 호출

        priorPositionInfo = (
            self.binanceApiWrappers.getCurrentFuturesPositions()
            .get("positions")
            .get(symbol)
        )

        # 조정 전 보유 수량과 wallet 정보 조회
        priorPositionQuantity = priorPositionInfo.get("positionAmt")
        priorPositionInputMargin = priorPositionInfo.get("inputMargin")

        # 마진 조정하는 symbol별 qualtity 계산
        marginIncreaseQty = float(priorPositionQuantity) * float(changeDelta) * (-1)
        adjustedAmt = self.adjustOrderQuantity(symbol, marginIncreaseQty).get("amount")

        # 현물 매도, 선물 매수==================================================================
        spotSellOrderNo = self.binanceApiWrappers.orderSpotSell(
            symbol, adjustedAmt
        ).get(
            "orderId"
        )  # API 호출
        futuresBuyOrderNo = self.binanceApiWrappers.orderFutureBuy(
            symbol, adjustedAmt
        ).get(
            "orderId"
        )  # API 호출
        spotSummary = self.spotOrderSummary(symbol, spotSellOrderNo, False)
        futuresSummary = self.futuresOrderSummary(symbol, futuresBuyOrderNo, True)

        orderlist = [
                    {
                        "order_id": spotSellOrderNo,
                        "symbol": symbol,
                        "is_spot": True,
                        "is_buyer": False,
                    },
                    {
                        "order_id": futuresBuyOrderNo,
                        "symbol": symbol,
                        "is_spot": False,
                        "is_buyer": True,
                    },
                ]
        # 실행 결과 저장
        action_result = self.save_action(
            action_type="LIQUIDATION_PREVENTION", symbol=symbol, orders=orderlist
        )

        # 현물 매도로 현물 계좌로 환입된 USDT 계산 및 이 금액을 선물 계좌로 이동
        netSpotSellUSDT_temp = spotSummary.get("netUSDTIncome")  # API 호출
        netSpotSellUSDT = self.trimUSDTAmount(netSpotSellUSDT_temp)
        if dec(netSpotSellUSDT) > dec("0"):
            self.binanceApiWrappers.transferFromSpotToUsdtM(netSpotSellUSDT)  # API 호출
            logger.info(
                "transfer %s USDT from spot wallet to futures wallet"
                % (netSpotSellUSDT)
            )
        # 선물 매수(포지션 종료)로 선물 계좌로 환입된 USDT 계산
        releasedMargin = (
            dec(priorPositionInputMargin)
            * dec(adjustedAmt)
            / dec(priorPositionQuantity)
            * dec("-1")
        )
        netReleasedMargin_temp = str(
            releasedMargin + dec(futuresSummary.get("totalIncome"))
        )  # API 호출
        netReleasedMargin = self.trimUSDTAmount(netReleasedMargin_temp)
        logger.info("[Margin Release]: %s USDT" % (netReleasedMargin_temp))
        # 현물 매도금액 + 선물 계좌 환입된 총 USDT만큼을 마진에 투입
        marginIncreaseUSDT = str(dec(netSpotSellUSDT) + dec(netReleasedMargin))
        self.binanceApiWrappers.apiManager.futureBinance.fapiPrivate_post_positionmargin(
            {"symbol": symbol, "amount": marginIncreaseUSDT, "type": 1}
        )  # API 호출
        logger.info("margin increase: %s USDT" % (marginIncreaseUSDT))

        return {
            "spotOrder": spotSummary,
            "futuresOrder": futuresSummary,
            "releasedMargin": netReleasedMargin_temp,
            "marginIncrease": marginIncreaseUSDT,
        }

    # 현재 증거금 비율 가져오는 함수 (Margin Rate를 가져올 수가 없음...)
    # 단위는 Percentage

    # =============================================================================

    # 재혁 : 민제야 너 규칙대로 알아서 코드 바꾸렴

    # 정산시간 10분전 확인 함수. 매일 서버시간 기준 00:50 ~ 00:59, 08:50~08:59, 16:50~16:59 총 세번 체크함
    # 하루 한번의 시간대에서 정산은 단 한번 ex) 00:51에 체크했으면 00:52는 패스함
    def needToCheckFundingFee(self):
        dt_obj = self.getServerTimeObject()

        if dt_obj.minute > 50:
            if dt_obj.hour == 8 and self.__lastTime != 9:
                self.__lastTime = 9
                return True
            elif dt_obj.hour == 16 and self.__lastTime != 17:
                self.__lastTime = 17
                return True
            elif dt_obj.hour == 0 and self.__lastTime != 1:
                self.__lastTime = 1
                return True
            else:
                return False
        else:
            return False

    def getServerTimeObject(self):
        return datetime.fromtimestamp(self.binanceApiWrappers.getServerTime() / 1000)

    def investResidualUSDT(self):
        self.binanceApiWrappers.updateAccountStatus()
        # 선물 지갑 짤짤이 spot으로 이동
        self.cleanFuturesUSDT()
        # 코인별 마진 줄이고 spot으로 이동
        logger.info("\t<선물계좌 여유 마진 인출>")
        for coins in list(set(self.targetCoinPairs + self.newInvestmentCoinPairs)):
            if self.hasPosition(coins):
                self.decreaseMargin(coins)

        # 초기화 후 총 투자 가능한 usdt 계산
        self.binanceApiWrappers.updateAccountStatus()
        totalbalance = self.binanceApiWrappers.getTotalBalanceInfo()
        availableUSDT = dec(
            totalbalance.get("spot").get("assets").get("USDT").get("qty")
        ) - dec(totalbalance.get("netAssetinUSDT")) * dec(self.usdtReserveRatio)

        if availableUSDT <= dec("0"):
            availableUSDT = dec("0")

        logger.info("\t총 투자 가능 금액: %s USDT" %str(availableUSDT))
        for i in range(int(availableUSDT // dec(self.minimumInvestmentNotional))):
            logger.info("\t>> %i 번째 투자 ==========" % (i + 1))
            # 투자 코인 목록 중 펀딩비 최고 코인 조회
            investingCoin = self.getMaxFundingSymbol(self.newInvestmentCoinPairs)
            logger.info("\t\t포지션 진입 코인: %s, 펀딩비: %s" %( investingCoin.get("symbol"), investingCoin.get("fundingRate")))
            # 포지션 진입 실행
            self.enter_position(
                investingCoin.get("symbol"), self.minimumInvestmentNotional
            )
            time.sleep(0.1)

    # # 회원 등록 시 최초 1회 수행됨. 현재 계좌에 가지고 있는 코인 포지션 쌍이 있는지 조회하고 업데이트
    # @transaction.atomic
    # def recordInitialPositions(self):
    #     self.binanceApiWrappers.updateAccountStatus()

    #     for coins in self.binanceApiWrappers.getAvailableCoinPairLists():
    #         if self.hasAsset(coins) and self.hasPosition(coins):
    #             positionModel_spot = models.Positions(user_id = self.userObject, is_spot = True)
    #             positionModel_futures= models.Positions(user_id = self.userObject, is_spot = False)
    #             positionModel_spot.symbol = coins
    #             positionModel_futures.symbol = coins
    #             # Futures
    #             coin_position = self.binanceApiWrappers.getFuturePositions(coins)
    #             positionModel_futures.quantity = coin_position.get('positionAmt')
    #             positionModel_futures.avg_Price = coin_position.get('entryPrice')
    #             # Spot
    #             positionModel_spot.quantity = self.binanceApiWrappers.getCurrentSpotBalances().get(coins[:-4]).get('qty')
    #             positionModel_spot.avg_Price = positionModel_futures.avg_Price # '0' Spot의 경우에는 평단이 제공되지 않으므로, 일단 최초 세팅시 포지션들이 잡혀있다면 futures 진입 가격과 같다고 가정
    #             positionModel_spot.save()
    #             positionModel_futures.save()
    #         # else:
    #         #     dbInput_futures = {'USER_ID': lf.userID,'SYMBOL': coins,'IS_SPOT': 0, 'QUANTITY': '0', 'AVG_PRICE': '0'}
    #         #     dbInput_spot = {'USER_ID': lf.userID,'SYMBOL': coins,'IS_SPOT': 1, 'QUANTITY': '0', 'AVG_PRICE': '0'}

    # 자산 스냅샷 db에 저장
    def saveAssetSnapshot(self):
        self.binanceApiWrappers.updateAccountStatus()
        # 현물과 선물의 총 합계 잔고와 포지션들을 조회
        totalBalanceInfo = self.binanceApiWrappers.getTotalBalanceInfo()
        (spot_value, futures_value) = (dec("0"), dec("0"))

        for coins in self.targetCoinPairs:
            if self.hasAsset(coins) and self.hasPosition(coins):
                spotcoin_usdt_equivalent = (
                    totalBalanceInfo.get("spot")
                    .get("assets")
                    .get(coins[:-4])
                    .get("usdtEquivalent")
                )
                spot_value += dec(spotcoin_usdt_equivalent)
                logger.info("[자산 스냅샷] [SPOT] " + coins + " " + spotcoin_usdt_equivalent)

                futurescoin_usdt_equivalent = (
                    totalBalanceInfo.get("futures")
                    .get("positions")
                    .get(coins)
                    .get("isolatedMargin")
                )
                futures_value += dec(futurescoin_usdt_equivalent)
                logger.info(
                    "[자산 스냅샷] [FUTR] " + coins + " " + futurescoin_usdt_equivalent
                )

        spot_usdt = (
            dec(
                totalBalanceInfo.get("spot")
                .get("assets")
                .get("USDT")
                .get("usdtEquivalent")
            )
            if "USDT" in totalBalanceInfo.get("spot").get("assets")
            else dec("0")
        )
        futures_usdt = (
            dec(totalBalanceInfo.get("futures").get("assets").get("USDT"))
            if "USDT" in totalBalanceInfo.get("futures").get("assets")
            else dec("0")
        )
        usdt_reserve = spot_usdt + futures_usdt
        logger.info("[자산 스냅샷] [USDT] " + " " + str(usdt_reserve))

        # user = User.objects.get(username=self.userId)

        asset = models.Asset(
            user=self.userObject,
            value_spot=str(spot_value),
            value_futures=str(futures_value),
            usdt_reserve=str(usdt_reserve),
        )
        asset.save()

    # 펀딩비 획득 내역 조회 함수
    def save_funding_income(self):
        timestamp_now = self.binanceApiWrappers.getServerTime()
        timestamp_8hrs_before = timestamp_now - 28800000

        funding_info = self.futureBinance.fapiPublic_get_fundingrate(
            {"startTime": timestamp_8hrs_before, "endTime": timestamp_now}
        )  # API 호출
        funding_income_info = self.futureBinance.fapiPrivateGetIncome(
            {
                "incomeType": "FUNDING_FEE",
                "startTime": timestamp_8hrs_before,
                "endTime": timestamp_now,
            }
        )  # API

        fundingrate_info = {
            elements.get("symbol"): elements.get("fundingRate")
            for elements in funding_info
        }
        income_info = {
            elements.get("symbol"): {
                "time": elements.get("time"),
                "income": elements.get("income"),
            }
            for elements in funding_income_info
        }

        funding_list = []

        for coins in self.targetCoinPairs:
            __fundingObj = models.IncomeFunding(symbol=coins, user=self.userObject)
            __fundingObj.date = datetime.fromtimestamp(
                int(income_info.get(coins).get("time")) / 1000, tz=tz.UTC
            )

            __fundingObj.funding_time = int(
                datetime.fromtimestamp(
                    int(income_info.get(coins).get("time")) / 1000
                ).hour
            )
            __fundingObj.funding_income = income_info.get(coins).get("income")
            __fundingObj.funding_rate = fundingrate_info.get(coins)

            funding_list.append(__fundingObj)

        models.IncomeFunding.objects.bulk_create(funding_list)

    # 주문 / 거래 내용을 DB에 삽입하기 위한 orm 객체 생성
    def get_order_model(self, symbol, order_id, is_spot, is_buyer):
        orderResult = (
            self.binance.private_get_mytrades({"symbol": symbol, "orderId": order_id})
            if is_spot
            else self.futureBinance.fapiPrivate_get_usertrades(
                {"symbol": symbol, "orderId": order_id}
            )
        )

        __order = models.Order(
            binance_order_number=order_id,
            user=self.userObject,
            is_spot=is_spot,
            is_buy=is_buyer,
            symbol=symbol,
        )
        # order 객체의 action id, order_timestamp는 나중에 삽입
        __order_detail = models.OrderDetail(
            order=__order,
        )
        transaction_list = []

        (
            order_coinIncome,
            order_usdtIncome,
            order_commission,
            order_totalUSDTCommission,
        ) = (dec("0"), dec("0"), dec("0"), dec("0"))
        buyerFlag = dec("1") if is_buyer else dec("-1")

        for transactions in orderResult:
            tx_commission = transactions.get("commission")
            tx_commissionAsset = transactions.get("commissionAsset")
            tx_usdtCommission = (
                tx_commission
                if tx_commissionAsset == "USDT"
                else str(
                    dec(self.getCurrentCoinPrice(tx_commissionAsset + "USDT"))
                    * dec(tx_commission)
                )
            )

            __transaction = models.Transaction(
                tx_id=transactions.get("id"),
                user=self.userObject,
                order=__order,
                tx_timestamp=datetime.fromtimestamp(
                    int(transactions.get("time")) / 1000, tz=tz.UTC
                ),
                symbol=symbol,
                price=transactions.get("price"),
                amount=transactions.get("qty"),
                quote_price=transactions.get("quoteQty"),
                commission=tx_commission,
                commission_asset=tx_commissionAsset,
                commission_usdt=tx_usdtCommission,
            )
            transaction_list.append(__transaction)

            # 첫 트랜잭션이 이루어진 시간을 order time으로 정함 (시장가 주문이기에)
            if not __order.order_timestamp:
                __order.order_timestamp = datetime.fromtimestamp(
                    int(transactions.get("time")) / 1000, tz=tz.UTC
                )
            order_coinIncome += dec(transactions.get("qty")) * buyerFlag
            order_usdtIncome -= dec(transactions.get("quoteQty")) * buyerFlag
            order_commission += dec(tx_commission)
            order_totalUSDTCommission += dec(tx_usdtCommission)

        __order_detail.amount = (
            str(order_coinIncome - order_commission)
            if is_buyer and is_spot
            else str(order_coinIncome)
        )
        __order_detail.price = str(abs(order_usdtIncome / order_coinIncome))
        __order_detail.quote_price = (
            str(abs(order_usdtIncome - order_totalUSDTCommission))
            if is_buyer and is_spot
            else str(abs(order_usdtIncome))
        )
        __order_detail.commission_usdt = str(order_totalUSDTCommission)

        return {
            "order": __order,
            "order_detail": __order_detail,
            "tx_input_set": transaction_list,
        }

    # 액션, 주문, 거래 정보를 담기 위한 orm model 객체 생성, db 저장
    @transaction.atomic
    def save_action(
        self,
        action_type,
        symbol,
        orders=[{"order_id": "", "symbol": "", "is_spot": True, "is_buyer": False}],
    ):
        __action = models.Action(user=self.userObject, symbol=symbol, type=action_type)
        __action.save()

        __capital_income_obj = models.incomeCapital(
            action=__action, total_commission="0"
        )

        order_models = []
        for order_input in orders:
            order_model = self.get_order_model(
                symbol=symbol,
                order_id=order_input.get("order_id"),
                is_spot=order_input.get("is_spot"),
                is_buyer=order_input.get("is_buyer"),
            )
            __order = order_model.get("order")
            __order_detail = order_model.get("order_detail")
            __transactions_list = order_model.get("tx_input_set")

            # 해당 액션으로 자본차익이 얼마나 됐는지 계산, 저장
            if order_input.get("is_buyer"):
                __capital_income_obj.unit_buying_price = __order_detail.price
                __capital_income_obj.total_buying_price = __order_detail.quote_price
                __capital_income_obj.amount = str(abs(dec(__order_detail.amount)))
            else:
                __capital_income_obj.unit_selling_price = __order_detail.price
                __capital_income_obj.total_selling_price = __order_detail.quote_price
                __capital_income_obj.amount = str(abs(dec(__order_detail.amount)))

            __capital_income_obj.total_commission = str(
                dec(__capital_income_obj.total_commission)
                + dec(__order_detail.commission_usdt)
            )

            __order.action_id = __action
            __order.save()
            __order_detail.save()
            __capital_income_obj.save()
            models.Transaction.objects.bulk_create(__transactions_list)

            order_models.append(order_model)

        return {"action": __action, "orders": order_models}

    # 양 포지션 진입 함수
    def enter_position(self, symbol, investment_notional):
        self.readBotProperties()
        starting_timestamp = datetime.now().timestamp()

        while True:
            # threshold_premium_index = dec(
            #     self.getPremiumIndexThreshold(symbol).get("upper")
            # )
            # threshold_price_difference = (
            #     dec(
            #         self.binanceApiWrappers.getRealtimeFundingFee(symbol).get(
            #             "indexPrice"
            #         )
            #     )
            #     * threshold_premium_index
            # )
            z_value = float(self.premiumIndexTriggerSigma)
            enteringInfo = LogicFuncionApi.getEnteringInfo(symbol=symbol.lower())
            if enteringInfo is None:
                logger.info(f"Don't enter {symbol}. Price Detector is not ready")
                return
            target_entering_difference = dec(enteringInfo['mean']) + dec(z_value) * dec(enteringInfo['stdev'])

            spot_buy_bid_price = dec(
                self.binanceApiWrappers.getSpotOrderBookTicker(symbol).get("askPrice")
            )
            futures_sell_ask_price = dec(
                self.binanceApiWrappers.getFutureOrderBookTicker(symbol).get("bidPrice")
            )
            price_difference = futures_sell_ask_price - spot_buy_bid_price

            logger.info(f"Try : price difference : {price_difference} / target entering difference : {target_entering_difference}")
            if price_difference > target_entering_difference:
                ending_timestamp = datetime.now().timestamp()
                time_difference = ending_timestamp - starting_timestamp
                logger.info("Entering Positions in %f seconds" % (time_difference))
                logger.info(
                    "Current Profit: %f, Threshold Profit: %f"
                    % (price_difference, target_entering_difference)
                )

                # 조회 시점에서 선/현물 투자 금액 계산 및 분배
                investmentInfo = self.calculateInvestmentQty(
                    symbol, investment_notional
                )  # API 2회 호출
                # 필요 증거금을 현물 -> 선물지갑으로 이동
                self.binanceApiWrappers.transferFromSpotToUsdtM(
                    investmentInfo.get("futuresUSDT")
                )  # API 호출
                logger.info(
                    "transfer %s USDT from spot wallet to futures wallet"
                    % (investmentInfo.get("futuresUSDT"))
                )
                # 현물 매수, 선물 매도==================================================================
                spotBuyOrderNo = self.binanceApiWrappers.orderSpotBuy(
                    symbol, investmentInfo.get("amount")
                ).get(
                    "orderId"
                )  # API 호출
                futuresSellOrderNo = self.binanceApiWrappers.orderFutureSell(
                    symbol, investmentInfo.get("amount")
                ).get(
                    "orderId"
                )  # API 호출

                orderlist = [
                    {
                        "order_id": spotBuyOrderNo,
                        "symbol": symbol,
                        "is_spot": True,
                        "is_buyer": True,
                    },
                    {
                        "order_id": futuresSellOrderNo,
                        "symbol": symbol,
                        "is_spot": False,
                        "is_buyer": False,
                    },
                ]
                # 실행 결과 저장
                action_result = self.save_action(
                    action_type="ORDER", symbol=symbol, orders=orderlist
                )

                # 실행 결과 요약
                actual_spot_buy_price = (
                    action_result.get("orders")[0].get("order_detail").price
                )
                actual_futures_sell_price = (
                    action_result.get("orders")[1].get("order_detail").price
                )
                logger.info(
                    "[탐지] 선물 매도가: %f, 현물 매수가: %f"
                    % (float(futures_sell_ask_price), float(spot_buy_bid_price))
                )
                logger.info(
                    "[실제] 선물 매도가: %f, 현물 매수가: %f"
                    % (float(actual_futures_sell_price), float(actual_spot_buy_price))
                )

                return action_result
            else:
                logger.info("Failed : price difference < target entering difference")
                logger.info("Retry ..")
                time.sleep(0.2)
    # 양 포지션 종료 함수
    def leave_position(self, symbol, investment_notional):
        self.readBotProperties()
        starting_timestamp = datetime.now().timestamp()

        while True:
            leavingInfo = LogicFuncionApi.getLeavingInfo(symbol=symbol.lower())
            if leavingInfo is None:
                logger.info(f"Don't leave {symbol}. Price Detector is not ready")
                return
            z_value = float(self.premiumIndexTriggerSigma)
            target_leaving_difference = dec(leavingInfo['mean']) + dec(z_value)*dec(leavingInfo['stdev'])

            spot_sell_bid_price = dec(
                self.binanceApiWrappers.getSpotOrderBookTicker(symbol).get("bidPrice")
            )
            futures_buy_ask_price = dec(
                self.binanceApiWrappers.getFutureOrderBookTicker(symbol).get("askPrice")
            )
            price_difference = spot_sell_bid_price - futures_buy_ask_price

            logger.info(f"Try : price difference : {price_difference} / target leaving difference : {target_leaving_difference}")
            if price_difference > target_leaving_difference:
                ending_timestamp = datetime.now().timestamp()
                time_difference = ending_timestamp - starting_timestamp
                logger.info("Leaving Positions in %f seconds" % (time_difference))
                logger.info(
                    "Current Profit: %f, Threshold Profit: %f"
                    % (price_difference, target_leaving_difference)
                )

                # 조회 시점에서 선/현물 투자 금액 계산 및 분배
                investmentInfo = self.calculateInvestmentQty(
                    symbol, investment_notional
                )  # API 2회 호출

                # 현물 매도, 선물 매수==================================================================
                spotSellOrderNo = self.binanceApiWrappers.orderSpotSell(
                    symbol, investmentInfo.get("amount")
                ).get(
                    "orderId"
                )  # API 호출
                futuresBuyOrderNo = self.binanceApiWrappers.orderFutureBuy(
                    symbol, investmentInfo.get("amount")
                ).get(
                    "orderId"
                )  # API 호출

                orderlist = [
                    {
                        "order_id": spotSellOrderNo,
                        "symbol": symbol,
                        "is_spot": True,
                        "is_buyer": False,
                    },
                    {
                        "order_id": futuresBuyOrderNo,
                        "symbol": symbol,
                        "is_spot": False,
                        "is_buyer": True,
                    },
                ]
                # 실행 결과 저장
                action_result = self.save_action(
                    action_type="CLOSE", symbol=symbol, orders=orderlist
                )

                # 실행 결과 요약
                actual_spot_sell_price = (
                    action_result.get("orders")[0].get("order_detail").price
                )
                actual_futures_buy_price = (
                    action_result.get("orders")[1].get("order_detail").price
                )
                logger.info(
                    "[탐지] 선물 매수가: %f, 현물 매도가: %f"
                    % (float(futures_buy_ask_price), float(spot_sell_bid_price))
                )
                logger.info(
                    "[실제] 선물 매수가: %f, 현물 매도가: %f"
                    % (float(actual_futures_buy_price), float(actual_spot_sell_price))
                )
                self.cleanFuturesUSDT()

                return action_result
            else:
                logger.info("Failed : price difference < target leaving difference")
                logger.info("Retry ..")
                time.sleep(0.2)
