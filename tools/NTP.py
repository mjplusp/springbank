from os import error
from socket import gaierror, socket
import time
import sys
from datetime import datetime, timezone
import ntplib
import logging

logger = logging.getLogger("django")


def adjustTime(domain="time.google.com", time_threshold=0.1, verbose=False):
    if verbose:
        logger.info("[서버 시간 체크] ===========================")
    difference = getNTPtime(
        domain=domain, time_threshold=time_threshold, verbose=verbose
    )

    if difference.get("needServertimeSync"):
        logger.info("[서버 시간 동기화] =========================")
        if sys.platform == "linux":
            _linux_set_time(difference.get("ntpTime"))
        elif sys.platform == "win32":
            _win_set_time(difference.get("ntpTime"))
        adjustTime(domain=domain, time_threshold=time_threshold, verbose=True)


def getNTPtime(
    domain="time.google.com", time_threshold=0.1, verbose=False, retry=False
):

    client = ntplib.NTPClient()
    response = None

    try:
        response = client.request(domain, version=3)
    except (ntplib.NTPException, Exception) as e:
        # logger.info('서버 시간 동기화를 위한 %s NTP Server가 1 번 연속 응답 없음'  %domain)
        if retry:
            logger.info("서버 시간 동기화를 위한 %s NTP Server가 2 번 연속 응답 없음" % domain)
            logger.info("Original Error Message: %s" % str(e))
        time.sleep(1)
        getNTPtime(
            domain=domain, time_threshold=time_threshold, verbose=verbose, retry=True
        )

    if response:
        datetimeobj = datetime.fromtimestamp(response.tx_time, timezone.utc)
        if verbose:
            logger.info("로컬 서버 시간: %s" % str(datetime.now(timezone.utc)))  # utc 시간
            logger.info("NTP 서버 시간: %s" % str(datetimeobj))
            logger.info("서버 시간 차이: %s 밀리초" % str(response.offset // 0.001))
            # logger.info("============================================")
        return {
            "needServertimeSync": True
            if abs(response.offset) > time_threshold
            else False,
            "ntpTime": datetimeobj,
        }
    else:
        return {"needServertimeSync": False}


def _win_set_time(datetimeobj):
    # http://timgolden.me.uk/pywin32-docs/win32api__SetSystemTime_meth.html
    # pywin32.SetSystemTime(year, month , dayOfWeek , day , hour , minute , second , millseconds )
    import win32api

    win32api.SetSystemTime(
        datetimeobj.year,
        datetimeobj.month,
        datetimeobj.isocalendar()[2],
        datetimeobj.day,
        datetimeobj.hour,
        datetimeobj.minute,
        datetimeobj.second,
        datetimeobj.microsecond // 1000,
    )
    getNTPtime(domain="time.google.com", time_threshold=0.1)


def _linux_set_time(datetimeobj):

    import subprocess, shlex

    subprocess.call(shlex.split("sudo ntpdate pool.ntp.org"))
