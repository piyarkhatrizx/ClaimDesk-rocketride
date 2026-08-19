#!/usr/bin/env python3
"""
ClaimDesk local server + RocketRide proxy.
Serves the website on a fixed port (8000) and auto-detects RocketRide's
current webhook port, so you never hand-type a changing port.

Run:  python serve.py
Open: http://localhost:8000
"""
import http.client
import http.server
import socketserver
import urllib.request
import urllib.error
import urllib.parse
import json
import os
import socket
import io
import time
from PIL import Image


try:
    from pillow_heif import register_heif_opener
    register_heif_opener()   # lets Pillow open .heic/.heif files
except ImportError:
    pass

# ---- config ----
SERVE_PORT = 8000
SITE_FILE = "web/index.html"
SCAN_RANGE = range(50000, 65536)

def extract_json_object(text):
    """
    Find and parse the first valid claim JSON object embedded in text, even
    if the LLM wrapped it in markdown headers/prose (e.g. "### Report 1\n```json\n{...}").
    Scans every balanced {...} block and returns the first one that parses
    and looks like a claim (has a "summary" key), rather than only stripping
    a single leading ```json fence.
    Returns None if no valid claim object is found.
    """
    start = None
    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    candidate = text[start:i + 1]
                    try:
                        parsed = json.loads(candidate)
                        if isinstance(parsed, dict) and "summary" in parsed:
                            return parsed
                    except json.JSONDecodeError:
                        pass
                    start = None
    return None


def _read_file(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except FileNotFoundError:
        return default

# All connection info comes from ClaimDesk.py or environment
ENV_AUTH_KEY = os.environ.get("ROCKETRIDE_AUTH")
CHAT_AUTH_KEY = os.environ.get("ROCKETRIDE_CHAT_AUTH", "")
WEBHOOK_PORT = os.environ.get("WEBHOOK_PORT") or _read_file(".rocketride_port") or None

def get_auth_key():
    """
    Re-read .rocketride_auth on every call instead of caching it once.
    ClaimDesk.py rewrites this file with a new publicToken every time the
    pipeline (re)connects, so a cached value goes stale -- causing "Task
    token is required" once the old token no longer maps to a running task.
    """
    return ENV_AUTH_KEY or _read_file(".rocketride_auth")

# =============================================================================
# DETERMINISTIC RULES ENGINE
# Runs in microseconds — no LLM needed. Applies business rules to the AI output
# to triage claims and flag contradictions before an adjuster sees them.
# =============================================================================
def audit_claim_logic(claim_data: dict) -> dict:
    # Rule -1: The AI's response couldn't be parsed as valid JSON at all.
    # This is NOT the same thing as "no damage found" -- we genuinely don't
    # know what the AI concluded, so this must never be treated as confirmed
    # no-damage (which would wrongly mark a real damage claim ineligible).
    # Route it to manual review instead of guessing.
    if claim_data.get("_fallback"):
        return {
            "triage_level": "NEEDS MANUAL REVIEW",
            "flags": [
                "UNPARSEABLE AI RESPONSE: The AI's output could not be read "
                "as a valid claim report. A human must review the raw "
                "response before this claim can be triaged -- do not treat "
                "this as a 'no damage' determination."
            ],
            "processed_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }

    severity = str(claim_data.get("severity", "Low")).capitalize()
    damaged_parts = [str(p).lower() for p in claim_data.get("damaged_parts") or []]
    drivable = bool(claim_data.get("drivable", True))
    hazards = claim_data.get("safety_hazards", [])
    requires_mechanic = bool(claim_data.get("requires_mechanic_inspection", False))
    confidence = claim_data.get("confidence", {}) or {}

    flags = []
    triage_level = "STANDARD"

    # Rule 0: No confirmed damage -- do not let the AI approve or price a claim
    # it can't actually substantiate. This does NOT depend on the LLM
    # following instructions correctly: it triggers on the structural
    # signal (an empty damaged_parts list) as well as the model's own
    # requires_mechanic_inspection flag, so a claim can't slip through fast
    # track / high priority triage without any damage actually described.
    #
    # These are two distinct cases with two accurate messages -- a model can
    # set requires_mechanic_inspection even when it DID list damaged parts
    # (e.g. it's unsure of the full extent), which is different from finding
    # no damage at all.
    if not damaged_parts:
        return {
            "triage_level": "MECHANIC INSPECTION REQUIRED",
            "flags": [
                "INSUFFICIENT EVIDENCE: No damage could be confirmed from the "
                "photo/description. Claimant must obtain a licensed mechanic's "
                "inspection report before this claim can proceed."
            ],
            "processed_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
    if requires_mechanic:
        return {
            "triage_level": "MECHANIC INSPECTION REQUIRED",
            "flags": [
                "AI FLAGGED FOR INSPECTION: Damage was identified "
                f"({', '.join(damaged_parts)}), but the AI could not fully "
                "confirm the extent of damage from this evidence alone. A "
                "licensed mechanic's inspection report is required before "
                "this claim can proceed."
            ],
            "processed_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }

    # Rule 1: Structural / critical component check
    critical_parts = ["frame", "radiator", "engine", "airbag", "steering", "axle"]
    has_critical_damage = any(cp in part for cp in critical_parts for part in damaged_parts)

    if severity in ["Severe", "Totaled"] or has_critical_damage:
        triage_level = "HIGH PRIORITY"
        if has_critical_damage:
            flags.append("Critical functional components damaged (e.g. frame/airbag/engine).")

    # Rule 2: Safety & contradiction detection
    if drivable and (has_critical_damage or severity == "Totaled"):
        flags.append("SAFETY RISK: Vehicle marked drivable despite severe/structural damage.")
    if not drivable and severity == "Low" and not hazards:
        flags.append("DISCREPANCY: Claimed non-drivable, but severity is classified as Low.")

    # Rule 3: Fast-track low-severity claims
    if severity == "Low" and not has_critical_damage and drivable and len(damaged_parts) <= 2:
        triage_level = "FAST TRACK"

    # Rule 4: Low-confidence damage assessment -- damage was described, but
    # the model itself wasn't sure. Note this only catches cases where the
    # model reports its own uncertainty; it can't catch a confidently wrong
    # (fabricated) damage list, since there's no independent signal to check
    # it against here.
    damaged_parts_confidence = confidence.get("damaged_parts")
    if isinstance(damaged_parts_confidence, (int, float)) and damaged_parts_confidence < 50:
        flags.append(
            f"LOW CONFIDENCE ({damaged_parts_confidence}%): AI was not "
            "confident in the damaged parts it identified -- recommend "
            "manual review before relying on this assessment."
        )

    return {
        "triage_level": triage_level,
        "flags": flags,
        "processed_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }


# =============================================================================
# CROSS-CHECK ENGINE
# Compares the user's written accident description against the AI vision output.
# Catches contradictions like "rear-ended" when the AI sees front damage.
# =============================================================================
def crosscheck_description_vs_claim(user_description: str, claim_data: dict) -> dict:
    if not user_description or not user_description.strip():
        return None  # no description provided, nothing to cross-check

    desc_lower = user_description.lower()
    contradictions = []

    # Cross-check 1: Severity language vs AI classification
    severity = str(claim_data.get("severity", "")).lower()
    severe_words = ["totaled", "destroyed", "wrecked", "demolished", "smashed"]
    mild_words = ["scratch", "scuff", "nick", "ding", "minor"]
    desc_sounds_severe = any(w in desc_lower for w in severe_words)
    desc_sounds_mild = any(w in desc_lower for w in mild_words)

    if desc_sounds_severe and severity in ["low", "moderate"]:
        contradictions.append(
            f"Description uses severe language but AI classified severity as '{severity.title()}'."
        )
    if desc_sounds_mild and severity in ["severe", "totaled"]:
        contradictions.append(
            f"Description suggests minor damage but AI classified severity as '{severity.title()}'."
        )

    # Cross-check 2: Drivable claims vs AI assessment
    drivable = claim_data.get("drivable", True)
    desc_not_drivable = any(w in desc_lower for w in [
        "couldn't drive", "can't drive", "towed", "not drivable",
        "undrivable", "won't start", "wouldn't start", "had to be towed"
    ])
    desc_drivable = any(w in desc_lower for w in [
        "drove home", "drove away", "still drives", "drivable",
        "drove it", "able to drive"
    ])

    if desc_not_drivable and drivable:
        contradictions.append(
            "Description says vehicle couldn't be driven, but AI assessment says drivable."
        )
    if desc_drivable and not drivable:
        contradictions.append(
            "Description says vehicle was driven, but AI assessment says not drivable."
        )

    # Cross-check 3: Damage location mismatch (front vs rear)
    damaged_parts_lower = " ".join([str(p).lower() for p in claim_data.get("damaged_parts", [])])
    desc_mentions_rear = any(w in desc_lower for w in ["rear-ended", "rear ended", "hit from behind", "back of"])
    desc_mentions_front = any(w in desc_lower for w in ["head-on", "head on", "front of", "hit a pole", "ran into"])
    ai_shows_front = any(w in damaged_parts_lower for w in ["front", "hood", "headlight", "grille", "bumper"])
    ai_shows_rear = any(w in damaged_parts_lower for w in ["rear", "trunk", "taillight", "tail light", "back bumper"])

    if desc_mentions_rear and ai_shows_front and not ai_shows_rear:
        contradictions.append(
            "Description mentions rear-end collision, but AI only detected front-end damage."
        )
    if desc_mentions_front and ai_shows_rear and not ai_shows_front:
        contradictions.append(
            "Description mentions front collision, but AI only detected rear damage."
        )

    # Return result
    if contradictions:
        return {
            "match": False,
            "contradictions": contradictions,
            "details": f"Found {len(contradictions)} inconsistenc{'y' if len(contradictions)==1 else 'ies'} between the written description and the AI photo analysis."
        }
    else:
        return {
            "match": True,
            "contradictions": [],
            "details": "The written accident description is consistent with what the AI detected in the photos."
        }


# =============================================================================
# PORT SCANNER
# Auto-detects the RocketRide webhook port. Caches result to avoid flooding
# the pipeline with test requests on every status poll.
# =============================================================================
_cached_port = None
_cache_time = 0

def find_webhook_port():
    global _cached_port, _cache_time

    # Manual override via environment variable
    if WEBHOOK_PORT:
        return int(WEBHOOK_PORT)

    now = time.time()

    # Return cached port if recently verified
    if _cached_port and (now - _cache_time) < 30:
        return _cached_port

    # Verify cached port is still alive
    if _cached_port:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.1)

            if s.connect_ex(("127.0.0.1", _cached_port)) == 0:
                _cache_time = now
                return _cached_port

        _cached_port = None

    # Scan RocketRide's dynamic high ports
    for port in SCAN_RANGE:

        # Don't identify our own web server
        if port == SERVE_PORT:
            continue

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.02)

            if s.connect_ex(("127.0.0.1", port)) != 0:
                continue

        url = f"http://127.0.0.1:{port}/webhook"

        try:
            test_data = b'{"_ping":true}'

            req = urllib.request.Request(
                url,
                method="POST",
                data=test_data
            )

            req.add_header("Content-Type", "application/json")
            req.add_header(
                "Authorization",
                f"Bearer {get_auth_key()}"
            )

            with urllib.request.urlopen(req, timeout=1.0) as resp:
                body = resp.read(1000).decode(
                    "utf-8",
                    "ignore"
                ).lower()

                # Ignore normal websites
                if "<!doctype html" in body or "<html" in body:
                    continue

                _cached_port = port
                _cache_time = now

                print(
                    f"Found RocketRide webhook on port {port} "
                    f"(HTTP {resp.status})"
                )

                return port

        except urllib.error.HTTPError as e:
            # IMPORTANT:
            # A RocketRide webhook can return an HTTP error because
            # our ping isn't a real pipeline payload.
            body = e.read(1000).decode(
                "utf-8",
                "ignore"
            ).lower()

            # 404 strongly suggests this server simply doesn't have
            # a /webhook endpoint.
            if e.code == 404:
                continue

            # Ignore HTML error pages from unrelated web servers
            if "<!doctype html" in body or "<html" in body:
                continue

            # 400/401/403/405/422 etc. still prove that something
            # is responding specifically at /webhook.
            _cached_port = port
            _cache_time = now

            print(
                f"Found possible RocketRide webhook on port {port} "
                f"(HTTP {e.code})"
            )

            return port

        except (
            urllib.error.URLError,
            http.client.BadStatusLine,
            ConnectionResetError,
            TimeoutError,
            OSError,
        ):
            continue

    return None


# =============================================================================
# EXIF SCRUBBER
# Strips all metadata (GPS, device, timestamp) from images BEFORE they leave
# this machine. Reports what was found so the UI can display it.
# =============================================================================
def scrub_exif(image_bytes):
    removed = {}
    try:
        img = Image.open(io.BytesIO(image_bytes))

        # Extract EXIF data before stripping
        exif = img._getexif() if hasattr(img, "_getexif") and img._getexif() else None
        if exif:
            from PIL.ExifTags import TAGS, GPSTAGS
            tagged = {TAGS.get(k, k): v for k, v in exif.items()}

            # Device info
            make = tagged.get("Make")
            model = tagged.get("Model")
            if make or model:
                removed["device"] = f"{make or ''} {model or ''}".strip()

            # Timestamp
            dt = tagged.get("DateTimeOriginal") or tagged.get("DateTime")
            if dt:
                removed["timestamp"] = str(dt)

            # GPS coordinates
            gps = tagged.get("GPSInfo")
            if gps:
                g = {GPSTAGS.get(k, k): v for k, v in gps.items()}
                lat = g.get("GPSLatitude"); lat_ref = g.get("GPSLatitudeRef")
                lon = g.get("GPSLongitude"); lon_ref = g.get("GPSLongitudeRef")
                if lat and lon:
                    def to_deg(v):
                        d, m, s = [float(x) for x in v]
                        return d + m / 60 + s / 3600
                    latitude = to_deg(lat) * (-1 if lat_ref == "S" else 1)
                    longitude = to_deg(lon) * (-1 if lon_ref == "W" else 1)
                    removed["gps"] = f"{latitude:.5f}, {longitude:.5f}"

        # Re-save as clean JPEG — all EXIF is gone
        if img.mode != "RGB":
            img = img.convert("RGB")
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=90)
        return out.getvalue(), "image/jpeg", removed

    except Exception as e:
        print(f"Error scrubbing EXIF: {e}")
        return image_bytes, None, removed


# =============================================================================
# HTTP HANDLER
# Serves the frontend, proxies submissions to the RocketRide pipeline,
# and post-processes the AI output with audit + cross-check logic.
# =============================================================================
class Handler(http.server.SimpleHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def do_GET(self):
        # Serve the frontend
        if self.path in ("/", "/index.html"):
            try:
                with open(SITE_FILE, "rb") as f:
                    content = f.read()

                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self._cors()
                self.end_headers()
                self.wfile.write(content)

            except FileNotFoundError:
                self.send_error(404, f"{SITE_FILE} not found")

            return

        # Serve static files
        if self.path.startswith("/web/"):
            filepath = self.path.lstrip("/")

            if os.path.exists(filepath):
                ext = os.path.splitext(filepath)[1]
                content_types = {
                    ".css": "text/css",
                    ".js": "application/javascript",
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".svg": "image/svg+xml",
                }

                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    content_types.get(ext, "application/octet-stream")
                )
                self._cors()
                self.end_headers()

                with open(filepath, "rb") as f:
                    self.wfile.write(f.read())

                return

            self.send_error(404)
            return

        # Pipeline health check
        if self.path == "/pipeline-status":
            port = find_webhook_port()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._cors()
            self.end_headers()

            self.wfile.write(
                json.dumps({"port": port}).encode()
            )
            return

        self.send_error(404)

    def do_POST(self):
        if self.path == "/chat":
            # Call Ollama directly for adjuster chat with full conversation history
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))

            # Accept either full history or single message
            if "messages" in body:
                messages = [{"role": "system", "content": "You are an AI assistant for insurance adjusters. Help understand claims, explain triage decisions, assess fraud risk, and recommend next steps. Be professional and concise. Only reference details from the claim report provided."}] + body["messages"]
            else:
                messages = [
                    {"role": "system", "content": "You are an AI assistant for insurance adjusters."},
                    {"role": "user", "content": body.get("message", "")}
                ]

            try:
                ollama_req = urllib.request.Request(
                    "http://localhost:11434/api/chat",
                    data=json.dumps({
                        "model": "llama3.1:8b",
                        "messages": messages,
                        "stream": False
                    }).encode(),
                    method="POST"
                )
                ollama_req.add_header("Content-Type", "application/json")

                with urllib.request.urlopen(ollama_req, timeout=120) as resp:
                    data = json.loads(resp.read())
                    reply = data.get("message", {}).get("content", "No response")

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self._cors(); self.end_headers()
                self.wfile.write(json.dumps({"reply": reply}).encode())

            except Exception as e:
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self._cors(); self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
            return

        if self.path != "/submit":
            self.send_error(404); return

        # Find the pipeline
        port = find_webhook_port()
        if not port:
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self._cors(); self.end_headers()
            self.wfile.write(json.dumps({
                "error": "No running RocketRide webhook found. Press play on the Webhook node."
            }).encode())
            return

        # Read the incoming request
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        content_type = self.headers.get("Content-Type", "application/octet-stream")

        # Grab metadata from custom headers (set by frontend)
        user_description = urllib.parse.unquote(self.headers.get("X-Claim-Description", ""))
        claim_id = self.headers.get("X-Claim-Id", "")

        # ---- PRIVACY: Scrub EXIF from images before sending to pipeline ----
        removed_info = {}
        if content_type.startswith("image/"):
            body, new_type, removed_info = scrub_exif(body)
            if new_type:
                content_type = new_type
                if removed_info:
                    print(f"  [{claim_id}] scrubbed EXIF: {removed_info}")
                else:
                    print(f"  [{claim_id}] scrubbed image (no EXIF found)")

            # Wrap image in multipart form for the webhook
            boundary = "----ClaimDeskBoundary987654321"
            multipart_header = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="claim_photo.jpg"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode('utf-8')
            multipart_footer = f"\r\n--{boundary}--\r\n".encode('utf-8')
            body = multipart_header + body + multipart_footer
            content_type = f"multipart/form-data; boundary={boundary}"

        # ---- FORWARD TO ROCKETRIDE PIPELINE ----
        req = urllib.request.Request(
            f"http://localhost:{port}/webhook", data=body, method="POST")
        req.add_header("Content-Type", content_type)
        req.add_header("Authorization", f"Bearer {get_auth_key()}")

        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                raw_response_bytes = resp.read()
                raw_response_text = raw_response_bytes.decode('utf-8', 'ignore')

                # ---- UNWRAP ROCKETRIDE RESPONSE ----
                # The pipeline wraps answers in a nested JSON structure.
                # We extract the actual LLM output from inside it.
                extracted_text = raw_response_text
                try:
                    outer_json = json.loads(raw_response_text)

                    # Check for pipeline-level errors (e.g. memory node failure)
                    file_obj = outer_json.get("data", {}).get("objects", {}).get("file", {})
                    body_obj = outer_json.get("data", {}).get("objects", {}).get("body", {})
                    for obj in [file_obj, body_obj]:
                        if isinstance(obj, dict) and obj.get("error"):
                            err_msg = obj["error"].get("message", "Unknown pipeline error")
                            raise ValueError(f"Pipeline error: {err_msg}")

                    # Extract the LLM's answer from the response wrapper
                    answers = (
                        file_obj.get("answers") or
                        body_obj.get("answers")
                    )
                    if isinstance(answers, list) and len(answers) > 0:
                        extracted_text = answers[0]
                    elif isinstance(outer_json.get("claim"), dict):
                        extracted_text = json.dumps(outer_json.get("claim"))

                except ValueError as ve:
                    # Pipeline error — return it cleanly to the frontend
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self._cors(); self.end_headers()
                    self.wfile.write(json.dumps({
                        "success": False,
                        "raw_text": str(ve),
                        "_privacy": {"removed": removed_info},
                        "error": str(ve)
                    }).encode())
                    return
                except Exception:
                    pass

                # ---- PARSE LLM OUTPUT ----
                # Try strict JSON first. If the LLM returned markdown-wrapped
                # JSON (```json ... ```), strip the fences. If it returned
                # chatty text, fall back to keyword extraction.
                try:
                    clean_text = extracted_text.strip()
                    if clean_text.startswith("```json"):
                        clean_text = clean_text[7:]
                    if clean_text.startswith("```"):
                        clean_text = clean_text[3:]
                    if clean_text.endswith("```"):
                        clean_text = clean_text[:-3]
                    clean_text = clean_text.strip()

                    try:
                        # Strict JSON parse — ideal path
                        claim_json = json.loads(clean_text)
                    except json.JSONDecodeError:
                        # The model sometimes wraps the real JSON in markdown
                        # headers/prose (e.g. "### Report 1\n```json\n{...}").
                        # Recover the embedded object before giving up.
                        recovered = extract_json_object(clean_text)
                        if recovered is not None:
                            claim_json = recovered
                        else:
                            # Truly unparseable. This is NOT the same thing as
                            # "no damage found" -- we genuinely don't know what
                            # the AI concluded, so don't claim damaged_parts is
                            # empty (that would incorrectly trigger the "no
                            # damage" mechanic-inspection rule below and could
                            # mark a real damage claim ineligible). Flag it as
                            # unparsed instead and let a human read the raw text.
                            claim_json = {
                                "summary": clean_text[:300] + ("..." if len(clean_text) > 300 else ""),
                                "severity": "Unknown",
                                "damaged_parts": [],
                                "estimated_cost_range": "Pending Adjuster Review",
                                "safety_hazards": ["AI response could not be parsed -- needs manual review"],
                                "drivable": True,
                                "_fallback": True
                            }

                    # ---- POST-PROCESSING ----
                    # Run deterministic audit rules on the AI output
                    audit_results = audit_claim_logic(claim_json)

                    # Cross-check user's description against AI analysis
                    crosscheck_result = crosscheck_description_vs_claim(
                        user_description, claim_json
                    )

                    # Bundle everything for the frontend
                    final_payload = {
                        "success": True,
                        "claim": claim_json,
                        "_audit": audit_results,
                        "_privacy": {"removed": removed_info},
                        "_crosscheck": crosscheck_result,
                        "_claim_id": claim_id
                    }

                except Exception as e:
                    final_payload = {
                        "success": False,
                        "raw_text": raw_response_text,
                        "_privacy": {"removed": removed_info},
                        "error": str(e)
                    }

                # Send processed result back to frontend
                result_bytes = json.dumps(final_payload).encode('utf-8')
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self._cors(); self.end_headers()
                self.wfile.write(result_bytes)

        except urllib.error.HTTPError as e:
            self.send_response(e.code); self._cors(); self.end_headers()
            self.wfile.write(e.read())
        except Exception as e:
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self._cors(); self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())


# =============================================================================
# SERVER SETUP
# Threading + port reuse so restarts don't fail on "address already in use"
# =============================================================================
class ReusableServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    current_port = SERVE_PORT

    while True:
        try:
            httpd = ReusableServer(("", current_port), Handler)
            break
        except OSError as e:
            if e.errno == 48:  # address already in use
                print(f"Port {current_port} is busy, trying {current_port + 1}...")
                current_port += 1
            else:
                raise

    print(f"ClaimDesk:  http://localhost:{current_port}")
    print(f"Auth key: {get_auth_key()[:12]}...")
    print("Keep the pipeline running. Ctrl+C to stop.\n")

    with httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")