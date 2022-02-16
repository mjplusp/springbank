import requests
import json

def __getEnteringPriceApiUrl(symbol):
  return f'http://localhost:8000/springbank-quant/webapp/entering_price/{symbol}'

def __getLeavingPriceApiUrl(symbol):
  return f'http://localhost:8000/springbank-quant/webapp/leaving_price/{symbol}'

def getEnteringInfo(symbol):
  response = requests.get(__getEnteringPriceApiUrl(symbol))
  
  if(response.status_code == 200):
    return json.loads(response.text)
  elif(response.status_code == 404):
    print(f"Entering Price API URL Is Wrong for symbol {symbol}")
  else:
    print(f"Entering Price API Error for symbol {symbol} / status code : {response.status_code}")
  return None

def getLeavingInfo(symbol):
  response = requests.get(__getLeavingPriceApiUrl(symbol))
  
  if(response.status_code == 200):
    return json.loads(response.text)
  elif(response.status_code == 404):
    print(f"Leaving Price API URL Is Wrong for symbol {symbol}")
  else:
    print(f"Leaving Price API Error for symbol {symbol} / status code : {response.status_code}")
  return None

if __name__ == "__main__":
  print("[Step 1 : Entering Price Api Call")
  response = getEnteringInfo("btcusdt")
  print(response)
  print(f'Entering Price Mean : {response["mean"]} / Stdev : {response["stdev"]}')
  
  print("[Step 1 : Leaving Price Api Call")
  response2 = getLeavingInfo("btcusdt")
  print(response)
  print(f'Entering Price Mean : {response2["mean"]} / Stdev : {response2["stdev"]}')
