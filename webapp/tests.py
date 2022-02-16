from django.test import TestCase
from django.contrib.auth.models import User
from . import models
from tools.LogicFunctions_v2 import LogicFunctions
import logging

logger = logging.getLogger("django")


# Create your tests here.
# 테스트 실행 방법

# python mange.py test

# django 각각의 앱들을 순회하면서 모든 test.py 를 가져와서 클래스들을 불러오게 됨

# class 내부에 test_ 로 시작하는 함수들을 실행하고 그 결과를 반환하게 됨

# setUp 함수는 단위테스트를 실행하기 전에 공통적으로 수행할 어떤 작업의 내용을 넣어줌.

# 여기에 쓴 코드는 test_가 붙은 함수들에 decorator처럼 붙어서 테스트 실행시 setUp먼저 실행되고 test_ 함수가 실행된다고 보면 됨
class dbInputTest(TestCase):
    def setUp(self):
        user = User.objects.create_user(username="minje", password="minje")
        user.save()
        # 기본 Bot Property 추가
        models.BotProperties(user_id=user).save()
        # 기본 Bot Property Advanced 추가
        models.BotPropertiesAdvanced(user_id=user).save()

        self.lf = LogicFunctions(
            "minje",
            "apikey",
            "secretkey",
        )

    def test_save_Order(self):
        orderInfo = self.lf.get_order_model(
            symbol="XRPUSDT", order_id="2326979140", is_spot=True, is_buyer=False
        )
        order = orderInfo.get("order")
        order_detail = orderInfo.get("order_detail")
        first_tx = orderInfo.get("tx_input_set")[0]

        print(order.binance_order_number)
        print(order.user_id)
        print(order.symbol)
        print(order_detail.order)
        print(order_detail.amount)
        print(order_detail.price)
        print(order_detail.quote_price)
        print(order_detail.commission_usdt)

    def test_save_action(self):
        orderlist = [
            {
                "order_id": "5263201033",
                "symbol": "DOGEUSDT",
                "is_spot": False,
                "is_buyer": False,
            },
            {
                "order_id": "5263753002",
                "symbol": "DOGEUSDT",
                "is_spot": False,
                "is_buyer": True,
            },
        ]

        self.lf.save_action(action_type="ORDER", symbol="DOGEUSDT", orders=orderlist)
