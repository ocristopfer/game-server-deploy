# Broker de brinquedo - imagem de DESENVOLVIMENTO (broker/dev.py: backends falsos).
# Nao e a imagem do broker de producao, que roda num CT proprio com o Proxmox e o OPNsense
# de verdade. Mesmas dependencias que ele tera: so python3-flask do apt, nada de pip.
FROM debian:13-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-flask ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/gamebroker
EXPOSE 8090
# O pacote `broker/` e o catalogo `games/` entram por bind mount (ver docker-compose.yml).
CMD ["python3", "-m", "broker.dev"]
