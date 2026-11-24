"""Static server for /data/site: byte ranges (iOS Safari won't play audio without them, seeking needs them),
cached media, revalidated pages. ponytail: stdlib server, fine for a personal recap; put a reverse proxy in front for TLS."""
import functools, http.server, io, os, re, sys


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # media/ files are named by song id and don't change; pages are rebuilt in place, so browsers revalidate
        self.send_header("Cache-Control", "max-age=604800" if "/media/" in self.path else "no-cache")
        self.send_header("Accept-Ranges", "bytes")
        super().end_headers()

    def send_head(self):
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", "").strip())
        path = self.translate_path(self.path)
        if not m or not any(m.groups()) or not os.path.isfile(path):
            return super().send_head()
        size, (a, b) = os.path.getsize(path), m.groups()
        start, end = (int(a), min(int(b or size - 1), size - 1)) if a else (max(0, size - int(b)), size - 1)
        if start > end:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return None
        f = open(path, "rb")
        f.seek(start)
        if end < size - 1:  # a bounded slice; open-ended ranges (what browsers send for audio) stream from the file
            body = f.read(end - start + 1)
            f.close()
            f = io.BytesIO(body)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        return f


class Server(http.server.ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        # browsers drop audio requests once they've buffered enough: normal, not worth a traceback in the logs
        if not isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            super().handle_error(request, client_address)


if __name__ == "__main__":
    root = os.environ.get("SITE", "/data/site")
    Server(("", int(os.environ.get("PORT", 8080))), functools.partial(Handler, directory=root)).serve_forever()
