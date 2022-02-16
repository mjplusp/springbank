import yaml
import os

class ApiKeys:
  def __init__(self, accessKey, secretKey):
    self.__accessKey = accessKey
    self.__secretKey = secretKey

  def getAccessKey(self):
    return self.__accessKey
  def getSecretKey(self):
    return self.__secretKey

def getApiKeys(site): 
  filename = os.path.join(os.path.dirname(__file__), 'apiKeys.yaml') # 'apiManager/apiKeys.yaml'
  with open(filename) as apiKeysFile:
    keys = yaml.load(apiKeysFile, Loader=yaml.FullLoader)

  if(site == "binance"):
    return ApiKeys(keys.get("binance").get("accessKey"), keys.get("binance").get("secretKey"))

  if(site == "upbit"):
    return ApiKeys(keys.get("upbit").get("accessKey"), keys.get("upbit").get("secretKey"))


