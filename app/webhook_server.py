"""Part 4 student implementation."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import queue
from tempfile import TemporaryDirectory
import threading

from app.integration import process_request
from app.webex_client import WEBEX_API_BASE, WebexClient

logger = logging.getLogger(__name__)


class WebexEventHandler:
    def __init__(self, client, bot_person_id, processor=None):
        self.client = client
        self.bot_person_id = bot_person_id
        self.processor = processor or process_request

    def handle_event(self, event):
        if not isinstance(event, dict):
            return None
        if event.get("resource") != "messages" or event.get("event") != "created":
            return None

        data = event.get("data", {})
        sender_id = data.get("personId")
        if sender_id == self.bot_person_id:
            return None

        message_id = data.get("id")
        if not message_id:
            return None

        message = self.client.get_message(message_id)
        if message.get("personId") == self.bot_person_id:
            return None

        room_id = message.get("roomId")
        files = message.get("files") or []

        if len(files) > 1:
            result = {"status": "error", "result": "multiple_attachments"}
            self.client.send_message(room_id, json.dumps(result))
            return result

        if len(files) == 0:
            result = self.processor(
                message.get("mentionedPeople", []),
                None,
                self.bot_person_id,
            )
            self.client.send_message(room_id, json.dumps(result))
            return result

        file_url = files[0]
        content = self.client.download_file(file_url)

        with TemporaryDirectory() as tmp_dir:
            temp_path = Path(tmp_dir) / "request.yaml"
            temp_path.write_bytes(content)
            result = self.processor(
                message.get("mentionedPeople", []),
                temp_path,
                self.bot_person_id,
            )

        self.client.send_message(room_id, json.dumps(result))
        return result


def make_http_handler(submit_event):
    class WebhookHTTPHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            # Silence default stderr logging
            pass

        def _send_json(self, status_code, data):
            body = json.dumps(data).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                self._send_json(200, {"status": "ok", "result": "healthy"})
            else:
                self._send_json(404, {"status": "error", "result": "not_found"})

        def do_POST(self):
            if self.path == "/webhook":
                content_len = self.headers.get("Content-Length")
                if not content_len:
                    self._send_json(400, {"status": "error", "result": "invalid_event"})
                    return
                try:
                    length = int(content_len)
                except ValueError:
                    self._send_json(400, {"status": "error", "result": "invalid_event"})
                    return

                if length < 1 or length > 1_000_000:
                    self._send_json(400, {"status": "error", "result": "invalid_event"})
                    return

                body = self.rfile.read(length)
                try:
                    payload = json.loads(body.decode("utf-8"))
                    if not isinstance(payload, dict):
                        self._send_json(400, {"status": "error", "result": "invalid_event"})
                        return
                except Exception:
                    self._send_json(400, {"status": "error", "result": "invalid_event"})
                    return

                submit_event(payload)
                self._send_json(200, {"status": "ok", "result": "accepted"})
            else:
                self._send_json(404, {"status": "error", "result": "not_found"})

    return WebhookHTTPHandler


def main():
    host = os.environ.get("WEBHOOK_HOST", "0.0.0.0")
    port = int(os.environ.get("WEBHOOK_PORT", "8000"))

    client = WebexClient()
    bot_person_id = os.environ.get("BOT_PERSON_ID", "")
    if not bot_person_id and client.token:
        try:
            me = client.get_me()
            bot_person_id = me.get("id", "")
        except Exception as e:
            logger.warning(f"Could not fetch bot identity: {e}")

    handler = WebexEventHandler(client, bot_person_id)

    event_queue = queue.Queue()

    def worker():
        while True:
            ev = event_queue.get()
            try:
                handler.handle_event(ev)
            except Exception as e:
                logger.error(f"Error handling event: {e}")
            finally:
                event_queue.task_done()

    worker_thread = threading.Thread(target=worker, daemon=True)
    worker_thread.start()

    server = ThreadingHTTPServer((host, port), make_http_handler(event_queue.put))
    print(f"Webhook server running on {host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
