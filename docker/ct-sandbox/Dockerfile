# Sandbox to PROVE that a change to the installers (provision-game-lxc.sh, lib/ct-phases.sh,
# lib/ct-install.sh, provision-broker-lxc.sh) does what it should. The "CT" is the container
# itself; pct, systemctl, apt-get, curl and SteamCMD are fakes that only record what they got.
# Nothing goes out to the network. Usage: docker/ct-sandbox/compare.sh  and  docker/ct-sandbox/broker.sh
FROM debian:13-slim
# openssl/openssh-client/python3-flask: the broker provisioning generates a real certificate and
# key and imports the real `broker` package (the import breaks if a file is missing from the bundle).
# sudo/openssh-server: lib/ct-panel-access.sh is proven against the REAL sudo (visudo -cf, what
# gamepanel may and may not run) and the real sshd (sshd -t, and an actual login in
# panel-access.sh). They are real, not fakes, because a wrong rule there only shows up as a
# lockout on a real CT.
RUN apt-get update && apt-get install -y --no-install-recommends tar gzip findutils sudo \
      openssl openssh-client openssh-server python3 python3-flask \
 && rm -rf /var/lib/apt/lists/*
# /usr/local/sbin: the installer's `bash -lc` resets PATH, but it always includes this folder
# (and before /usr/bin) - that is where the fakes live so they win over the real binaries.
COPY fakes/ /usr/local/sbin/
COPY fake-steamcmd.sh /usr/local/lib/fake-steamcmd.sh
RUN chmod +x /usr/local/sbin/* /usr/local/lib/fake-steamcmd.sh
COPY run-provision.sh run-broker.sh run-release.sh run-panel-access.sh /usr/local/lib/
RUN chmod +x /usr/local/lib/run-provision.sh /usr/local/lib/run-broker.sh /usr/local/lib/run-release.sh \
      /usr/local/lib/run-panel-access.sh
