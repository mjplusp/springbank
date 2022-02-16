from rest_framework import serializers
from .models import BotProperties


class BotPropertiesSerializer(serializers.ModelSerializer):
    class Meta:
        model = BotProperties
        fields = ["user", "code", "key", "value", "description"]


class BotQuerySerializer(serializers.Serializer):
    action = serializers.ChoiceField(
        help_text="봇 동작/정지", choices=("start", "stop"), required=True
    )


class BotRequestBodySerializer(serializers.Serializer):
    botName = serializers.ChoiceField(
        help_text="봇 이름",
        choices=(
            "calculate_bot",
            "liquidation_prevention_bot",
            'rebalancing_bot',
            'test_bot'
        ),
        required=True,
    )

class SignUpRequestBodySerializer(serializers.Serializer):
    id = serializers.CharField(help_text="User Id", required=True)
    password = serializers.CharField(help_text="Password", required=True)
    telegramChatId = serializers.CharField(help_text="Telegram Chat Id", required=True)

    firstName = serializers.CharField(help_text="First Name", required=False)
    lastName = serializers.CharField(help_text="Last Name", required=False)
    email = serializers.EmailField(help_text="email", required=False)

    binanceApiKey = serializers.CharField(help_text="Binance Api Key", required=False)
    binanceSecretKey = serializers.CharField(help_text="Binance Secret Key", required=False)

class BotPropertiesRequestBodySerializer(serializers.Serializer):
    liquidationBotInterval = serializers.IntegerField(help_text="민제가 채워주길")
    fundingOptimizationMinute = serializers.IntegerField(help_text="민제가 채워주길")
    leverage = serializers.IntegerField(help_text="레버리지")

    marginUpperBound = serializers.FloatField(help_text="MARGIN_UPPERBOUND")
    marginLowerBound = serializers.FloatField(help_text="MARGIN_LOWERBOUND")
    marginDelta = serializers.FloatField(help_text="MARGIN_DELTA")
    usdtDecimal = serializers.FloatField(help_text="USDT_DECIMAL")
    usdtReserveRatio = serializers.FloatField(help_text="USDT_RESERVE_RATIO")
    minimumInvestment = serializers.FloatField(help_text="MINIMUM_INVESTMENT")
    safeInvestmentRatio = serializers.FloatField(help_text="SAFE_INVESTMENT_RATIO")
    deviationWindow = serializers.FloatField(help_text="DEVIATION_WINDOW")
    thresholdSigma = serializers.FloatField(help_text="THRESHOLD_SIGMA")

class AdjustPositionsRequestBodySerializer(serializers.Serializer):
    username = serializers.CharField(help_text="username", required=True)
    action = serializers.ChoiceField(
        help_text="포지션 진입/정리", choices=("enter", "leave"), required=True
    )
    symbol = serializers.CharField(help_text="symbol", required=True)
    notional_amount = serializers.CharField(help_text="notional amount", required=True)

class CheckPriceDetectorRequestBodySerializer(serializers.Serializer):
    symbol = serializers.CharField(help_text="symbol", required=True)