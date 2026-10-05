# Security policy

The panel runs with **root access to your game containers**, and the broker holds
Proxmox and OPNsense credentials. Please treat security issues accordingly.

## Reporting a vulnerability

Do **not** open a public issue. Use GitHub's private vulnerability reporting
(the "Report a vulnerability" button on the repository's **Security** tab) and include:

- what is affected (panel, broker, deploy scripts, game-container scripts);
- steps to reproduce, or a proof of concept;
- the version (`/health` returns it, and it is shown in the footer of every page).

You should get an answer within a few days. Fixes are released as a new tagged
version; the advisory is published once a fixed release is available.

## Supported versions

Only the latest release receives fixes.

## Deployment hardening (short version)

- Never expose the development `docker compose` stack: it ships a known
  `admin/admin12345` login and is bound to `127.0.0.1` on purpose.
- Put the panel behind TLS (a reverse proxy) or a VPN. When
  `GAMEPANEL_WEBAUTHN_ORIGIN` is an `https://` address the session cookie is
  marked `Secure`.
- Turn on two-factor authentication for every admin, then set
  `GAMEPANEL_REQUIRE_2FA=1`. Broker actions always require 2FA.
- Keep `GAMEPANEL_ALLOW_BROKER=0` unless you use the broker.
- Container root passwords are not set by default (`CT_PASSWORD` empty): access is by
  `pct enter` or SSH key only.
