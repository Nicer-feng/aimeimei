"""Official OpenAI egress only; no process-wide proxy or background probing."""
import base64
import hashlib
import http.client
import ipaddress
import json
import os
import socket
import ssl
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote, unquote, urlparse, urljoin

from .settings import DATA_DIR

CONFIG_PATH = DATA_DIR / "openai-egress.json"
CLIENT_PATH = DATA_DIR / "openai-egress-client.json"
RUNTIME_PATH = Path("/var/lib/ai-platform-egress/config.json")
CACHE_SECONDS = 90
_lock = threading.RLock()
_active = 0
_updating = False
_cache = {}
_checks = {}
_slots = threading.BoundedSemaphore(2)


class EgressError(urllib.error.URLError):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)


def read_config():
    try:
        data = json.loads(CONFIG_PATH.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def read_client():
    try:
        data = json.loads(CLIENT_PATH.read_text())
        for name in ("proxy_url", "controller_url"):
            parsed = urlparse(data[name])
            if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port:
                return {}
        proxy = urlparse(data["proxy_url"])
        if not proxy.username or not proxy.password or len(data.get("controller_secret", "")) < 32:
            return {}
        if data.get("runtime_path") != str(RUNTIME_PATH):
            return {}
        return data
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def is_openai_url(url):
    try:
        return urlparse(str(url or "")).hostname == "api.openai.com"
    except ValueError:
        return False


def validate_openai_url(url):
    try:
        p = urlparse(str(url or ""))
        valid = (p.scheme == "https" and p.hostname == "api.openai.com" and p.port in (None, 443)
                 and not p.username and not p.password and p.path.startswith("/v1/") and not p.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise EgressError("invalid_endpoint", "仅支持 https://api.openai.com/v1 官方接口")


def write_config(path, data, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as f:
        temp = Path(f.name)
        try:
            os.fchmod(f.fileno(), mode)
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
            os.replace(temp, path)
        finally:
            if temp.exists():
                temp.unlink()


def public_config():
    cfg, client = read_config(), read_client()
    return {"enabled": bool(cfg.get("enabled")), "installed": bool(client),
            "subscription_configured": bool(cfg.get("subscription_url")),
            "selected_node": str(cfg.get("selected_node") or ""),
            "updated_at": cfg.get("updated_at", 0), "cache_seconds": CACHE_SECONDS}


def controller(path, method="GET", body=None, timeout=10):
    client = read_client()
    if not client:
        raise EgressError("not_installed", "出站代理服务尚未安装")
    req = urllib.request.Request(client["controller_url"] + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "Bearer " + client["controller_secret"], "Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout) as r:
            data = r.read(512 * 1024 + 1)
            if len(data) > 512 * 1024:
                raise ValueError("large controller response")
            return json.loads(data) if data else {}
    except (OSError, ValueError):
        raise EgressError("proxy_service", "代理服务不可达或配置未被接受，请检查代理服务") from None


def nodes():
    data = controller("/proxies/OPENAI")
    return [str(n) for n in data.get("all", []) if isinstance(n, str) and n != "REJECT"][:500]


def validate_subscription(url):
    try:
        p = urlparse(url)
        if (p.scheme != "https" or not p.hostname or p.username or p.password or p.fragment
                or len(url) > 4096 or any(c.isspace() for c in url)):
            raise ValueError("invalid subscription")
        addresses = socket.getaddrinfo(p.hostname, p.port or 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError("nonpublic subscription")
    except (OSError, ValueError):
        raise EgressError("invalid_subscription", "订阅地址必须能解析到公网地址，不能使用本机或内网地址") from None
    return p, addresses


def download_subscription(url):
    deadline = time.monotonic() + 20
    for _ in range(4):
        parsed, addresses = validate_subscription(url)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        conn = http.client.HTTPSConnection(parsed.hostname, parsed.port or 443, timeout=min(8, remaining))
        try:
            # Pin the validated address while retaining TLS hostname verification.
            sock = socket.create_connection((addresses[0][4][0], parsed.port or 443), timeout=min(8, remaining))
            try:
                conn.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=parsed.hostname)
            except Exception:
                sock.close()
                raise
            conn.request("GET", (parsed.path or "/") + ("?" + parsed.query if parsed.query else ""),
                         headers={"User-Agent": "clash.meta", "Accept-Encoding": "identity"})
            response = conn.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                url = urljoin(url, response.getheader("Location", ""))
                continue
            if response.status != 200 or response.getheader("Content-Encoding", "identity") != "identity":
                break
            parts, size = [], 0
            while time.monotonic() < deadline:
                chunk = response.read1(min(65536, 2 * 1024 * 1024 + 1 - size))
                if not chunk:
                    break
                parts.append(chunk); size += len(chunk)
                if size > 2 * 1024 * 1024:
                    break
            else:
                raise TimeoutError("subscription budget exceeded")
            data = b"".join(parts)
            if not data or len(data) > 2 * 1024 * 1024:
                break
            return data
        except (OSError, ValueError, http.client.HTTPException):
            break
        finally:
            conn.close()
    raise EgressError("subscription_fetch", "订阅获取失败或超过 2MB，请检查 Clash/Mihomo 格式、链接和网络")


def write_bytes(path, data):
    path = Path(path)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        temp = Path(f.name)
        try:
            os.fchmod(f.fileno(), 0o640)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
            os.replace(temp, path)
        finally:
            if temp.exists():
                temp.unlink()


def runtime_config(cfg, client):
    p = urlparse(client["proxy_url"])
    config = {"port": p.port, "bind-address": "127.0.0.1", "allow-lan": False,
        "authentication": [p.username + ":" + p.password], "mode": "rule", "log-level": "silent",
        "external-controller": urlparse(client["controller_url"]).netloc,
        "secret": client["controller_secret"], "tun": {"enable": False}, "dns": {"enable": False},
        "sniffer": {"enable": False}, "find-process-mode": "off", "profile": {"store-selected": True},
        "proxy-groups": [{"name": "OPENAI", "type": "select", "proxies": ["REJECT"]}],
        "rules": ["DOMAIN,api.openai.com,OPENAI", "MATCH,REJECT"]}
    if cfg.get("subscription_url"):
        config["proxy-providers"] = {"subscription": {"type": "file",
            "path": "subscription.yaml", "interval": 0,
            "health-check": {"enable": False}}}
        config["proxy-groups"] = [{"name": "OPENAI", "type": "select", "use": ["subscription"]}]
    return config


def configure(incoming, reload_subscription=False):
    global _updating
    runtime_path, old_runtime, provider_path, old_provider = None, None, None, None
    current, node_applied = {}, False
    if not _lock.acquire(blocking=False):
        raise EgressError("busy", "代理配置正在更新，请稍后重试")
    try:
        current, client = read_config(), read_client()
        cfg = dict(current)
        if "enabled" in incoming:
            if not isinstance(incoming["enabled"], bool):
                raise ValueError("enabled must be boolean")
            cfg["enabled"] = incoming["enabled"]
        url = str(incoming.get("subscription_url") or "").strip()
        if url:
            validate_subscription(url)
            cfg["subscription_url"] = url
        node = str(incoming.get("selected_node", cfg.get("selected_node", "")) or "")
        changed_url = cfg.get("subscription_url") != current.get("subscription_url")
        if changed_url:
            cfg["enabled"] = False
        needs_reload = reload_subscription or changed_url
        if needs_reload and not cfg.get("subscription_url"):
            raise EgressError("not_configured", "请先填写订阅链接")
        if needs_reload or node != current.get("selected_node", ""):
            if _active:
                raise EgressError("busy", "有 OpenAI 请求正在进行，请结束后再更新订阅或切换节点")
            if not client:
                raise EgressError("not_installed", "出站代理服务尚未安装")
            _updating = True
            if needs_reload:
                runtime_path = Path(client["runtime_path"])
                old_runtime = runtime_path.read_bytes()
                provider_path = runtime_path.parent / "subscription.yaml"
                old_provider = provider_path.read_bytes() if provider_path.exists() else b""
                subscription = download_subscription(cfg["subscription_url"])
                write_bytes(provider_path, subscription)
                write_config(runtime_path, runtime_config(cfg, client), 0o640)
                controller("/configs?force=true", "PUT", {"path": str(runtime_path)}, timeout=20)
            available = nodes()
            if node and node not in available:
                node = ""
            if node:
                controller("/proxies/OPENAI", "PUT", {"name": node})
                node_applied = True
            cfg["selected_node"] = node
        if cfg.get("enabled") and not (client and cfg.get("subscription_url") and cfg.get("selected_node")):
            raise EgressError("not_configured", "请先更新订阅、选择节点，再开启 OpenAI 出站代理")
        cfg["updated_at"] = int(time.time())
        write_config(CONFIG_PATH, cfg)
        _cache.clear()
        return public_config()
    except Exception:
        if runtime_path is not None and old_runtime is not None:
            try:
                if provider_path is not None and old_provider is not None:
                    write_bytes(provider_path, old_provider)
                write_bytes(runtime_path, old_runtime)
                controller("/configs?force=true", "PUT", {"path": str(runtime_path)}, timeout=20)
            except Exception:
                pass
        if node_applied and current.get("selected_node"):
            try:
                controller("/proxies/OPENAI", "PUT", {"name": current["selected_node"]})
            except EgressError:
                pass
        raise
    finally:
        _updating = False
        _lock.release()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ScopedProxy(urllib.request.ProxyHandler):
    def proxy_open(self, req, proxy, kind):
        # Explicit routing must not be bypassed by ambient NO_PROXY settings.
        p = urlparse(proxy)
        credentials = (unquote(p.username) + ":" + unquote(p.password)).encode()
        req.add_header("Proxy-Authorization", "Basic " + base64.b64encode(credentials).decode("ascii"))
        req.set_proxy(p.hostname + ":" + str(p.port), "http")
        return None


class TrackedResponse:
    def __init__(self, response):
        self.response, self.closed = response, False

    def __getattr__(self, key):
        return getattr(self.response, key)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        global _active
        if self.closed:
            return
        self.closed = True
        try:
            self.response.close()
        finally:
            with _lock:
                _active -= 1


def open_model_request(request, timeout=120, allow_disabled=False):
    global _active
    if not is_openai_url(request.full_url):
        return urllib.request.urlopen(request, timeout=timeout)
    validate_openai_url(request.full_url)
    if not _lock.acquire(blocking=False):
        raise EgressError("busy", "代理配置正在更新，请稍后重试")
    try:
        cfg, client = read_config(), read_client()
        if not cfg.get("enabled") and not allow_disabled:
            raise EgressError("disabled", "OpenAI 专用出站代理未启用，请联系管理员")
        if not (client and cfg.get("subscription_url") and cfg.get("selected_node")):
            raise EgressError("not_configured", "OpenAI 出站代理尚未配置完成，请联系管理员")
        _active += 1
    finally:
        _lock.release()
    try:
        opener = urllib.request.build_opener(ScopedProxy({"https": client["proxy_url"]}), NoRedirect())
        return TrackedResponse(opener.open(request, timeout=timeout))
    except Exception:
        with _lock:
            _active -= 1
        raise


def result(status, code, message):
    ts = int(time.time())
    return {"status": status, "code": code, "message": message, "checked_at": ts, "expires_at": ts + CACHE_SECONDS}


def probe(model=None):
    model = dict(model) if model is not None else None
    key = str(model.get("api_key") or "").strip() if model is not None else ""
    if model is not None and not key:
        return result("unavailable", "missing_key", "请先配置该模型的 API Key")
    target = "https://api.openai.com/v1/models"
    if model is not None:
        target += "/" + quote(str(model["model"] or ""), safe="")
    req = urllib.request.Request(target, headers={"Authorization": "Bearer " + key} if key else {})
    try:
        with open_model_request(req, timeout=8, allow_disabled=True) as response:
            data = response.read(256 * 1024)
            if model is not None:
                body = json.loads(data)
                if not isinstance(body, dict) or body.get("id") != model["model"]:
                    return result("unavailable", "model_mismatch", "接口未返回对应模型信息")
            return result("reachable", "ok", "接口及模型权限检查通过，未执行生成；额度和生成能力以实际调用为准" if key else "代理 HTTPS 通道可达")
    except EgressError as exc:
        return result("unavailable", exc.code, exc.message)
    except urllib.error.HTTPError as exc:
        code = exc.code
        exc.close()
        if model is None and code == 401:
            return result("reachable", "ok", "代理 HTTPS 通道可达，已收到官方接口的未认证响应")
        messages = {401: "API Key 无效或未获授权", 403: "接口拒绝访问，请检查账号、地区或策略限制",
                    404: "模型不存在或当前 Key 无权访问", 429: "接口限流或额度受限，请检查账号"}
        return result("unavailable", "http_" + str(code), messages.get(code, "上游接口暂时不可用"))
    except (OSError, ValueError):
        return result("unavailable", "network", "代理或 API 连接失败/超时，请检查订阅、节点及网络")


def availability(model):
    cfg, client = read_config(), read_client()
    if not cfg.get("enabled"):
        return result("disabled", "disabled", "OpenAI 出站代理未启用")
    fingerprint = hashlib.sha256(json.dumps([dict(model), cfg, client], sort_keys=True, default=str).encode()).hexdigest()
    with _lock:
        cached = _cache.get(fingerprint)
        if cached and cached["expires_at"] > time.time():
            return dict(cached)
        check = _checks.setdefault(fingerprint, threading.Lock())
    if not check.acquire(timeout=9):
        return result("unknown", "busy", "检查正在进行，请稍后重试")
    try:
        with _lock:
            cached = _cache.get(fingerprint)
            if cached and cached["expires_at"] > time.time():
                return dict(cached)
        if not _slots.acquire(blocking=False):
            return result("unknown", "busy", "连接检查繁忙，请稍后重试")
        try:
            checked = probe(model)
        finally:
            _slots.release()
        with _lock:
            if read_config() != cfg or read_client() != client:
                return result("unknown", "config_changed", "代理配置已变化，请重新检查")
            if len(_cache) >= 128:
                _cache.clear()
            _cache[fingerprint] = checked
        return dict(checked)
    finally:
        check.release()
        with _lock:
            if len(_checks) > 128:
                for key in list(_checks):
                    if not _checks[key].locked():
                        _checks.pop(key, None)
