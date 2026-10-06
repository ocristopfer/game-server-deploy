"""Is the broker on this CT answering? Exit 0 = yes. Used by the automatic update to decide a rollback.

    cd /opt/gamebroker/current && python3 -m gamebroker.healthcheck --port 8443

The broker's /v1/health is HTTPS with its own self-signed certificate and a token, so `wget`
(the panel's probe) cannot be used without turning verification off - which this project does
nowhere. Instead the certificate is PINNED by its own fingerprint, read from the file on this CT,
through the same pinned client the broker uses for Proxmox and OPNsense.

Only the broker itself counts (`"broker": true`). Proxmox or OPNsense not answering is their
problem, not the new release's: rolling back over it would undo a good update.
"""
from __future__ import annotations

import hashlib
import ssl
import sys

from gamebroker.integrations import http_client

# A PATH to the token, written by provisioning (0600), not a token.
TOKEN_FILE = "/etc/gamebroker/token"  # noqa: S105
CERT_FILE = "/etc/gamebroker/tls/cert.pem"
# /v1/health also asks Proxmox and OPNsense, each with its own short deadline.
TIMEOUT = 30.0
MAX_PORT = 65535


def fingerprint(pem: str) -> str:
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()


def check(port: int) -> str:
    """'' when the broker answered healthy, else the reason (no secret in it)."""
    try:
        with open(TOKEN_FILE, encoding="utf-8") as fh:
            token = fh.read().strip()
        with open(CERT_FILE, encoding="ascii") as fh:
            pin = fingerprint(fh.read())
    except (OSError, ValueError) as exc:
        return f"cannot read the token or the certificate: {type(exc).__name__}"
    client = http_client.Client(f"https://127.0.0.1:{port}", {"Authorization": f"Bearer {token}"},
                                pin, timeout=TIMEOUT)
    try:
        response = client.request("GET", "/v1/health")
    except http_client.ConnectionFailed as exc:
        return f"no answer: {exc}"
    if not response.ok:
        return f"HTTP {response.status}"
    if not (isinstance(response.json, dict) and response.json.get("broker")):
        return "answered, but not as a healthy broker"
    return ""


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2 or args[0] != "--port" or not args[1].isdigit() or not 1 <= int(args[1]) <= MAX_PORT:
        print("usage: python3 -m gamebroker.healthcheck --port N", file=sys.stderr)
        return 2
    problem = check(int(args[1]))
    if problem:
        print(f"health: {problem}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - run by install-release.sh
    sys.exit(main())
