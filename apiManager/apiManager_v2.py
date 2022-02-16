import requests
import ccxt
import logging
import yaml
import pathlib

logger = logging.getLogger("django")
class ApiManager:  
  def __init__(self, userDetail):
    # 현물 binance
    self.userDetail = userDetail
    self.binance = ccxt.binance({
      'apiKey': userDetail.api_key,
      'secret': userDetail.secret_key,
      "enableRateLimit": True,
    })

    # 선물 binance
    self.futureBinance = ccxt.binance({
      'apiKey': userDetail.api_key,
      'secret': userDetail.secret_key,
      "enableRateLimit": True,
      "options": {
        "defaultType" : "future"
      }
    })
    ymlfile = pathlib.Path(__file__).with_name("apiManagerProperties.yaml")
    with open(ymlfile) as apiManagerFile:
      apiManagerProperties = yaml.load(apiManagerFile, Loader=yaml.FullLoader)
      self.__maxIteration = apiManagerProperties.get("maxIteration")
      self.__telegramToken = apiManagerProperties.get("telegramToken")
  def getApiKeys(self):
    return self.__apiKeys  
  def invokeReadOnlyAPI(self, method, args):
    return self.invokeAPI(method, args)
  
  def invokeAPI(self, method, args):
    success = True
    result = ""
    for i in range(0, self.__maxIteration):      
      try:
        result = method(args)
        if self.__isApiError(result):
          logger.info("ERROR on ", i, " th loop")
          continue

        break
      # Binance 에서 준 에러는 다시 할 필요가 없음
      except ccxt.ExchangeError as ee:
        # 오류 케이스 01. 'binance {"code":-4046,"msg":"No need to change margin type."}'
        if('"code":-4046' in ee.args[0]):
          # print(ee, args)
          success = True          
          break
        # 오류 케이스 02. 잔고가 부족함
        elif("Account has insufficient balance for requested action" in ee.args[0]):
          success = True          
          # 여기가 orderSpotSell / orderSpotBuy 가 아닌 곳에서 터질수도 있음.
          # arg 를 orderSpotSell / orderSpotBuy 시나리오를 가정하고 썼음.
          logger.info("현물 잔고가 부족합니다.", args.get("symbol"), " -- ", args.get("quantity"))          
          break
        else:
          logger.info(ee)
          success = False
          result = ee + args;
          break

      except Exception as e:  
        result = str(e.args) + " --- " + args

    if(success):
      # Success      
      return result
    else:
      # Fail
      self.__alarm(result)
      return "fail"

  def transactional(self, args):
    logger.info("transactional")    
  
  def __isApiError(self, result):
    return self.__isRunTimeError(result) | self.__isApplicationTimeRror(result)    

  def __isRunTimeError(self, result):
    # 앞으로 여기 내부 내용을 채워나가야 함
    if("get" not in result):
      return False
    if(result.get("msg") != None): # code 200을 제외하면 다 실패인데 200으로 해둔다면..?
      logger.info(result.get("code"))
      logger.info("RESULT :", result.get("msg"))
      if(result.get("msg") == "-1021=Timestamp for this request was 1000ms ahead of the server's time."):
        logger.info("Windows10 의 경우 시계 동기화를 실행하세요 (참고: https://rootblog.tistory.com/223)")
      return True
    else:
      return False
  
  def __isApplicationTimeRror(self, result):
    # 앞으로 여기 내부 내용을 채워나가야 함
    return False  
  
  def __alarm(self, result):    
    self.__telegramAlarm("Error : " + result)    

  def __telegramAlarm(self, message):
    logger.info("Telegram Bot Alarm")

    rootUrl = "https://api.telegram.org/bot" + self.__telegramToken
    serviceUrl = rootUrl + "/sendmessage?text=" + message

    response = requests.post(serviceUrl + "&&chat_id=" + str(self.userDetail.user.username))
    logger.info(response)

  # check user Token https://api.telegram.org/bot1770113125:AAH-JsmwxpZFqp-l5m3CDIO5zGoG6nAZTDY/getUpdates