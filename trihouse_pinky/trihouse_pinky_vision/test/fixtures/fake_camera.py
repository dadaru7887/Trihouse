#!/usr/bin/env python3
import signal
import sys
import time


running = True


def stop(_signum, _frame):
    global running
    running = False


signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)

payload = b'camera-data' * 128
while running:
    try:
        sys.stdout.buffer.write(payload)
        sys.stdout.buffer.flush()
    except BrokenPipeError:
        break
    time.sleep(0.02)
