from .settings import *

CELERY_BROKER_URL = 'redis://redis-container:6379/0'
CELERY_RESULT_BACKEND = 'redis://redis-container:6379/0'

DEBUG = False
ALLOWED_HOSTS=['*']