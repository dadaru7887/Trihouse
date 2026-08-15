#!/usr/bin/env python3
"""Small server-side OpenAI gateway for the RoboSapiens hybrid map planner."""

import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


OPENAI_URL = "https://api.openai.com/v1/responses"
MODEL = os.environ.get("ROBOSAPIENS_CODEX_MODEL", "gpt-5.6-terra")
PORT = int(os.environ.get("ROBOSAPIENS_CODEX_PORT", "8787"))

WAYPOINT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "x", "y", "name", "category"],
    "properties": {
        "id": {"type": "string"},
        "x": {"type": "number"},
        "y": {"type": "number"},
        "name": {"type": "string"},
        "category": {
            "type": "string",
            "enum": ["일반", "대기", "홈", "충전", "픽업", "드랍오프"],
        },
    },
}
LANE = {
    "type": "object",
    "additionalProperties": False,
    "required": ["startId", "endId", "direction"],
    "properties": {
        "startId": {"type": "string"},
        "endId": {"type": "string"},
        "direction": {
            "type": "string",
            "enum": ["양방향", "정방향", "역방향"],
        },
    },
}
OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["provider", "summary", "waypoints", "lanes", "warnings"],
    "properties": {
        "provider": {"type": "string"},
        "summary": {"type": "string"},
        "waypoints": {"type": "array", "items": WAYPOINT},
        "lanes": {"type": "array", "items": LANE},
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
}


def _extract_output_text(response):
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                return content.get("text", "")
    raise ValueError("Responses API output_text is missing")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/v1/map/analyze":
            self.send_error(404)
            return
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            self.send_error(503, "OPENAI_API_KEY is not configured")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            source = json.loads(self.rfile.read(length))
            prompt = (
                "Design an editable Open-RMF navigation graph from the supplied JSON. "
                "Preserve every existing operational waypoint and its id. Add ids prefixed "
                "with ai_. Do not move existing points. Place every added waypoint strictly "
                "inside floorPolygon and never cross a wall. Keep robot clearance and turning "
                "radius. Obey scenario.routeMode: create two physically distinct one-way paths "
                "only for separate_outbound_return; for shared_narrow_lane_with_holding create "
                "one shared lane and holding points at both narrow-passage entrances. Place new "
                "Home points near dropoff points. Use category 충전 for every requested charger. Create at least "
                "holdingCount waypoints with category 대기 in addition to homeCount waypoints "
                "with category 홈. Return only the schema.\n\n"
                + json.dumps(source, ensure_ascii=False)
            )
            body = json.dumps({
                "model": MODEL,
                "reasoning": {"effort": "medium"},
                "input": prompt,
                "store": False,
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "rmf_map_proposal",
                        "strict": True,
                        "schema": OUTPUT_SCHEMA,
                    }
                },
            }).encode()
            upstream = urllib.request.Request(
                OPENAI_URL,
                data=body,
                headers={
                    "Authorization": "Bearer " + api_key,
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(upstream, timeout=90) as response:
                result = json.load(response)
            proposal = json.loads(_extract_output_text(result))
            encoded = json.dumps(proposal, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            self.send_error(400, str(error))
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")[:1000]
            self.send_error(502, f"OpenAI API {error.code}: {detail}")
        except Exception as error:  # Keep the Flutter client on its local fallback.
            self.send_error(502, str(error))

    def log_message(self, fmt, *args):
        print("codex-map-gateway:", fmt % args)


if __name__ == "__main__":
    print(f"Codex map gateway listening on http://127.0.0.1:{PORT}/v1/map/analyze")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
