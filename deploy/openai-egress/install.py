#!/usr/bin/env python3
"""Install a verified, loopback-only egress core. Never installs global routing."""
import argparse
import gzip
import grp
import hashlib
import os
from pathlib import Path
import pwd
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ai_platform.openai_egress import runtime_config, write_config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("root required")
    data_dir = Path(os.environ.get("AI_PLATFORM_DATA", "/opt/ai-platform"))
    client_path = data_dir / "openai-egress-client.json"
    if client_path.exists():
        raise SystemExit("Already installed; preserve credentials. Upgrade manually after backup.")
    archive = args.archive.read_bytes()
    if hashlib.sha256(archive).hexdigest() != args.sha256.removeprefix("sha256:"):
        raise SystemExit("Official archive checksum mismatch")
    with tempfile.TemporaryDirectory(prefix="meimei-egress-") as temp:
        binary = Path(temp) / "mihomo"
        binary.write_bytes(gzip.decompress(archive))
        binary.chmod(0o755)
        version = subprocess.check_output([str(binary), "-v"], text=True)
        if args.version not in version:
            raise SystemExit("Core version mismatch")
        sockets = []
        try:
            for port in (17891, 17892):
                sock = socket.socket(); sockets.append(sock)
                sock.bind(("127.0.0.1", port))
        finally:
            for sock in sockets:
                sock.close()
        user = "ai-platform-egress"
        try:
            pwd.getpwnam(user)
        except KeyError:
            subprocess.run(["useradd", "--system", "--home-dir", "/var/lib/ai-platform-egress",
                            "--shell", "/usr/sbin/nologin", user], check=True)
        app_user = pwd.getpwnam("ai-platform")
        group_id = grp.getgrnam(user).gr_gid
        state = Path("/var/lib/ai-platform-egress")
        if state.is_symlink():
            raise SystemExit("State directory must not be a symlink")
        state.mkdir(mode=0o2770, exist_ok=True)
        os.chown(state, app_user.pw_uid, group_id); state.chmod(0o2770)
        target = Path("/usr/local/lib/ai-platform-egress")
        target.mkdir(mode=0o755, parents=True, exist_ok=True)
        shutil.copyfile(binary, target / "mihomo"); (target / "mihomo").chmod(0o755)
        client = {"proxy_url": "http://meimei:" + secrets.token_hex(24) + "@127.0.0.1:17891",
                  "controller_url": "http://127.0.0.1:17892", "controller_secret": secrets.token_hex(32),
                  "runtime_path": str(state / "config.json")}
        runtime = state / "config.json"
        write_config(runtime, runtime_config({}, client), 0o640)
        os.chown(runtime, app_user.pw_uid, group_id)
        write_config(client_path, client)
        os.chown(client_path, app_user.pw_uid, app_user.pw_gid)
        config = data_dir / "openai-egress.json"
        if not config.exists():
            write_config(config, {"enabled": False})
            os.chown(config, app_user.pw_uid, app_user.pw_gid)
        subprocess.run(["runuser", "-u", user, "--", str(target / "mihomo"), "-t", "-d", str(state), "-f", str(runtime)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        shutil.copyfile(Path(__file__).with_name("ai-platform-egress.service"),
                        "/etc/systemd/system/ai-platform-egress.service")
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "enable", "--now", "ai-platform-egress"], check=True)
    print("Installed verified core; feature disabled, subscription empty; no global routing changes.")


if __name__ == "__main__":
    main()
