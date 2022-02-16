import requests
import logging
import json
import ssl
import pathlib
from requests.models import Response
import websockets
import asyncio
import numpy as np

logger = logging.getLogger("django")

ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
self_signed_cert = pathlib.Path(__file__).parent.with_name("selfsigned.crt")
ssl_context.load_verify_locations(self_signed_cert)


minutes = 20
spotMaxLen = minutes * 60 # 1000 ms 에 한번
futureMaxLen = minutes * 60 * 2 # 500 ms 에 한번

def getFutureTickerInfo():
    response = requests.get(
        "https://www.binance.com/fapi/v1/ticker/bookTicker"
    ).text  # api 2회 소모
    return [
        element.get("symbol")
        for element in json.loads(response)
        if element.get("symbol").endswith("USDT")
    ]


def getSpotTickerInfoInFutureTickerInfo(futureTickerInfo):
    response = requests.get(
        "https://www.binance.com/api/v3/ticker/bookTicker"
    ).text  # api 2회 소모
    return [
        element.get("symbol").lower() # 중요 !!
        for element in json.loads(response)
        if element.get("symbol").endswith("USDT")
        and element.get("symbol") in futureTickerInfo
    ]

class PriceDetector:
    def __new__(self, *args, **kwargs):
        if not hasattr(self, '_instance'):
            self._instance = super().__new__(self)
            self.__initialize(self._instance)
        return self._instance

    def __initialize(cls):
        logger.info("INITIALIZE PRICE DETECTOR")
        cls.tickers = getSpotTickerInfoInFutureTickerInfo(getFutureTickerInfo())
        cls.spotDic = cls.__initDic(cls.tickers)
        cls.futureDic = cls.__initDic(cls.tickers)

    def __initDic(self, tickers):
        dic = {}
        for ticker in tickers:
            dic[ticker] = {}
            dic[ticker]["bidP"] = []
            dic[ticker]["bidQ"] = []
            dic[ticker]["askP"] = []
            dic[ticker]["askQ"] = []
        return dic

    def connWebSocket(self):
        # try:
        logger.info("INIT ASYNC LOOP IN PRICE DETECTOR")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        groups = self.getWebSocketAsyncGroup()
        loop.run_until_complete(groups)
        # except Exception as e:
        #     print(e)
        #     # 여기서 연결이 끊어졌을때 처리를 해줘야 함.
        #     pass
    def getWebSocketAsyncGroup(self):
        return asyncio.gather(
            FutureRecvTicker(self.tickers, self.futureDic),
            SpotRecvTicker(self.tickers, self.spotDic))
    
    def getEnteringInfo(self, symbol):
        futureBidP = self.futureDic[symbol]["bidP"]
        spotAskP = self.spotDic[symbol]["askP"]

        futurelen = len(futureBidP)
        # if futurelen < futureMaxLen: # 20분 다 안 채우고 10분만 채워도 괜찮을 듯
        #     logger.info(f'Price Detector is not ready for {symbol} - future : {futurelen} / {futureMaxLen}, spot : {len(spotAskP)} / {spotMaxLen}')
        #     return {
        #         "mean" : None,
        #         "stdev" : None
        #     }
        diffs = [(futureBidP[i*2] - x) for i,x in enumerate(spotAskP) if i < (futurelen // 2)]
        return {
            "mean" : np.mean(diffs),
            "stdev" : np.std(diffs)
        }

    def getLeavingInfo(self, symbol):
        futureAskP = self.futureDic[symbol]["askP"]
        spotBidP = self.spotDic[symbol]["bidP"]
        
        futurelen = len(futureAskP)

        # if futurelen < futureMaxLen: # 20분 다 안 채우고 10분만 채워도 괜찮을 듯
        #     logger.info(f'future : {futurelen} / {futureMaxLen} spot : {len(spotBidP)} / {spotMaxLen}')
        #     return {
        #         "mean" : None,
        #         "stdev" : None
        #     }
        diffs = [x - futureAskP[i*2] for i,x in enumerate(spotBidP) if i < futurelen // 2]
        return {
            "mean" : np.mean(diffs),
            "stdev" : np.std(diffs)
        }

def __handleStreamInternal(container, value, maxLen):
    if len(container) == maxLen:
        container.pop(0)
    container.append(value)

def handleStream(dic, symbol, bidP, bidQ, askP, askQ, maxLen):
    data = dic[symbol]
    # print(f'{symbol} - bid : {bidP} / {bidQ} // ask : {askP} / {askQ} ] {maxLen}')

    __handleStreamInternal(data["bidP"], bidP, maxLen)
    __handleStreamInternal(data["bidQ"], bidQ, maxLen)
    __handleStreamInternal(data["askP"], askP, maxLen)
    __handleStreamInternal(data["askQ"], askQ, maxLen)

def getSpotWebsocketUrl(tickerList):
    params = "/".join([f"{ticker}@depth5@1000ms" for ticker in tickerList])
    return f"wss://stream.binance.com:9443/stream?streams={params}"

async def SpotRecvTicker(tickerList, spotDic):
    url = getSpotWebsocketUrl(tickerList=tickerList)

    logger.info(f"SPOT WEBSOCKET CONNECT TO {url}")

    try:
        async for websocket in websockets.connect(url, ssl=ssl_context):
            try:
                logger.info("======SPOT WEBSOCKET SUCCESS======")
                while True:
                    response = json.loads(await websocket.recv())
                    bid = response["data"]["bids"][0]
                    ask = response["data"]["asks"][0]
                    handleStream(
                        dic=spotDic,
                        symbol=response["stream"].split("@")[0].lower(),
                        bidP=float(bid[0]),
                        bidQ=float(bid[1]),
                        askP=float(ask[0]),
                        askQ=float(ask[1]),
                        maxLen=spotMaxLen,
                    )
            except websockets.ConnectionClosed as e:
                logger.info("======SPOT WEBSOCKET RECONNECT======")
                continue
            except Exception as e:
                logger.error("======SPOT WEBSOCKET ERROR======")
                logger.error(e)

        logger.info("end")
    except Exception as e:
        logger.error("======SPOT WEBSOCKET CONNECTION ERROR======")
        logger.error(e)


def getFutureWebsocketUrl(tickerList):
    params = "/".join([f"{ticker}@depth5@500ms" for ticker in tickerList])
    return f"wss://fstream.binance.com/stream?streams={params}"


async def FutureRecvTicker(tickerList, futureDic):
    url = getFutureWebsocketUrl(tickerList=tickerList)

    logger.info(f"FUTURE WEBSOCKET CONNECT TO {url}")

    try:
        async for websocket in websockets.connect(url, ssl=ssl_context):
            try:
                logger.info("======FUTURE WEBSOCKET SUCCESS======")
                while True:
                    response = await websocket.recv()
                    responseData = json.loads(response)["data"]
                    bid = responseData["b"][0]
                    ask = responseData["a"][0]
                    handleStream(
                        dic=futureDic,
                        symbol=responseData["s"].lower(),
                        bidP=float(bid[0]),
                        bidQ=float(bid[1]),
                        askP=float(ask[0]),
                        askQ=float(ask[1]),
                        maxLen=futureMaxLen,
                    )
            except websockets.ConnectionClosed as e:
                logger.info("======FUTURE WEBSOCKET RECONNECT======")
                continue
            except Exception as e:
                logger.error("======FUTURE WEBSOCKET ERROR======")
                logger.error(e)

    except Exception as e:
        logger.error("======FUTURE WEBSOCKET CONNECTION ERROR======")
        logger.error(e)

async def test():
    print("calculating go")
    await asyncio.sleep(5)
    print("===endend===")
    priceDetect = PriceDetector()
    print(priceDetect.getEnteringInfo("btcusdt"))
    print(priceDetect.getLeavingInfo("btcusdt"))
    
if __name__ == "__main__":
    priceDetect = PriceDetector()
    print(priceDetect.tickers)
    
    loop = asyncio.get_event_loop()
    group1 = priceDetect.getWebSocketAsyncGroup()
    group2 = asyncio.gather(group1, test())
    
    loop.run_until_complete(group2)