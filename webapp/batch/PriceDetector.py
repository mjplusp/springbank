from tools.PriceDetect_v2 import PriceDetector
import threading

# 코드를 더 깔끔하게 할 방법이 없다. 여기서 그냥 스레드를 판다.
def startPriceDetector():
  threading.Thread(target=PriceDetector().connWebSocket).start()