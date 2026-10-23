import io
import json
from unittest import mock


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def patch_urlopen(reply):
    """Patch urllib.request.urlopen; returns (patcher, calls) where calls collects (request_or_url, kwargs)."""
    calls = []

    def fake(url, data=None, **kwargs):
        calls.append((url, data, kwargs))
        return FakeResponse(json.dumps(reply).encode())

    return mock.patch("urllib.request.urlopen", fake), calls
