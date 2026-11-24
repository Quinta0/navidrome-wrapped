"""Static server for /data/site: byte ranges (iOS Safari won't play audio without them, seeking needs them),
cached media, revalidated pages. ponytail: stdlib server, fine for a personal recap; put a reverse proxy in front for TLS."""
import functools, http.server, io, os, re


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
        with open(path, "rb") as f:
            f.seek(start)
            body = f.read(end - start + 1)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        return io.BytesIO(body)


if __name__ == "__main__":
    root = os.environ.get("SITE", "/data/site")
    http.server.ThreadingHTTPServer(("", int(os.environ.get("PORT", 8080))),
                                    functools.partial(Handler, directory=root)).serve_forever()
