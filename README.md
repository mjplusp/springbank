# springbank
Leveraged Coin Funding Fee Earning Program

Celery 작동법
$ celery -A springbank worker -l INFO --beat

Django 작동법
$ python manage.py runserver

0. 웹소켓 보안세팅에 필요한 cert 파일 세팅
$ openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout selfsigned.key -out selfsigned.crt


Django 배포 모드로 동작하는 법


0. ssl 인증을 받아, selfsigned.crt, selfsigned.key 를 만든다.
$ openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout selfsigned.key -out selfsigned.crt

1. static 파일들을 모은다.
$ python manage.py collectstatic

2. cellery 동작
$ celery multi start worker -A springbank -l INFO --beat

3. 서버 동작
$ python manage.py runserver --settings=springbank.settings_prod
# 참고
Django Admin 사용법

$ python manage.py runserver 이후 http://localhost:8000/admin 에서 user 를 관리할 수 있다.

$ python manage.py createsuperuser 명령어를 통해 임의의 super user 를 만들어 관리자페이지에 로그인할 수 있다.

# 12/02 수정사항

1. celery.py가 pip로 다운받은 celery 패키지와 계속 헷갈리는듯 에러 발생으로 (Celery 클래스를 찾을 수 없다고 나옴) 
    celery.py -> celery_settings.py 로 수정. 해당 모듈을 import한 모듈의 import 구문도 수정
2. requirements.txt 내 celery, click, kombu, numpy 모듈의 최신본이 다운받아지지 않아 이전 버전 중 최신 것으로 교체
3. MainTradeBot_v3 내 로깅 관련 오류 수정, ntpbot 수정 (관련 NTP 모듈도 같이 수정. 리눅스에 맞도록)
4. models.py에서 정수형 column의 경우 length를 지정하지 않는듯. 컬럼 정의부에서 maxlength = 127 등의 파라미터 삭제


# 공부하며 정리한 사용법 (윈도우 기준)

1. 기본 플로우
    - Celerybeat가, 혹은 직접 작업을 지시했을 경우, 작업은 Redis 큐에 들어감
    - Celery Worker가 Django 안에 정의된 대로 작업을 수행

2. 실행한 것들

    - 윈도우 내 WSL(Windows Subsystem for Linux) 설치 
        (단, wsl 이용 시 네트워크 속도는 느려짐. 따라서 time limit 초과해 에러 발생할 수 있으나 이는 리눅스에서 돌리면 문제 없을 듯)
        (처음에 셋업하면서 일시적으로 느려지고 시간이 지나며 정상화되는것 같음)
        https://docs.microsoft.com/ko-kr/windows/wsl/install

    - 윈도우 스토어에서 원하는 Ubuntu 버전 설치

    - VScode에서 remote extension pack 설치

    - WSL 환경에서 VSCode 다시 연 후 python 등 필요 익스텐션 설치

    - 터미널 bash에서 apt 업데이트, pip, requirements들 설치

    - Django, Celery 설치

    - Celery 명령어 bash에서 사용할 수 있도록 패키지도 설치: 
        $ sudo apt install python-celery-common

    - Django 서버 실행 
        $ python manage.py runserver
        $ python manage.py migrate 통해 먼저 db 마이그레이션 진행해야 할듯
        실행 시 logs 디렉토리 및 로그 파일이 없으면 에러가 나왔음

    - Window에 도커 설치 Redis 이미지 pull, docker run
        WSL 가상환경에 설치하지 말고 윈도우 도커에 설치할 것을 권고했음
        https://www.docker.com/products/docker-desktop

        Docker에 Redis Run (port: 6379)
        https://dingrr.com/blog/post/redis-%EB%8F%84%EC%BB%A4docker%EB%A1%9C-redis-%EC%84%A4%EC%B9%98%ED%95%98%EA%B8%B0

        $ docker run --name redis -d -p 6379:6379 --rm redis
        -d: 백그라운드에서 실행 / -p: 해당 포트로 접근가능하도록 열어두기 / --rm: 기존 컨테이너 존재시 삭제 후 재실행

    - Celery 작동 시작
        $ celery -A springbank worker -l INFO --beat
        이렇게 하면 celery beat 실행되며 celery_settings.py에 명시된 periodic task들이 celeryBeat에 등록됨
        CeleryBeat는 설정된 스케줄에 따라 Docker에 돌아가고 있는 Redis 서버에 메세지를 날리고, 이 메세지가 비동기적으로 Celery Worker에 전달되며 작업 수행. 실행 결과는 Result에 저장됨
