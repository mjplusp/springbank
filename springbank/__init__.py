# -*- coding: utf-8 -*-
# 이렇게 설정해주면 Django가 시작할떄 Celery가 항상 import 되고
# shared_task 데코레이션이 Celery를 이용하게됩니다.
from .celery_settings import app as celery_app

__all__ = ("celery_app",)
