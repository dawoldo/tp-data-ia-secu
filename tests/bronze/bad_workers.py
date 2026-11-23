import os
import time


def crash():
    os._exit(11)


def hang():
    time.sleep(999)


def memory():
    return len(bytearray(8 * 1024**3))


def raises():
    raise RuntimeError("boom")


def chatty():
    print("noise")
    os.write(1, b"noise2\n")
    return "ok"
