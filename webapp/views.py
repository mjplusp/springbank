from django.http import HttpResponse, JsonResponse
from rest_framework.views import APIView
from django_celery_beat.models import PeriodicTask
from . import models
from . import tasks
from .serializers import (
    BotPropertiesSerializer,
    BotQuerySerializer,
    BotRequestBodySerializer,
    SignUpRequestBodySerializer,
    BotPropertiesRequestBodySerializer,
    AdjustPositionsRequestBodySerializer,
    CheckPriceDetectorRequestBodySerializer
)
from rest_framework.parsers import JSONParser
from rest_framework.exceptions import APIException, NotAuthenticated, ParseError
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions
from django.db import transaction
from rest_framework.authtoken.models import Token
from django.contrib.auth.models import User
from django.contrib.auth.models import Group
from tools.LogicFunctions_v2 import LogicFunctions
from django.http import HttpResponseRedirect
from django.contrib import messages

from tools.PriceDetect_v2 import PriceDetector

import logging

logger = logging.getLogger("django")


class BotPropertiesView(APIView):
    # permission_classes=permissions.DjangoModelPermissionsOrAnonReadOnly
    def get(self, request):
        querySet = models.BotProperties.objects.all()
        serializer = BotPropertiesSerializer(querySet, many=True)
        return JsonResponse(serializer.data, safe=False)

    @swagger_auto_schema(request_body=BotPropertiesRequestBodySerializer)
    def post(self, request):
        data = JSONParser().parse(request)
        serializer = BotPropertiesSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return JsonResponse(serializer.data, status=201)
        return JsonResponse(serializer.errors, status=400)


class BotSchedulerView(APIView):
    # permission_classes=(permissions.DjangoModelPermissionsOrAnonReadOnly, )
    def get(self, request, botName):
        try:
            obj = PeriodicTask.objects.get(name=botName)
            isRunning = "Running" if obj.enabled else "Stopped"
            return JsonResponse(botName + " is " + isRunning, safe=False)
        except PeriodicTask.DoesNotExist as e:
            logger.error(e)
            return JsonResponse("NO " + botName, safe=False)

    @swagger_auto_schema(
        query_serializer=BotQuerySerializer, request_body=BotQuerySerializer
    )
    def post(self, request, botName):
        if not "action" in request.data:
            raise ParseError("action 정보가 없습니다.")

        action = request.data["action"]

        if not action in ["start", "stop"]:
            raise ParseError("action 은 start 나 stop 이어야 합니다.")

        # botName = JSONParser().parse(request)["botName"]

        try:
            obj = PeriodicTask.objects.get(name=botName)

            if action == "start":
                obj.enabled = True
                logger.info("START : " + botName)
            else:
                obj.enabled = False
                logger.info("STOP : " + botName)

            obj.save()

            if action == "start":
                return HttpResponseRedirect('/springbank-quant/admin/webapp/usersummary') #JsonResponse(botName + " ON", safe=False)
            else:
                return HttpResponseRedirect('/springbank-quant/admin/webapp/usersummary') #JsonResponse(botName + " OFF", safe=False)
        except PeriodicTask.DoesNotExist as e:
            logger.error(e)
            if action == "start":
                return HttpResponseRedirect(self.request.path_info) #JsonResponse(botName + " ON FAILED", safe=False)
            else:
                return HttpResponseRedirect(self.request.path_info) #JsonResponse(botName + " OFF FAILED", safe=False)


class SignUpView(APIView):
    @transaction.atomic
    @swagger_auto_schema(request_body=SignUpRequestBodySerializer)
    def post(self, request):
        userName = request.data["id"]
        password = request.data["password"]
        telegramChatId = request.data["telegramChatId"]

        firstName = request.data["firstName"]
        lastName = request.data["lastName"]
        email = request.data["email"]

        binanceApiKey = request.data["binanceApiKey"]
        binanceSecretKey = request.data["binanceSecretKey"]

        user = User.objects.create_user(
            username=userName,
            password=password,
            first_name=firstName,
            last_name=lastName,
            email=email,
            is_staff=True,
        )
        user.groups.add(Group.objects.get(name='Springbank_Quant_Staff'))
        
        userDetail = models.UserDetail(
            user=user,
            telegram_chat_id=telegramChatId,
            api_key=binanceApiKey,
            secret_key=binanceSecretKey,
        )

        user.save()
        userDetail.save()

        # 기본 Bot Property 추가
        models.BotProperties(user=user).save()

        # 기본 Bot Property Advanced 추가
        models.BotPropertiesAdvanced(user=user).save()

        token = Token.objects.create(user=user)

        tasks.scheduleRebalancingBotTask(userId=user.username)
        tasks.scheduleLiquidationPreventionBotTask(userId=user.username)
        tasks.scheduleAssetRecordingBotTask(userId=user.username)
        tasks.scheduleFundingFeeRecordingBotTask(userId=user.username)

        return HttpResponseRedirect('/springbank-quant/admin/webapp/usersummary') #JsonResponse({"Token": token.key}, safe=False)

    def delete(self, request):
        pass


class CheckPriceDetectorAPI(APIView):
    @swagger_auto_schema(request_body=CheckPriceDetectorRequestBodySerializer)
    def post(self, request):
        if not "symbol" in request.data:
            raise ParseError("symbol 정보가 없습니다.")
        
        from tools.PriceDetect_v2 import PriceDetector, spotMaxLen, futureMaxLen

        priceDetector = PriceDetector()
        # print(priceDetector)

        symbol = request.data["symbol"].lower()

        spotLength = len(priceDetector.spotDic[symbol]["askP"])
        futuresLength = len(priceDetector.futureDic[symbol]["bidP"])

        enteringInfo = priceDetector.getEnteringInfo(symbol=symbol)
        leavingInfo = priceDetector.getLeavingInfo(symbol=symbol)

        returnObj = {
            "entering":{
                "spotLength": spotLength,
                "maxSpotLength": spotMaxLen,
                "futuresLength": futuresLength,
                "maxFuturesLength": futureMaxLen,   
                "enteringInfo": enteringInfo
            },
            "leaving":{
                "spotLength": spotLength,
                "maxSpotLength": spotMaxLen,
                "futuresLength": futuresLength,
                "maxFuturesLength": futureMaxLen,
                "leavingInfo": leavingInfo
            }
        }
        if futuresLength < futureMaxLen:
            messages.error(request, f"wait more time [Spot]: {spotLength}/{spotMaxLen} <br/> [Futures]: {futuresLength}/{futureMaxLen}")
        else:
            messages.success(request, f"can adjust positions [Spot]: {spotLength}/{spotMaxLen} <br/> [Futures]: {futuresLength}/{futureMaxLen}")
        # request.session['spotLength'] = spotLength
        # request.session['maxSpotLength'] = spotMaxLen
        # request.session['futuresLength'] = futuresLength
        # request.session['maxFuturesLength'] = futureMaxLen

        # request.session['enteringMean'] = enteringInfo['mean']
        # request.session['enteringStdev'] = enteringInfo['stdev']

        # request.session['leavingMean'] = leavingInfo['mean']
        # request.session['leavingStdev'] = leavingInfo['stdev']

        return HttpResponseRedirect('/springbank-quant/admin/webapp/usersummary')

        
class TestApiView(APIView):
    def get(self, request):
        try:
            user = User.objects.get(username="admin")

            print(user.username)

            return JsonResponse(request.user.username, safe=False)
        except models.User.DoesNotExist as e:
            logger.error("admin 에 해당하는 User 가 없습니다.")
            return JsonResponse("fail", safe=False)


class EnteringPriceDetectorApi(APIView):
    def get(self, request, symbol):
        enteringInfo = PriceDetector().getEnteringInfo(symbol=symbol.lower())
        return JsonResponse(enteringInfo, safe=False)

class LeavingPriceDetectorApi(APIView):
    def get(self, request, symbol):
        leavingInfo = PriceDetector().getLeavingInfo(symbol=symbol.lower())
        return JsonResponse(leavingInfo, safe=False)
        
class AdjustPositionsView(APIView):
    @swagger_auto_schema(
        query_serializer=AdjustPositionsRequestBodySerializer,
         request_body=AdjustPositionsRequestBodySerializer
    )
    def post(self, request):
        if not "username" in request.data:
            raise ParseError("username 정보가 없습니다.")
        if not "action" in request.data:
            raise ParseError("action 정보가 없습니다.")
        if not "symbol" in request.data:
            raise ParseError("symbol 정보가 없습니다.")
        if not "notional_amount" in request.data:
            raise ParseError("notional_amount 정보가 없습니다.")
        if not request.user.username:
            raise NotAuthenticated("로그인해주세요")

        username = request.data['username']
        action = request.data["action"]
        symbol = request.data["symbol"]
        notional_amount = request.data["notional_amount"]

        # symbol = request.data["symbol"]
        # notional_amount = request.data["notional_amount"]
        if action == "enter":
            taskID = tasks.enterPositionTask.delay(username, symbol, notional_amount)
        elif action == "leave":
            taskID = tasks.leavePositionTask.delay(username, symbol, notional_amount)
        
        messages.success(request, f"{action} {symbol} request has sent with Task ID: {taskID}.")
        messages.success(request, "The task will be terminated in 30 minutes. Orders not completed in 30 minutes will be killed")
        
        return HttpResponseRedirect('/springbank-quant/admin/webapp/usersummary/') # JsonResponse("success", safe=False)
