"""公网入口配置与登录频率限制。"""

from collections import Counter, deque
from dataclasses import dataclass
from ipaddress import ip_address
import re
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit


@dataclass(frozen=True)
class PublicSite:
    host: str
    prefix: str

    @property
    def origin(self):
        return "https://" + self.host

    @classmethod
    def parse(cls, url):
        target = urlsplit(url)
        if (target.scheme != "https" or target.hostname != target.netloc or
                not re.fullmatch(r"[a-z0-9.-]+\.[a-z0-9-]+", target.netloc) or
                not re.fullmatch(r"/(?:[A-Za-z0-9_-]+/)+", target.path) or
                target.query or target.fragment):
            raise ValueError("公网地址须为 HTTPS 域名和以斜杠结尾的路径。")
        return cls(target.netloc, target.path)


class LoginThrottle:
    window = 60
    per_client = 12
    total = 120

    def __init__(self):
        self._events = deque()
        self._client_counts = Counter()
        self._lock = Lock()

    def allow(self, address):
        address = ip_address(address)
        with self._lock:
            now = monotonic()
            while self._events and self._events[0][0] <= now - self.window:
                _, old_address = self._events.popleft()
                self._client_counts[old_address] -= 1
                if not self._client_counts[old_address]:
                    del self._client_counts[old_address]
            if len(self._events) >= self.total or self._client_counts[address] >= self.per_client:
                return False
            self._events.append((now, address))
            self._client_counts[address] += 1
            return True
