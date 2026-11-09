"""Configured service URLs are credential boundaries, never redirect hints."""
import urllib.request


class RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_opener = urllib.request.build_opener(RejectRedirects())
open_request = _opener.open
