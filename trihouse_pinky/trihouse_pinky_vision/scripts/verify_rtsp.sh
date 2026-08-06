#!/usr/bin/env bash
set -euo pipefail

uri="${1:-rtsp://192.168.0.9:8554/pinky_1}"
duration="${2:-600}"

if [[ "$uri" != rtsp://* ]]; then
  echo "URI must start with rtsp://" >&2
  exit 2
fi
if [[ ! "$duration" =~ ^[1-9][0-9]*$ ]] || (( duration > 3600 )); then
  echo "duration must be an integer from 1 to 3600 seconds" >&2
  exit 2
fi

ffprobe \
  -v error \
  -rtsp_transport tcp \
  -show_entries stream=codec_name,profile,width,height,avg_frame_rate \
  -of default=noprint_wrappers=1 \
  "$uri"

ffmpeg \
  -hide_banner \
  -xerror \
  -rtsp_transport tcp \
  -i "$uri" \
  -map 0:v:0 \
  -t "$duration" \
  -f null -
