from decimal import Decimal as dec
from typing import DefaultDict
import yaml
import numpy
import time
import sys

sys.path.append("./")
# from bot_v2.BinanceApiWrappers import BinanceApiWrappers
from tools.BinanceApiWrappers import BinanceApiWrappers
from datetime import datetime


class LogicFunctions:
    def __init__(self):

        self.binanceApiWrappers = BinanceApiWrappers()
        self.binance = self.binanceApiWrappers.apiManager.binance
        self.futureBinance = self.binanceApiWrappers.apiManager.futureBinance

        self.readBotProperties()

    ########################################################################################
    # 1. 자릿수 조정, Legal Order 생성 등 전처리작업 함수
    ########################################################################################
    # 설정값 읽어오기

    def readBotProperties(self):
        filename = "botProperties.yaml"
        with open(filename, encoding="UTF8") as botPropertiesFile:
            botProperties = yaml.load(botPropertiesFile, Loader=yaml.FullLoader)
            self.bot_interval = botProperties.get("bot").get(
                "interval"
            )  # 봇이 돌아가는 주기 (seconds)
            self.leverage = botProperties.get("bot").get("leverage")  # 레버리지

            self.usdtDecimal = botProperties.get("bot").get(
                "usdtDecimal"
            )  # usdt를 관리할 소수점
            self.usdtReserveRatio = botProperties.get("bot").get(
                "usdtReserveRatio"
            )  # Spot 지갑에 항상 남겨둘 USDT 비율 (총 자산 기준)
            self.minimumInvestmentNotional = botProperties.get("bot").get(
                "minimumInvestmentNotional"
            )  # 이 수량의 USDT 단위로 투자가 됨 (현물 + 선물의 Notional USDT

            self.threshold_margin_upper = botProperties.get("bot").get(
                "safeRatioUpperBound"
            )  # 상방 제한 증거금 비율 (추후 레버리지와 연동)
            self.threshold_margin_lower = botProperties.get("bot").get(
                "safeRatioLowerBound"
            )  # 하방 제한 증거금 비율 (추후 레버리지와 연동)
            self.marginDelta = botProperties.get("bot").get(
                "marginDelta"
            )  # 1회의 반복에서 Rebalancing 하는 자산의 비율
            self.targetCoinPairs = botProperties.get("bot").get(
                "targetCoinPairs"
            )  # 관리할 코인 pair 리스트
            self.newInvestmentCoinPairs = botProperties.get("bot").get(
                "newInvestmentCoinPairs"
            )  # 신규 투자할 코인 pair 리스트 (관리할거면 관리 코인 리스트에도 추가)
            self.safeInvestmentRatio = botProperties.get("bot").get(
                "safeInvestmentRatio"
            )

            self.premiumIndexWindow = botProperties.get("bot").get(
                "premiumIndexWindow"
            )  # Premium Index들의 표준편차를 구할 때 사용되는 데이터 수 (분 단위)
            self.premiumIndexTriggerSigma = botProperties.get("bot").get(
                "premiumIndexTriggerSigma"
            )  # 몇 sigma 보다 큰 premium index를 보일 때 long/short 포지션 진입할 지 선택
            self.targetTimeSpareMinute = botProperties.get("bot").get(
                "targetTimeSpareMinute"
            )  # 몇 sigma 보다 큰 premium index를 보일 때 long/short 포지션 진입할 지 선택 "targetTimeSpareMinute"

    # usdt amount를 원하는 자리수까지 trim (내림)
    def trimUSDTAmount(self, amount):
        amount = dec(str(amount))
        trimmer = dec(str(self.usdtDecimal))
        return str((amount // trimmer) * trimmer)

    # trimUSDTAmount(1.2342)
    # '1.23'

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
        futuresUSDTBalance = (
            self.binanceApiWrappers.getCurrentFuturesPositions()
            .get("assets")
            .get("USDT")
        )
        movingUSDT = self.trimUSDTAmount(futuresUSDTBalance)
        if dec(movingUSDT) > dec("0"):
            print("\t>> 선물 지갑의 잔여 USDT를 SPOT 지갑으로 이동. 이동 금액: %s USDT" % (movingUSDT))
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
            print("동시 진입 포지션이 없음")
            return {"symbol": symbol, "spotDeficit": False, "difference": "0"}

    # 선물/현물 포지션 숫자를 조회해, 해당 차이가 주문가능한 Threshold보다 크다면 현물 수량을 조절해 현/선물 수량을 맞추는 함수 (주문이 들어가기에 여유자금이 있어야 함)
    def syncSpotFuturesQty(self):
        syncResult = {}
        for symbol in self.targetCoinPairs:
            difference = self.spotFuturesDifference(symbol)
            differenceAmt = difference.get("difference")
            thresholdAmt = self.adjustOrderQuantity(symbol, "0").get("amount")

            if dec(differenceAmt) > dec(thresholdAmt):
                print(
                    "\t%s\t현/선물 수량 차이 조절 필요.\t 차이: %s,\t최소 주문 가능: %s"
                    % (symbol, differenceAmt, thresholdAmt)
                )

                if difference.get("spotDeficit"):
                    buyAmt = self.adjustOrderQuantity(
                        symbol, str(dec(differenceAmt) / dec("0.999"))
                    ).get("amount")
                    spotBuyOrderNo = self.binanceApiWrappers.orderSpotBuy(
                        symbol, buyAmt
                    ).get(
                        "orderId"
                    )  # API 호출
                    spotBuySummary = self.spotOrderSummary(symbol, spotBuyOrderNo, True)
                    syncResult[symbol] = spotBuySummary
                else:
                    sellAmt = self.adjustOrderQuantity(symbol, differenceAmt).get(
                        "amount"
                    )
                    spotSellOrderNo = self.binanceApiWrappers.orderSpotSell(
                        symbol, sellAmt
                    ).get(
                        "orderId"
                    )  # API 호출
                    spotSellSummary = self.spotOrderSummary(
                        symbol, spotSellOrderNo, False
                    )
                    syncResult[symbol] = spotSellSummary
            else:
                print(
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

        print(
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

        print(
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
        print("\t\t%s 마진 축소 가능 액수: %s USDT" % (symbol, marginDecreaseUSDT))
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
            print("\t\t마진 인출 후 %s USDT를 Spot 지갑으로 이동" % (marginDecreaseUSDT))
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
                print("\t\tEntering Positions in %f seconds" % (seconds))
                print(
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
                print(
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
                print("=== Leaving Positions in %f seconds ===" % (seconds))
                print(
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

        # 현물 매도로 현물 계좌로 환입된 USDT 계산 및 이 금액을 선물 계좌로 이동
        netSpotSellUSDT_temp = spotSummary.get("netUSDTIncome")  # API 호출
        netSpotSellUSDT = self.trimUSDTAmount(netSpotSellUSDT_temp)
        if dec(netSpotSellUSDT) > dec("0"):
            self.binanceApiWrappers.transferFromSpotToUsdtM(netSpotSellUSDT)  # API 호출
            print(
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
        print("[Margin Release]: %s USDT" % (netReleasedMargin_temp))
        # 현물 매도금액 + 선물 계좌 환입된 총 USDT만큼을 마진에 투입
        marginIncreaseUSDT = str(dec(netSpotSellUSDT) + dec(netReleasedMargin))
        self.binanceApiWrappers.apiManager.futureBinance.fapiPrivate_post_positionmargin(
            {"symbol": symbol, "amount": marginIncreaseUSDT, "type": 1}
        )  # API 호출
        print("margin increase: %s USDT" % (marginIncreaseUSDT))

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
        print("\t<선물계좌 여유 마진 인출>")
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

        print("\t총 투자 가능 금액:\t", str(availableUSDT), "USDT")
        for i in range(int(availableUSDT // dec(self.minimumInvestmentNotional))):
            print("\n\t>> %i 번째 투자 ==========" % (i + 1))
            # 투자 코인 목록 중 펀딩비 최고 코인 조회
            investingCoin = self.getMaxFundingSymbol(self.newInvestmentCoinPairs)
            print(
                "\t\t포지션 진입 코인:\t",
                investingCoin.get("symbol"),
                "\t펀딩비:\t",
                investingCoin.get("fundingRate"),
            )
            # 포지션 진입 실행
            self.enterPosition(
                investingCoin.get("symbol"), self.minimumInvestmentNotional
            )
