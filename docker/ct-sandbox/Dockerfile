# Sandbox para PROVAR que uma mudanca nos instaladores (provision-game-lxc.sh, lib/ct-phases.sh,
# lib/ct-install.sh, provision-broker-lxc.sh) faz o que deveria. O "CT" e o proprio container;
# pct, systemctl, apt-get, curl e o SteamCMD sao falsos e so registram o que receberam. Nada
# sai para a rede. Uso: docker/ct-sandbox/compare.sh  e  docker/ct-sandbox/broker.sh
FROM debian:13-slim
# openssl/openssh-client/python3-flask: o provisionamento do broker gera certificado e chave de
# verdade e importa o pacote `broker` de verdade (o import quebra se faltar arquivo no bundle).
RUN apt-get update && apt-get install -y --no-install-recommends tar gzip findutils sudo \
      openssl openssh-client python3 python3-flask \
 && rm -rf /var/lib/apt/lists/*
# /usr/local/sbin: o `bash -lc` do instalador zera o PATH, mas ele sempre traz esta pasta
# (e antes de /usr/bin) - e onde os falsos ficam para vencer os binarios de verdade.
COPY fakes/ /usr/local/sbin/
COPY fake-steamcmd.sh /usr/local/lib/fake-steamcmd.sh
RUN chmod +x /usr/local/sbin/* /usr/local/lib/fake-steamcmd.sh
COPY run-provision.sh run-broker.sh run-release.sh /usr/local/lib/
RUN chmod +x /usr/local/lib/run-provision.sh /usr/local/lib/run-broker.sh /usr/local/lib/run-release.sh
