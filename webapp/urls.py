import webapp.views as views
from django.urls import path

urlpatterns = [
  # django 
  path('bot_properties/', views.BotPropertiesView.as_view(), name = 'botProperties'),
  path('bot/<str:botName>/', views.BotSchedulerView.as_view(), name = 'botAction2'),
  path('bot/', views.BotSchedulerView.as_view(), name = 'botAction'),
  path('signup/', views.SignUpView.as_view(), name='SignUp'),
  path('test/', views.TestApiView.as_view(), name='Test'),
  path('check_price_detector/', views.CheckPriceDetectorAPI.as_view(), name='checkPriceDetector'),
  path('adjust_position/', views.AdjustPositionsView.as_view(), name='adjustPosition'),
  path('entering_price/<str:symbol>/', views.EnteringPriceDetectorApi.as_view(), name='enteringPrice'),
  path('leaving_price/<str:symbol>/', views.LeavingPriceDetectorApi.as_view(), name='leavingPrice'),
]