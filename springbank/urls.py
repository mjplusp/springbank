"""springbank URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from django.conf.urls import include
from webapp import views
from drf_yasg.views import get_schema_view
from drf_yasg import openapi
from rest_framework.permissions import AllowAny

schema_view = get_schema_view(
    openapi.Info(
        title="SpringBank",  # 타이틀
        default_version="v1",  # 버전
        description="spring bank 의 API 설명서입니다.",  # 설명
        terms_of_service="http://github.com/springbankquant/springbank",
        # contact=openapi.Contact(name="Spring Bank", email="jjh2613@gmail.com")
    ),
    validators=["flex"],
    public=True,
    permission_classes=(AllowAny,),
)

original_urlpatterns = [
    # path(
    #     r"swagger(?P<format>\.json|\.yaml)",
    #     schema_view.without_ui(cache_timeout=0),
    #     name="schema-json",
    # ),
    path(
        r"swagger",
        schema_view.with_ui("swagger", cache_timeout=0),
        name="schema-swagger-ui",
    ),
    path(
        r"redoc", schema_view.with_ui("redoc", cache_timeout=0), name="schema-redoc-v1"
    ),
    path("admin/", admin.site.urls),
    path("webapp/", include("webapp.urls")),
]

urlpatterns = [
    # prefix
    path('springbank-quant/', include(original_urlpatterns)),
]