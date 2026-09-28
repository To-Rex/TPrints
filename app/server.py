"""HTTP API server — boshqa dasturlar shu API orqali chek yuboradi.

Barcha javoblar JSON. CORS ochiq — brauzerdagi veb-POS ilovalar ham
to'g'ridan-to'g'ri localhost'ga yuborishi mumkin.

Endpointlar:
  GET  /                 - dastur holati
  GET  /printers         - printerlar ro'yxati (profil bilan)
  GET  /status           - navbat statistikasi
  GET  /jobs             - so'nggi vazifalar
  GET  /jobs/<id>        - bitta vazifa holati
  POST /print            - chek chiqarish (elements JSON, quyida)
  POST /print/text       - oddiy matn chiqarish {"text": "...", "printer": "..."}
  POST /print/raw        - tayyor ESC/POS baytlar {"raw_base64": "..."}
  POST /print/image      - rasm chiqarish {"image_base64": "..."}
  POST /print/pdf        - PDF hujjat (A4) chiqarish {"pdf_base64": "..."}
  POST /preview/pdf      - PDF sahifasi PNG (chiqarmaydi)
  POST /preview          - chekni chiqarilmasdan PNG ko'rinishida qaytaradi
  POST /test             - sinov cheki {"printer": "..."} (ixtiyoriy)
"""
import base64
import io
import threading

from flask import Flask, jsonify, request, send_file

from . import APP_NAME, APP_VERSION
from .config import paper_dots

WAIT_TIMEOUT = 60  # "wait": true bo'lsa maksimal kutish (soniya)


def create_app(config, job_queue, manager, logger):
    app = Flask(APP_NAME)

    # ---------- CORS va autentifikatsiya ----------

    @app.after_request
    def add_cors(resp):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-Key"
        # Chrome PNA: https saytlar localhost'dagi print-serverga murojaat
        # qila olishi uchun (preflight'da so'raladi)
        resp.headers["Access-Control-Allow-Private-Network"] = "true"
        return resp

    @app.route("/", defaults={"_any": ""}, methods=["OPTIONS"])
    @app.route("/<path:_any>", methods=["OPTIONS"])
    def options(_any):
        return "", 204

    @app.before_request
    def check_auth():
        if request.method == "OPTIONS":
            return None
        key = (config.get("api_key") or "").strip()
        if key and request.headers.get("X-API-Key", "") != key:
            return jsonify({"ok": False, "error": "Noto'g'ri yoki yo'q X-API-Key"}), 401
        return None

    @app.errorhandler(Exception)
    def on_error(e):
        from werkzeug.exceptions import HTTPException
        if isinstance(e, HTTPException):
            return jsonify({"ok": False, "error": e.description}), e.code
        logger.error("API xatosi: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500

    # ---------- ma'lumot ----------

    @app.get("/")
    def index():
        return jsonify({"ok": True, "app": APP_NAME, "version": APP_VERSION,
                        "status": "ishlamoqda", **job_queue.stats()})

    @app.get("/printers")
    def printers():
        from .printing import win_printer
        items = win_printer.list_printers()
        for p in items:
            prof = config.profile(p["name"])
            p["profile"] = prof
            p["dots"] = paper_dots(prof)
        return jsonify({"ok": True, "printers": items,
                        "app_default": config.get("default_printer") or
                                       win_printer.default_printer(),
                        "always_open_drawer": bool(config.get("always_open_drawer")),
                        "drawer_printer": config.get("drawer_printer") or ""})

    @app.get("/status")
    def status():
        return jsonify({"ok": True, **job_queue.stats()})

    @app.get("/jobs")
    def jobs():
        limit = min(int(request.args.get("limit", 50)), 200)
        return jsonify({"ok": True, "jobs": job_queue.snapshot(limit)})

    @app.get("/jobs/<int:job_id>")
    def job_detail(job_id):
        job = job_queue.get_job(job_id)
        if not job:
            return jsonify({"ok": False, "error": "Vazifa topilmadi"}), 404
        return jsonify({"ok": True, "job": job.to_dict()})

    # ---------- chop etish ----------

    def _submit(payload):
        source = request.remote_addr or ""
        job = job_queue.submit(payload, source)
        if payload.get("wait"):
            job.done_event.wait(timeout=WAIT_TIMEOUT)
        d = job.to_dict()
        code = 200
        if d["status"] == "xato":
            code = 502
        return jsonify({"ok": d["status"] != "xato", "job_id": job.id,
                        "job": d}), code

    @app.post("/print")
    def print_receipt():
        payload = request.get_json(force=True, silent=True)
        if not isinstance(payload, dict):
            return jsonify({"ok": False, "error": "JSON body kerak"}), 400
        if not any(payload.get(k) for k in ("elements", "text", "image_base64",
                                            "raw_base64", "pdf_base64")):
            return jsonify({"ok": False,
                            "error": "elements/text/image_base64/raw_base64/pdf_base64 kerak"}), 400
        return _submit(payload)

    @app.post("/print/text")
    def print_text():
        payload = request.get_json(force=True, silent=True) or {}
        if request.content_type and "text/plain" in request.content_type:
            payload = {"text": request.get_data(as_text=True)}
        if not payload.get("text"):
            return jsonify({"ok": False, "error": "'text' maydoni kerak"}), 400
        return _submit(payload)

    @app.post("/print/raw")
    def print_raw():
        payload = request.get_json(force=True, silent=True) or {}
        if not payload.get("raw_base64"):
            return jsonify({"ok": False, "error": "'raw_base64' maydoni kerak"}), 400
        return _submit(payload)

    @app.post("/print/image")
    def print_image():
        payload = request.get_json(force=True, silent=True) or {}
        if not payload.get("image_base64"):
            return jsonify({"ok": False, "error": "'image_base64' maydoni kerak"}), 400
        return _submit(payload)

    @app.post("/print/pdf")
    def print_pdf():
        """PDF hujjat (natija, A4): {"pdf_base64": "...", "printer": "HP LaserJet", "copies": 1, "doc_name": "..."}"""
        payload = request.get_json(force=True, silent=True) or {}
        if not payload.get("pdf_base64"):
            return jsonify({"ok": False, "error": "'pdf_base64' maydoni kerak"}), 400
        return _submit(payload)

    @app.post("/preview/pdf")
    def preview_pdf():
        """PDF sahifasini PNG sifatida qaytaradi (chiqarmaydi): {"pdf_base64": "...", "page": 1, "dpi": 110}"""
        payload = request.get_json(force=True, silent=True) or {}
        if not payload.get("pdf_base64"):
            return jsonify({"ok": False, "error": "'pdf_base64' maydoni kerak"}), 400
        pages = manager.render_pdf_pages(base64.b64decode(payload["pdf_base64"]),
                                         int(payload.get("dpi") or 110))
        page = max(1, min(int(payload.get("page") or 1), len(pages)))
        buf = io.BytesIO()
        pages[page - 1].save(buf, format="PNG")
        buf.seek(0)
        resp = send_file(buf, mimetype="image/png")
        resp.headers["X-Pages"] = str(len(pages))
        return resp

    @app.post("/preview")
    def preview():
        payload = request.get_json(force=True, silent=True)
        if not isinstance(payload, dict):
            return jsonify({"ok": False, "error": "JSON body kerak"}), 400
        try:
            printer = manager.resolve_printer(payload.get("printer"))
        except Exception:
            printer = ""
        if printer:
            img, _ = manager.render_job(payload, printer)
        else:
            from .config import PROFILE_DEFAULTS
            dots = paper_dots({**PROFILE_DEFAULTS, **payload})
            img = manager.renderer.render(payload.get("elements") or
                                          [{"type": "text",
                                            "value": payload.get("text", "")}],
                                          dots, logger)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "PNG")
        buf.seek(0)
        return send_file(buf, mimetype="image/png")

    @app.post("/test")
    def test_print():
        payload = request.get_json(force=True, silent=True) or {}
        return _submit(manager.test_payload(payload.get("printer")))

    return app


class ServerThread:
    """Waitress serverni fonda ishga tushiradi."""

    def __init__(self, app, host, port, logger):
        self.host, self.port, self.logger = host, port, logger
        self.error = None
        self._thread = threading.Thread(target=self._serve, args=(app,),
                                        daemon=True, name="tprints-http")

    def start(self):
        # Port bandligini oldindan tekshirish (aniq xato xabari uchun)
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind((self.host, self.port))
        except OSError as e:
            self.error = (f"{self.host}:{self.port} band yoki ochib bo'lmadi: {e}. "
                          f"Balki TPrints allaqachon ishlayapti?")
            raise OSError(self.error)
        finally:
            s.close()
        self._thread.start()
        self.logger.info("HTTP server ishga tushdi: http://%s:%d", self.host, self.port)

    def _serve(self, app):
        from waitress import serve
        try:
            serve(app, host=self.host, port=self.port, threads=8,
                  ident=APP_NAME, clear_untrusted_proxy_headers=True)
        except Exception as e:
            self.error = str(e)
            self.logger.error("HTTP server to'xtadi: %s", e)
