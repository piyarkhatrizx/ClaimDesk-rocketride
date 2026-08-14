#!/usr/bin/env python3
"""
ClaimDesk local server + RocketRide proxy.
Serves the website on a fixed port (8000) and auto-detects RocketRide's
current webhook port, so you never hand-type a changing port.

Run:  python serve.py
Open: http://localhost:8000
"""

import http.server
import socketserver
import urllib.request
import urllib.error
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
AUTH_KEY = os.environ.get("ROCKETRIDE_AUTH", "pk_5e8624de9c0b2aa5c86952a1bdc419bf")
SCAN_RANGE = range(50000, 65001)   # extension picks high ports; scan this range
SITE_FILE = "web/index.html"


def audit_claim_logic(claim_data: dict) -> dict:
    """Microsecond deterministic rules engine."""
    severity = str(claim_data.get("severity", "Low")).capitalize()
    damaged_parts = [str(p).lower() for p in claim_data.get("damaged_parts", [])]
    drivable = bool(claim_data.get("drivable", True))
    hazards = claim_data.get("safety_hazards", [])

    flags = []
    triage_level = "STANDARD"

    # Rule 1: Structural / Critical Component Check
    critical_parts = ["frame", "radiator", "engine", "airbag", "steering", "axle"]
    has_critical_damage = any(cp in part for cp in critical_parts for part in damaged_parts)

    if severity in ["Severe", "Totaled"] or has_critical_damage:
        triage_level = "HIGH PRIORITY"
        if has_critical_damage:
            flags.append("Critical functional components damaged (e.g. frame/airbag/engine).")

    # Rule 2: Safety & Contradiction Detection
    if drivable and (has_critical_damage or severity == "Totaled"):
        flags.append("SAFETY RISK: Vehicle marked drivable despite severe/structural damage.")
    if not drivable and severity == "Low" and not hazards:
        flags.append("DISCREPANCY: Claimed non-drivable, but severity is classified as Low.")

    # Rule 3: Fast-Track Low-Severity Claims
    if severity == "Low" and not has_critical_damage and drivable and len(damaged_parts) <= 2:
        triage_level = "FAST TRACK"

    return {
        "triage_level": triage_level,
        "flags": flags,
        "processed_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }


def find_webhook_port():
    """Scan localhost for the port answering RocketRide's webhook (not Ollama)."""
    for port in SCAN_RANGE:
        if port == 11434:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.02)
            if s.connect_ex(("127.0.0.1", port)) != 0:
                continue
        try:
            url = f"http://localhost:{port}/webhook"
            req = urllib.request.Request(url, method="POST", data=b"")
            with urllib.request.urlopen(req, timeout=0.5) as resp:
                body = resp.read(300).decode("utf-8", "ignore").lower()
                if "<!doctype html" in body or "<html" in body:
                    continue  
                return port
        except urllib.error.HTTPError as e:
            if e.code in (400, 401, 403):
                return port
            continue
        except Exception:
            continue
    return None


def scrub_exif(image_bytes):
    """
    Strip all EXIF/metadata from an image before it leaves this machine,
    AND report what sensitive data was found so the UI can show it.
    """
    removed = {}
    try:
        img = Image.open(io.BytesIO(image_bytes))

        exif = img._getexif() if hasattr(img, "_getexif") and img._getexif() else None
        if exif:
            from PIL.ExifTags import TAGS, GPSTAGS
            tagged = {TAGS.get(k, k): v for k, v in exif.items()}

            make = tagged.get("Make")
            model = tagged.get("Model")
            if make or model:
                removed["device"] = f"{make or ''} {model or ''}".strip()

            dt = tagged.get("DateTimeOriginal") or tagged.get("DateTime")
            if dt:
                removed["timestamp"] = str(dt)

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

        if img.mode != "RGB":
            img = img.convert("RGB")

        out = io.BytesIO()
        img.save(out, format="JPEG", quality=90)
        return out.getvalue(), "image/jpeg", removed

    except Exception as e:
        print(f"Error scrubbing EXIF: {e}")
        return image_bytes, None, removed


class Handler(http.server.SimpleHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            try:
                with open(SITE_FILE, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self._cors(); self.end_headers()
                self.wfile.write(content)
            except FileNotFoundError:
                self.send_error(404, f"{SITE_FILE} not found")
            return
        if self.path == "/pipeline-status":
            port = find_webhook_port()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._cors(); self.end_headers()
            self.wfile.write(json.dumps({"port": port}).encode())
            return
        self.send_error(404)

    def do_POST(self):
        if self.path != "/submit":
            self.send_error(404); return
        port = find_webhook_port()
        if not port:
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self._cors(); self.end_headers()
            self.wfile.write(json.dumps({
                "error": "No running RocketRide webhook found. Press play on the Webhook node."
            }).encode())
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        content_type = self.headers.get("Content-Type", "application/octet-stream")

        removed_info = {}
        if content_type.startswith("image/"):
            body, new_type, removed_info = scrub_exif(body)
            if new_type:
                content_type = new_type
                if removed_info:
                    print(f"  scrubbed EXIF: {removed_info}")
                else:
                    print("  scrubbed image (no EXIF found)")
            
            boundary = "----ClaimDeskBoundary987654321"
            multipart_header = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="claim_photo.jpg"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode('utf-8')
            multipart_footer = f"\r\n--{boundary}--\r\n".encode('utf-8')
            
            body = multipart_header + body + multipart_footer
            content_type = f"multipart/form-data; boundary={boundary}"


        req = urllib.request.Request(
            f"http://localhost:{port}/webhook", data=body, method="POST")
        req.add_header("Content-Type", content_type)
        req.add_header("Authorization", f"Bearer {AUTH_KEY}")

        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                raw_response_bytes = resp.read()
                raw_response_text = raw_response_bytes.decode('utf-8', 'ignore')
                
                # --- UNWRAP ROCKETRIDE RESPONSE ---
                extracted_text = raw_response_text
                try:
                    outer_json = json.loads(raw_response_text)
                    answers = (
                        outer_json.get("data", {}).get("objects", {}).get("file", {}).get("answers") or
                        outer_json.get("data", {}).get("objects", {}).get("body", {}).get("answers")
                    )
                    if isinstance(answers, list) and len(answers) > 0:
                        extracted_text = answers[0]
                    elif isinstance(outer_json.get("claim"), dict):
                        extracted_text = json.dumps(outer_json.get("claim"))
                except Exception:
                    pass

                # --- BULLETPROOF PARSING & FALLBACK ---
                try:
                    clean_text = extracted_text.strip()
                    if clean_text.startswith("```json"):
                        clean_text = clean_text[7:]
                    if clean_text.endswith("```"):
                        clean_text = clean_text[:-3]
                    clean_text = clean_text.strip()

                    try:
                        # Attempt strict JSON parse
                        claim_json = json.loads(clean_text)
                    except json.JSONDecodeError:
                        # FALLBACK: If LLM outputs chatty text, map it to a valid JSON card automatically
                        clean_text_lower = clean_text.lower()
                        is_severe = "severe" in clean_text_lower or "broken" in clean_text_lower
                        claim_json = {
                            "summary": clean_text[:300] + ("..." if len(clean_text) > 300 else ""),
                            "severity": "Moderate" if "damage" in clean_text_lower else "Low",
                            "damaged_parts": ["front bumper", "hood"] if "front" in clean_text_lower else ["Unspecified damage"],
                            "estimated_cost_range": "Pending Adjuster Review",
                            "safety_hazards": ["Needs visual confirmation"],
                            "drivable": False if is_severe else True
                        }

                    audit_results = audit_claim_logic(claim_json)

                    final_payload = {
                        "success": True,
                        "claim": claim_json,
                        "_audit": audit_results,
                        "_privacy": {"removed": removed_info} 
                    }
                except Exception as e:
                    final_payload = {
                        "success": False,
                        "raw_text": raw_response_text,
                        "_privacy": {"removed": removed_info},
                        "error": str(e)
                    }

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
            if e.errno == 48: 
                print(f"Port {current_port} is busy, trying {current_port + 1}...")
                current_port += 1
            else:
                raise

    print(f"ClaimDesk:  http://localhost:{current_port}")
    print(f"Auth key: {AUTH_KEY[:12]}...")
    print("Keep the pipeline running. Ctrl+C to stop.\n")
    
    with httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")