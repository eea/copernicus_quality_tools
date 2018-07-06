import logging
import threading
import time
from django.conf import settings

logger = logging.getLogger(__name__)


def check_processes():
    # runs the timer every 10 seconds
    time.sleep(10)
    counter = 0
    while True:
        time.sleep(10)
        counter += 1
        msg = "Running the timer: {:d} .....".format(counter)
        logger.info(msg)


def run():

    print ("STARTUP !!!!!")

    t = threading.Thread(target=check_processes)
    t.setDaemon(True)
    t.start()

