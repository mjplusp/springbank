# /docker-server/jin_crawler/Dockerfile
# docker-server
#   - manage.py
#   - Dockerfile
#

FROM python:3.9.6
# Docker의 python버전을 설정

RUN apt-get -y update
RUN apt-get -y install vim
# docker 안에서 vim설치를 하도록

RUN mkdir -p /srv/docker-server/logs
RUN mkdir -p /srv/docker-server/static
RUN mkdir -p /srv/docker-server/database

# docker안에서 srv/docker-server 폴더 생성
# ADD . /srv/docker-server
# 현재 디렉토리를 통째로 srv/docker-server 폴더에 복사

WORKDIR /srv/docker-server
# 작업 디렉토리 설정
COPY bots bots
COPY apiManager apiManager
COPY tools tools
COPY springbank springbank
COPY exceptions exceptions
COPY webapp webapp
COPY manage.py  manage.py
COPY requirements.txt  requirements.txt
COPY entrypoint.sh entrypoint.sh
COPY selfsigned.key  selfsigned.key
COPY selfsigned.crt  selfsigned.crt


RUN mkdir -p /srv/docker-server/static
RUN pip install --upgrade pip
# pip 업그레이드
RUN pip install -r requirements.txt
#필수 패키지 설치

RUN python manage.py migrate

EXPOSE 8000
ENTRYPOINT [ "/bin/bash", "/srv/docker-server/entrypoint.sh" ]

# docker run -p 8000:8000 image 로 실행 해주자
