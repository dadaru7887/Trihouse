#!/usr/bin/env python3
import argparse
import signal
import sys
import time


parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('--exit-after', type=int, default=0)
args, _unknown = parser.parse_known_args()
running = True


def stop(_signum, _frame):
    global running
    running = False


signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)

frame = 0
while running:
    data = sys.stdin.buffer.read(1024)
    if not data:
        break
    frame += 1
    sys.stderr.write(f'frame={frame}\n')
    sys.stderr.write('fps=15.0\n')
    sys.stderr.write(f'out_time_us={frame * 66667}\n')
    sys.stderr.write('progress=continue\n')
    sys.stderr.flush()
    if args.exit_after and frame >= args.exit_after:
        sys.exit(7)
    time.sleep(0.01)
