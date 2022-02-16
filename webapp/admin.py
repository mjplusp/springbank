from django.contrib import admin
from django.db.models.aggregates import Count
from django.db.models.expressions import ExpressionWrapper, OuterRef
from django.db.models.fields import DateField, FloatField, DateTimeField
from . import models
from decimal import Decimal as dec
from django.db.models import Sum, Subquery, F
from django.utils.html import format_html
from django.urls import reverse
from django_celery_beat.models import PeriodicTask


# Register your models here.

@admin.register(models.UserSignup)
class SignUp(admin.ModelAdmin):
    change_list_template = "admin/sign_up_change_list.html"

@admin.register(models.UserSummary)
class UserSummary(admin.ModelAdmin):
    change_list_template = "admin/user_summary_change_list.html"

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context=extra_context)

        try:
            qs = response.context_data["cl"].queryset
        except (AttributeError, KeyError):
            return response

        summary_metrics = {
            "total": Sum("incomefunding__funding_income"),
            "totalAsset": Subquery(
                models.Asset.objects.filter(
                    user=OuterRef("id"),
                    created_time__gte=ExpressionWrapper(OuterRef("incomefunding__date"), output_field=DateTimeField()),
                )
                .annotate(
                    totalAsset=F("value_spot") + F("value_futures") + F("usdt_reserve")
                )
                .order_by("created_time")
                .values("totalAsset")[:1]
            ),
            "daily_return_percentage": ExpressionWrapper(
                F("total") * 100 / F("totalAsset"), output_field=FloatField(5)
            ),
            "annual_return_percentage": ExpressionWrapper(
                F("daily_return_percentage") * 365, output_field=FloatField(5)
            ),
        }

        response.context_data["summary"] = list(
            qs.values("username", "incomefunding__date")
            .annotate(**summary_metrics)
            .order_by("-incomefunding__date")
        )

        response.context_data["summary_total"] = list(
            qs
            .values("username")
            .annotate(
                accumulated_fundingfee=Sum("incomefunding__funding_income"),
                accumulated_trade_profit=Subquery(
                    models.incomeCapital.objects
                    .values('action__user')
                    .annotate(
                        net_profit= ExpressionWrapper(Sum("total_selling_price") - Sum("total_buying_price") - Sum("total_commission"), output_field=FloatField())
                    )
                    .values('net_profit')
                ),
                total_profit = ExpressionWrapper(F('accumulated_fundingfee') + F('accumulated_trade_profit'), output_field=FloatField())
            )
        )

        response.context_data["collateral_ratio"] = list(
            models.CollateralRatio.objects.all().filter(user=request.user) if not request.user.is_superuser else models.CollateralRatio.objects.all()
        )

        response.context_data["periodic_task"] = list(
            models.PeriodicTaskProxy.objects
            .all()
            .filter(name__contains=request.user if not request.user.is_superuser else '')
            .annotate(action_url = reverse("botAction") + F("name") + "/?action=" + "stop")
            .values('name', 'enabled')
            # qs.values('username', )
            # .annotate(botName = Subquery(models.PeriodicTaskProxy.objects.filter(name__contains=OuterRef('username')).values_list('name')))
        )

        response.context_data["target_coins"] = list(
            models.TargetCoin.objects.all().filter(user = request.user) if not request.user.is_superuser else models.TargetCoin.objects.all()
        )

        return response

    def get_queryset(self, request):
        qs = super(UserSummary, self).get_queryset(request)
        return qs if request.user.is_superuser else qs.filter(username=request.user)


@admin.register(models.UserDetail)
class UserDetail(admin.ModelAdmin):
    def get_queryset(self, request):
        qs = super(UserDetail, self).get_queryset(request)
        return qs if request.user.is_superuser else qs.filter(user=request.user)

    list_display = ["user", "telegram_chat_id", "api_key", "secret_key"]


@admin.register(models.BotProperties)
class BotProperties(admin.ModelAdmin):
    def get_queryset(self, request):
        qs = super(BotProperties, self).get_queryset(request)
        return qs if request.user.is_superuser else qs.filter(user=request.user)

    list_display = [
        "user",
        "liquidation_bot_interval",
        "funding_optimization_minute",
        "leverage",
    ]


@admin.register(models.BotPropertiesAdvanced)
class BotPropertiesAdvanced(admin.ModelAdmin):
    def get_queryset(self, request):
        qs = super(BotPropertiesAdvanced, self).get_queryset(request)
        return qs if request.user.is_superuser else qs.filter(user=request.user)

    list_display = [
        "user",
        "margin_upper_bound",
        "margin_lower_bound",
        "margin_delta",
        "usdt_decimal",
        "usdt_reserve_ratio",
        "minimum_investment",
        "safe_investment_ratio",
        "deviation_window",
        "threshold_sigma",
    ]


@admin.register(models.TargetCoin)
class TargetCoin(admin.ModelAdmin):
    def get_queryset(self, request):
        qs = super(TargetCoin, self).get_queryset(request)
        return qs if request.user.is_superuser else qs.filter(user=request.user)

    list_display = ["user", "symbol", "is_investing"]
    ordering = ["user"]


@admin.register(models.Asset)
class AssetSnapshot(admin.ModelAdmin):
    def get_queryset(self, request):
        qs = super(AssetSnapshot, self).get_queryset(request)
        return qs if request.user.is_superuser else qs.filter(user=request.user)

    list_display = [
        "user",
        "created_time",
        "value_spot",
        "value_futures",
        "usdt_reserve",
        "total_value",
    ]
    list_per_page = 30

    @admin.display(description="Total Value")
    def total_value(self, obj):
        valueSpot = float(obj.value_spot) if obj.value_spot else 0
        valueFutures = float(obj.value_futures) if obj.value_futures else 0
        valueUsdt = float(obj.usdt_reserve) if obj.usdt_reserve else 0
        return round(valueSpot + valueFutures + valueUsdt, 2)

    # list_display_links = ['id', 'title']
    # list_editable = ['author']
    # list_filter = ['author', 'created_at']


@admin.register(models.incomeCapital)
class CapitalIncome(admin.ModelAdmin):
    def get_queryset(self, request):
        qs = super(CapitalIncome, self).get_queryset(request)
        return qs if request.user.is_superuser else qs.filter(action__user=request.user)

    list_display = [
        "getUser",
        "getCreatedTime",
        "getType",
        "getSymbol",
        "unit_selling_price",
        "unit_buying_price",
        "getProfitPerUnit",
        "amount",
        "getTotalProfit",
        "total_commission",
        "getNetProfit",
    ]
    list_per_page = 30

    @admin.display(description="User Name")
    def getUser(self, obj):
        return obj.action.user

    @admin.display(description="Action Time")
    def getCreatedTime(self, obj):
        return obj.action.created_time

    @admin.display(description="Action Type")
    def getType(self, obj):
        return obj.action.type

    @admin.display(description="Symbol")
    def getSymbol(self, obj):
        return obj.action.symbol

    @admin.display(description="Profit Per Unit")
    def getProfitPerUnit(self, obj):
        return round(float(obj.unit_selling_price) - float(obj.unit_buying_price), 6)

    @admin.display(description="Total Profit")
    def getTotalProfit(self, obj):
        return round(float(obj.total_selling_price) - float(obj.total_buying_price), 6)

    @admin.display(description="Net Profit")
    def getNetProfit(self, obj):
        return round(
            float(obj.total_selling_price)
            - float(obj.total_buying_price)
            - float(obj.total_commission),
            6,
        )


@admin.register(models.IncomeFunding)
class IncomeFunding(admin.ModelAdmin):
    def get_queryset(self, request):
        qs = super(IncomeFunding, self).get_queryset(request)
        return qs if request.user.is_superuser else qs.filter(user=request.user)

    list_display = [
        "user",
        "symbol",
        "date",
        "funding_time",
        "funding_income",
        "funding_rate",
        "getSum",
    ]

    @admin.display(description="Daily Total Funding Fee")
    def getSum(self, obj):
        result = models.IncomeFunding.objects.filter(
            date=obj.date, user=obj.user
        ).aggregate(sum=Sum("funding_income"))
        daily_funding_sum = round(float(result.get("sum")), 3)
        return format_html("<b><i>{}</i></b>", daily_funding_sum)
