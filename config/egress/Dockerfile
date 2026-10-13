FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends iptables \
    && rm -rf /var/lib/apt/lists/*
COPY firewall.sh /firewall.sh
ENTRYPOINT ["sh", "/firewall.sh"]
