from django.db import models
from django.contrib.auth.models import User
from decimal import Decimal as dec
from django_celery_beat.models import PeriodicTask, CrontabSchedule

from django.db.models.fields import proxy

""" 검정색 영역 : 실제 거래가 일어날 때 업데이트 될 내용들 """


class UserManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_superuser=False)

class UserSummary(User):
    objects = UserManager()
    class Meta:
        proxy = True
        verbose_name = ".Dashboard"
        verbose_name_plural = ".Dashboard"

class UserSignup(User):
    objects = UserManager()
    class Meta:
        proxy = True
        verbose_name = "__User Signup"
        verbose_name_plural = "__User Signup"

class PeriodicTaskProxy(PeriodicTask):
    class Meta:
        proxy = True

class UserDetail(models.Model):
    class Meta:
        verbose_name = "__User Detail"

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    telegram_chat_id = models.CharField(max_length=255)
    api_key = models.CharField(max_length=255, null=True)
    secret_key = models.CharField(max_length=255, null=True)


class BotProperties(models.Model):
    class Meta:
        verbose_name = "__Bot Property"
        verbose_name_plural = "__Bot Properties"

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    liquidation_bot_interval = models.IntegerField(default=900)
    funding_optimization_minute = models.IntegerField(default=30)
    leverage = models.IntegerField(default=4)


class BotPropertiesAdvanced(models.Model):
    class Meta:
        verbose_name = "__Bot Property Advanced"
        verbose_name_plural = "__Bot Properties Advanced"

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    margin_upper_bound = models.FloatField(default=0.26)
    margin_lower_bound = models.FloatField(default=0.14)
    margin_delta = models.FloatField(default=0.01)
    usdt_decimal = models.FloatField(default=0.01)
    usdt_reserve_ratio = models.FloatField(default=0.1)
    minimum_investment = models.FloatField(default=100)
    safe_investment_ratio = models.FloatField(default=0.98)
    deviation_window = models.FloatField(default=20)
    threshold_sigma = models.FloatField(default=1.2)
    
class Asset(models.Model):  # 자산 로그
    class Meta:
        verbose_name = "Asset Snapshot"

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    created_time = models.DateTimeField(auto_now=True)  # Created Time
    value_spot = models.CharField(
        max_length=255,
    )  # 현물 가치 (관리코인)
    value_futures = models.CharField(
        max_length=255,
    )  # 선물 마진 가치 (관리코인)
    usdt_reserve = models.CharField(
        max_length=255,
    )  # 선물 마진 가치


class TargetCoin(models.Model):  # 관리 코인
    class Meta:
        verbose_name = "__Target Coin"

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    symbol = models.CharField(
        max_length=255,
    )
    is_investing = models.BooleanField()

class CollateralRatio(models.Model):  # 담보 비율
    class Meta:
        verbose_name = "Collateral Ratio"
        unique_together = (('user', 'symbol'),)

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    symbol = models.CharField(
        max_length=255,
    )
    collateral_ratio = models.FloatField()
    created_time = models.DateTimeField(auto_now=True)  # Created Time



# class Positions(models.Model):
#     user_id = models.ForeignKey(User, on_delete=models.CASCADE, db_column="USER_ID")
#     symbol = models.CharField(max_length=255)
#     is_spot = models.BooleanField()  # 현물/선물
#     quantity = models.CharField(max_length=255)  # 보유 수량
#     avg_Price = models.CharField(
#         max_length=255,
#     )  # 개당 평균진입가격 (USDT)


""" 파란색 영역 : 바이낸스 거래 시도를 따라가는 내용? """


class Action(models.Model):
    action_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    created_time = models.DateTimeField(
        auto_now=True,
    )  # Created Time
    symbol = models.CharField(max_length=255)
    # 요부분 순서는 알아서 바꾸면 됨
    ActionTypeChoices = (
        ("ENTER", "ORDER"),  # 포지션 진입
        ("CLOSE", "CLOSE"),  # 포지션 종료
        ("LIQUIDATION_PREVENTION", "LIQUIDATION_PREVENTION"),  # 청산 방지
        ("COIN_SYNC", "COIN_SYNC"),  # 수량 맞추기
    )

    type = models.CharField(max_length=255, choices=ActionTypeChoices)


class Order(models.Model):
    # 중요.
    binance_order_number = models.CharField(max_length=255, primary_key=True)

    # action 과 binance order number 간에 누가 primary key 인가 ???
    # 설계를 약간 바꿔야할수도 있겠다.
    action_id = models.ForeignKey(
        Action, on_delete=models.CASCADE, db_column="ACTION_ID", null=True
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    is_spot = models.BooleanField()  # 현물/선물
    is_buy = models.BooleanField()  # BUY/SELL 여부
    order_timestamp = models.DateTimeField()  # Created Time
    symbol = models.CharField(max_length=255)


class OrderDetail(models.Model):
    # 중요.
    order = models.OneToOneField(Order, on_delete=models.CASCADE, primary_key=True, db_column="BINANCE_ORDER_NUMBER")
    amount = models.CharField(max_length=255)
    price = models.CharField(
        max_length=255,
    )  # 개당 평균진입가격 (USDT)
    quote_price = models.CharField(
        max_length=255,
    )  # 총 가격
    commission_usdt = models.CharField(
        max_length=255,
    )  # USDT 환산 수수료


class Transaction(models.Model):
    tx_id = models.CharField(max_length=255, primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, db_column="BINANCE_ORDER_NUMBER", null=True
    )

    tx_timestamp = models.DateField()

    # 여기도 binance 주문 번호 있음
    # binanceOrderNumber
    symbol = models.CharField(max_length=255)
    price = models.CharField(max_length=255)
    amount = models.CharField(max_length=255)
    # total price 가 아니고??
    quote_price = models.CharField(
        max_length=255,
    )  # 총 가격
    commission = models.CharField(max_length=255)  # 수수료
    commission_asset = models.CharField(
        max_length=255,
    )  # 수수료 단위
    commission_usdt = models.CharField(
        max_length=255,
    )  # USDT 환산 수수료


######## 노란색 통계 관련 #####
class IncomeFunding(models.Model):
    symbol = models.CharField(max_length=255)

    user = models.ForeignKey(User, on_delete=models.CASCADE)

    date = models.DateField(null=True)  # 날짜

    FundingTimeChoices = (
        (1, 1),  # 1 시 펀딩
        (9, 9),  # 9 시 펀딩
        (17, 17),  # 17 시 펀딩
    )
    funding_time = models.IntegerField(choices=FundingTimeChoices)
    funding_income = models.CharField(
        max_length=255,null=True
    )
    funding_rate = models.CharField(
        max_length=255,null=True
    )


class incomeCapital(models.Model):
    action = models.OneToOneField(
        Action, on_delete=models.CASCADE, db_column="ACTION_ID", primary_key=True
    )  # 정리 action id
    unit_selling_price = models.CharField(
        max_length=255, null=True
    )  # 판매가격
    unit_buying_price = models.CharField(
        max_length=255,null=True
    )  # 구매가격
    amount = models.CharField(
        max_length=255, null=True
    )
    total_selling_price = models.CharField(
        max_length=255, null=True
    )  # 판매가격
    total_buying_price = models.CharField(
        max_length=255,null=True
    )  # 구매가격
    total_commission = models.CharField(
        max_length=255,null=True
    )  # 두번의 주문에서 발생된 총 수수료