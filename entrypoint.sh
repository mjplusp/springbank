#!/bin/bash

python manage.py migrate
# python manage.py collectstatic
python manage.py collectstatic <<EOF
yes
EOF

celery multi start worker -A springbank -l INFO --beat
python manage.py runserver --settings=springbank.settings_prod 0.0.0.0:8000

# 정말 서비스 모드에선 gunicorn 으로 해야한다고 함.
# export DJANGO_SETTINGS_MODULE=springbank.settings_prod
# gunicorn springbank.wsgi:application --bind 0.0.0.0:8000