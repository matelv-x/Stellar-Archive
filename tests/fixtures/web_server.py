import json
from http.server import SimpleHTTPRequestHandler


class StargateWebServer(SimpleHTTPRequestHandler):
    def parse_get_vars(self):
        return self.path, {}

    def do_GET(self):
        try:
            request_path, get_vars = self.parse_get_vars()
            if request_path == "/dial":
                self.send_response(302)
                self.end_headers()
        except Exception:
            self.send_error(500)

    def do_POST(self):
        try:
            content_len = int(self.headers.get('content-length', 0))
            body = self.rfile.read(content_len)
            try:
                data = json.loads(body)
            except Exception:
                data = {}
            if self.path == '/do/shutdown':
                self.send_response(200)
                self.end_headers()
        except Exception:
            self.send_error(500)

    def send_json_response(self, data):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
