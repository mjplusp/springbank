import sys

# sys.path.append('../')


# sys.path.append('apiManager')

from apiManager.apiManager import ApiManager
import re
import json
import requests
import decimal

# 변경내역
# 1. 거래 가능한 coin-usdt pair 정보 불러오기 추가 getAvailableCoinPairLists()
# 2. 선물, 현물 종합해 최소 거래 단위 정보를 인스턴스로 추가 getLegalOrdersInfo
# 3. 선물 달러와 보유한 포지션들 정보를 조회 getCurrentFuturesPositions
# 4. 현물 보유 코인들 정보를 조회 getCurrentSpotBalances

# 고려해야 할 내용
# 1. 선물 주문 시 격리모드, 레버리지 설정
# 2. bulk order
# 3. 주문중 일부 실패했을 때 처리방법
# 4. 주문 후 거래 데이터 (입금금액, 수수료 등) 반환받아 처리 방법


class BinanceApiWrappers:
    def __init__(self):
        self.apiManager = ApiManager()
        # 불변의 정보는 한번만 콜하기

        self.initializeBot()
        self.updateAccountStatus()

    ############### Bot Initialize 관련 함수들 모음 ###############

    def initializeBot(self):
        self.__binanceExchangeInfo = self.apiManager.invokeAPI(
            self.apiManager.binance.public_get_exchangeinfo, None
        )
        self.__futurebinanceInfo = self.apiManager.invokeAPI(
            self.apiManager.futureBinance.fapiPublic_get_exchangeinfo, None
        )

        # 전체 symbol들에 대한 정보
        self.__symbolsInfo = self.__binanceExchangeInfo.get("symbols")
        self.__futureSymbolsInfo = self.__futurebinanceInfo.get("symbols")

        # 우리가 다룰 usdt 로 살수 있는 symbol들 에 대한 정보
        regex = re.compile("[\w]+USDT$")
        self.__symbolsUSDTInfo = dict(
            (s.get("symbol"), s)
            for s in list(
                filter(
                    lambda s: regex.match(s.get("symbol")) != None, self.__symbolsInfo
                )
            )
        )
        self.__futureSymbolsUSDTInfo = dict(
            (s.get("symbol"), s)
            for s in list(
                filter(
                    lambda s: regex.match(s.get("symbol")) != None,
                    self.__futureSymbolsInfo,
                )
            )
        )
        self.__availableSymbolsList = [
            val
            for val in list(self.__symbolsUSDTInfo.keys())
            if val in list(self.__futureSymbolsUSDTInfo.keys())
        ]

        # Trade Fee 에 대한 정보
        feeregex = re.compile("[\w]+/USDT$")
        self.__tradeFeeInfo = self.apiManager.invokeAPI(
            self.apiManager.binance.fetch_trading_fees, None
        )
        self.__tradeFee = dict(
            (element.get("info").get("symbol"), element.get("info"))
            for element in dict(
                filter(
                    lambda element: feeregex.match(element[0]) != None,
                    self.__tradeFeeInfo.items(),
                )
            ).values()
        )

        # self.__tradeFee = dict((s.get("symbol"), s) for s in list(filter(lambda s: regex.match(s.get("symbol")) != None, self.__tradeFeeInfo)))
        # self.__tradeFeeInfo = self.apiManager.invokeAPI(self.apiManager.binance.wapi_get_tradefee, None).get('tradeFee')
        # self.__tradeFee = dict((s.get("symbol"), s) for s in list(filter(lambda s: regex.match(s.get("symbol")) != None, self.__tradeFeeInfo)))

    #######################

    # 주어진 코인 symbol에 대해 현물/선물 filter 데이터를 종합해 허용된 최소 주문량을 읽어오는 함수
    def getSingleLegalOrdersInfo(self, symbol):  # BTCUSDT
        filters = self.__symbolsUSDTInfo[symbol].get("filters")
        futuresFilters = self.__futureSymbolsUSDTInfo[symbol].get("filters")

        lotsizeFilter = next(
            filter(lambda e: e.get("filterType") == "LOT_SIZE", filters)
        )
        lotsizeFilter_Futures = next(
            filter(lambda e: e.get("filterType") == "LOT_SIZE", futuresFilters)
        )

        minNotionalFiter = next(
            filter(lambda e: e.get("filterType") == "MIN_NOTIONAL", filters)
        )
        minNotionalFiter_Futures = next(
            filter(lambda e: e.get("filterType") == "MIN_NOTIONAL", futuresFilters)
        )

        marketLotSizeFilter = next(
            filter(lambda e: e.get("filterType") == "MARKET_LOT_SIZE", filters)
        )
        marketLotSizeFilter_Futures = next(
            filter(lambda e: e.get("filterType") == "MARKET_LOT_SIZE", futuresFilters)
        )

        return {
            "symbol": symbol,
            "minNotional": str(
                decimal.Decimal(minNotionalFiter.get("minNotional")).max(
                    decimal.Decimal(minNotionalFiter_Futures.get("notional"))
                )
            ),
            "minOrderQty": str(
                decimal.Decimal(lotsizeFilter.get("minQty"))
                .max(decimal.Decimal(lotsizeFilter_Futures.get("minQty")))
                .max(decimal.Decimal(marketLotSizeFilter.get("minQty")))
                .max(decimal.Decimal(marketLotSizeFilter_Futures.get("minQty")))
            ),
            "stepSize": str(
                decimal.Decimal(lotsizeFilter.get("stepSize"))
                .max(decimal.Decimal(lotsizeFilter_Futures.get("stepSize")))
                .max(decimal.Decimal(marketLotSizeFilter.get("stepSize")))
                .max(decimal.Decimal(marketLotSizeFilter_Futures.get("stepSize")))
            ),
        }

    # 모든 코인 symbol에 대해 현물/선물 filter 데이터를 종합해 허용된 최소 주문량을 읽어오는 함수
    def getLegalOrdersInfo(self):
        return {
            symbol: self.getSingleLegalOrdersInfo(symbol)
            for symbol in self.getAvailableCoinPairLists()
        }

    # 현물의 0 이상 수량을 보유한 symbol에 대해 free 수량과 USDT 환산액, 총 자산 USDT 환산액을 읽어오는 함수
    def getCurrentSpotBalances(self):
        currentAssets_temp = {
            value.get("asset"): value.get("free")
            for (key, value) in self.__balances.items()
            if decimal.Decimal(value.get("free")) != decimal.Decimal("0")
        }

        tickers = self.apiManager.binance.public_get_ticker_price()

        return {
            key: {
                "qty": value,
                "usdtEquivalent": str(
                    decimal.Decimal(
                        next(
                            filter(lambda l: l.get("symbol") == key + "USDT", tickers),
                            {"price": "1"},
                        ).get("price")
                    )
                    * decimal.Decimal(value)
                ),
            }
            for (key, value) in currentAssets_temp.items()
        }

    # 선물의 0 이상 포지션을 보유한 symbol에 대해 수량, 마진정보, 비율 등을 읽어오는 함수
    def getCurrentFuturesPositions(self):
        futurePositions = self.__futurePositionsInfo
        futureAssets = self.__futureAssetsInfo
        positions = {
            value.get("symbol"): {
                "positionAmt": value.get("positionAmt"),
                "initialMargin": value.get("initialMargin"),
                "notional": value.get("notional"),
                "inputMargin": value.get("isolatedWallet"),
                "isolatedMargin": str(
                    decimal.Decimal(value.get("isolatedWallet"))
                    + decimal.Decimal(value.get("unrealizedProfit"))
                ),
                "collateralRatio": str(
                    (
                        decimal.Decimal(value.get("isolatedWallet"))
                        + decimal.Decimal(value.get("unrealizedProfit"))
                    )
                    / decimal.Decimal(value.get("notional"))
                    * decimal.Decimal("-1")
                ),
            }
            for (key, value) in futurePositions.items()
            if decimal.Decimal(value.get("positionAmt")) != decimal.Decimal("0")
        }

        futuresInfo = {
            "assets": {"USDT": futureAssets.get("USDT").get("maxWithdrawAmount")},
            "positions": positions,
        }
        return futuresInfo

    # 현물과 선물의 총 합계 잔고와 포지션들을 조회
    def getTotalBalanceInfo(self):

        spotBalances = self.getCurrentSpotBalances()
        spots = {
            "totalUSDTBalance": str(
                sum(decimal.Decimal(x["usdtEquivalent"]) for x in spotBalances.values())
            ),
            "assets": spotBalances,
        }

        futureAccounts = self.__futureAcountInfo
        futures = self.getCurrentFuturesPositions()
        futures["totalUSDTBalance"] = futureAccounts.get("totalMarginBalance")

        return {
            "netAssetinUSDT": str(
                sum(decimal.Decimal(x["usdtEquivalent"]) for x in spotBalances.values())
                + decimal.Decimal(futureAccounts.get("totalMarginBalance"))
            ),
            "spot": spots,
            "futures": futures,
        }

    # 거래 가능한 coin-usdt pair 정보
    def getAvailableCoinPairLists(self):
        return self.__availableSymbolsList

    # rate limit 정보
    def getRateLimits(self):
        return self.__binanceExchangeInfo.get("rateLimits")

    # USDT Symbol 정보들 모두 가져오기
    def getSymbolLists(self, isFuture=False):
        return self.__futureSymbolsInfo if (isFuture) else self.__symbolsUSDTInfo

    # USDT Symbol 정보들 중 하나의 symbol 정보만 가져오기
    def getSingleSymbol(self, symbol, isFuture=False):
        return (
            self.__futureSymbolsUSDTInfo[symbol]
            if (isFuture)
            else self.__symbolsUSDTInfo[symbol]
        )

    # 하나의 symbol 정보 중 precision 정보 가져오기
    def getPrecisions(self, symbol, isFuture=False):
        singleSymbolInfo = self.getSingleSymbol(symbol, isFuture)
        if isFuture:
            return {
                "pricePrecision": singleSymbolInfo.get("pricePrecision"),
                "quantityPrecision": singleSymbolInfo.get("quantityPrecision"),
                "baseAssetPrecision": singleSymbolInfo.get("baseAssetPrecision"),
                "quotePrecision": singleSymbolInfo.get("quotePrecision"),
            }
        else:
            return {
                "quotePrecision": singleSymbolInfo.get("quotePrecision"),
                "quoteAssetPrecision": singleSymbolInfo.get("quoteAssetPrecision"),
                "baseCommissionPrecision": singleSymbolInfo.get(
                    "baseCommissionPrecision"
                ),
                "quoteCommissionPrecision": singleSymbolInfo.get(
                    "quoteCommissionPrecision"
                ),
            }

    # 하나의 symbol 정보 중 주문 Price 정보 가져오기
    def getPriceInfo(self, symbol, isFuture=False):
        singleSymbolInfo = self.getSingleSymbol(symbol, isFuture)
        return next(
            filter(
                lambda l: l.get("filterType") == "PRICE_FILTER",
                singleSymbolInfo.get("filters"),
            ),
            None,
        )

    # 하나의 symbol 정보 중 주문 수량 정보 가져오기
    def getQuoteInfo(self, symbol, isFuture=False):
        singleSymbolInfo = self.getSingleSymbol(symbol, isFuture)
        return next(
            filter(
                lambda l: l.get("filterType") == "LOT_SIZE",
                singleSymbolInfo.get("filters"),
            ),
            None,
        )

    def getMarketPriceQuoteInfo(self, symbol, isFuture=False):
        singleSymbolInfo = self.getSingleSymbol(symbol, isFuture)
        return next(
            filter(
                lambda l: l.get("filterType") == "MARKET_LOT_SIZE",
                singleSymbolInfo.get("filters"),
            ),
            None,
        )

    def getTradeFee(self, symbol):
        return self.__tradeFee.get(symbol)

    def getFutureCommissionFee(self, symbol):
        return self.apiManager.invokeAPI(
            self.apiManager.futureBinance.fapiPrivate_get_commissionrate,
            {"symbol": symbol},
        )

    def setSymbolLeverage(self, symbol, leverage=3):
        data = {"symbol": symbol, "leverage": leverage}
        return self.apiManager.invokeAPI(
            self.apiManager.futureBinance.fapiPrivate_post_leverage, data
        )

    # marginType = ISOLATED, CROSSED
    def setMarginType(self, symbol, marginType="ISOLATED"):
        data = {"symbol": symbol, "marginType": marginType}
        return self.apiManager.invokeAPI(
            self.apiManager.futureBinance.fapiPrivate_post_margintype, data
        )

    ##########################################################

    ############### Loop Initialize 관련 함수들 모음 ###############

    def updateAccountStatus(self):
        balances = self.apiManager.invokeAPI(
            self.apiManager.binance.private_get_account, None
        ).get("balances")
        self.__balances = dict((s.get("asset"), s) for s in balances)

        # account 정보
        self.__futureAcountInfo = self.apiManager.invokeAPI(
            self.apiManager.futureBinance.fapiPrivate_get_account, None
        )
        self.__futureAssetsInfo = dict(
            (s.get("asset"), s) for s in self.__futureAcountInfo.get("assets")
        )
        self.__futurePositionsInfo = dict(
            (s.get("symbol"), s) for s in self.__futureAcountInfo.get("positions")
        )

    #######################
    def getSpotBalance(self, symbol=None):
        if symbol == None:
            return self.__balances
        else:
            return self.__balances.get(symbol)

    def getFutureBalance(self):
        return self.apiManager.invokeAPI(
            self.apiManager.futureBinance.fapiPrivate_get_balance, None
        )

    def getFutureAccount(self):
        return self.__futureAcountInfo

    def getFuturePositions(self, symbol=None):
        if symbol == None:
            return self.__futurePositionsInfo
        else:
            return self.__futurePositionsInfo.get(symbol)

    def getFutureAssets(self, asset=None):
        if asset == None:
            return self.__futureAssetsInfo
        else:
            return self.__futureAssetsInfo.get(asset)

    def getAvgPrice5min(self, symbol):
        return json.loads(
            requests.get(
                "https://api.binance.com/api/v3/avgPrice?symbol=" + symbol
            ).text
        )

    #########################################################

    ######### 1번 지난 정산으로 얻어진 펀딩비 재투자 관련 함수들 #########
    def getLastFundingFeeIncome(self, symbol):
        histories = list(
            filter(
                lambda s: s.get("incomeType") == "FUNDING_FEE",
                self.getIncomeHistory(symbol),
            )
        )
        if len(histories) > 0:
            return histories[-1]
        else:
            return None

    def getRealtimeFundingFee(self, symbol=None):
        return self.apiManager.invokeAPI(
            self.apiManager.futureBinance.fapiPublic_get_premiumindex,
            {"symbol": symbol} if symbol else None,
        )

        # result = self.apiManager.invokeAPI(self.apiManager.futureBinance.fapiPublic_get_premiumindex, None)
        # return (dict((s.get("symbol"), s) for s in result))

    def getLatestPremiumIndexValue(self, symbol):
        reqResult = requests.get(
            "https://www.binance.com/fapi/v1/marketKlines?interval=1m&limit=1000&symbol=p"
            + symbol
        ).text
        recentResult = json.loads(reqResult)[-1]
        return {
            "timestamp": recentResult[0],
            "open": recentResult[1],
            "high": recentResult[2],
            "low": recentResult[3],
            "close": recentResult[4],
        }
        # ccxt 소스코드에 이게 없어서 만듦
        # param = {"limit" : 10, "symbol": symbol, "interval": "1m"}
        # return self.apiManager.invokeAPI(self.apiManager.futureBinance.fapiPublic_get_markpriceklines, param)

    def getPremiumIndexValue(self, symbol):
        reqResult = requests.get(
            "https://www.binance.com/fapi/v1/marketKlines?interval=1m&limit=1000&symbol=p"
            + symbol
        ).text
        return list(
            map(
                lambda x: {
                    "timestamp": x[0],
                    "open": x[1],
                    "high": x[2],
                    "low": x[3],
                    "close": x[4],
                },
                json.loads(reqResult),
            )
        )

    def transferFromSpotToUsdtM(self, amount, asset="USDT"):
        data = {"type": 1, "asset": asset, "amount": amount}
        return self.apiManager.invokeAPI(
            self.apiManager.binance.sapi_post_futures_transfer, data
        )

    def transferFromUsdtMToSpot(self, amount, asset="USDT"):
        data = {"type": 2, "asset": asset, "amount": amount}
        return self.apiManager.invokeAPI(
            self.apiManager.binance.sapi_post_futures_transfer, data
        )

    def getSpotOrderBookTicker(self, symbol):
        return self.apiManager.invokeAPI(
            self.apiManager.binance.public_get_ticker_bookticker, {"symbol": symbol}
        )

    def getFutureOrderBookTicker(self, symbol):
        return self.apiManager.invokeAPI(
            self.apiManager.binance.fapiPublic_get_ticker_bookticker, {"symbol": symbol}
        )

    # 현물 거래 테스트
    def orderSpotSellTest(self, symbol, amount):
        data = {"symbol": symbol, "side": "SELL", "type": "MARKET", "quantity": amount}
        return self.apiManager.invokeAPI(
            self.apiManager.binance.private_post_order_test, data
        )

    # 현물 거래 테스트
    def orderSpotBuyTest(self, symbol, amount):
        data = {"symbol": symbol, "side": "BUY", "type": "MARKET", "quantity": amount}
        return self.apiManager.invokeAPI(
            self.apiManager.binance.private_post_order_test, data
        )

    # 실제 거래 함수
    def orderSpotSell(self, symbol, amount):
        data = {"symbol": symbol, "side": "SELL", "type": "MARKET", "quantity": amount}
        return self.apiManager.invokeAPI(
            self.apiManager.binance.private_post_order, data
        )

    # 실제 거래 함수
    def orderSpotBuy(self, symbol, amount):
        data = {"symbol": symbol, "side": "BUY", "type": "MARKET", "quantity": amount}
        return self.apiManager.invokeAPI(
            self.apiManager.binance.private_post_order, data
        )

    # 실제 거래 함수
    def orderFutureSell(self, symbol, amount):
        data = {"symbol": symbol, "side": "SELL", "type": "MARKET", "quantity": amount}
        return self.apiManager.invokeAPI(
            self.apiManager.binance.fapiPrivate_post_order, data
        )

    # 실제 거래 함수
    def orderFutureBuy(self, symbol, amount):
        data = {"symbol": symbol, "side": "BUY", "type": "MARKET", "quantity": amount}
        return self.apiManager.invokeAPI(
            self.apiManager.binance.fapiPrivate_post_order, data
        )

    # 거래 데이터 얻어오는 함수
    def getFuturesTradeData(self, symbol, orderId):
        data = {"symbol": symbol, "orderId": orderId}
        return self.apiManager.invokeAPI(
            self.apiManager.futureBinance.fapiPrivate_get_usertrades, data
        )

    def getSpotTradeData(self, symbol, orderId):
        data = {"symbol": symbol, "orderId": orderId}
        return self.apiManager.invokeAPI(
            self.apiManager.binance.private_get_mytrades, data
        )

    ##########################################################

    ############### 2번 청산 방지 증거금 비율 조정 관련 ##############
    def getPremiumIndex(self, symbol=None):
        if symbol == None:
            return self.apiManager.invokeAPI(
                self.apiManager.futureBinance.fapiPublic_get_premiumindex, None
            )
        else:
            return self.apiManager.invokeAPI(
                self.apiManager.futureBinance.fapiPublic_get_premiumindex,
                {
                    "symbol": symbol,
                },
            )

    def getLiquidationPrice(self, symbol):
        return self.apiManager.invokeAPI(
            self.apiManager.futureBinance.fapiPrivate_get_positionrisk,
            {"symbol": symbol},
        )[0].get("liquidationPrice")

    def getPositionRisk(self, symbol):
        return self.apiManager.invokeAPI(
            self.apiManager.futureBinance.fapiPrivate_get_positionrisk,
            {"symbol": symbol},
        )[0]

    def changeMargin(
        self, symbol, amount, type
    ):  # type 1: add margin, 2: reduce margin
        data = {"symbol": symbol, "amount": amount, "type": type}
        return self.apiManager.invokeAPI(
            self.apiManager.futureBinance.fapiPrivate_post_positionmargin, data
        )

    ##########################################################

    ############### Income History ###############
    def getIncomeHistory(self, symbol=None):
        if symbol == None:
            return self.apiManager.invokeAPI(
                self.apiManager.futureBinance.fapiPrivate_get_income, None
            )
        else:
            return self.apiManager.invokeAPI(
                self.apiManager.futureBinance.fapiPrivate_get_income, {"symbol": symbol}
            )

    ############### 서버시간 체크 ###############

    # 재혁 : 민제야 너 규칙대로 알아서 코드 바꾸렴 - 서버시간 체크
    def getServerTime(self):
        return int(
            self.apiManager.invokeAPI(
                self.apiManager.binance.public_get_time, None
            ).get("serverTime")
        )
