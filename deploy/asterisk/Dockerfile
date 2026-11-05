FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends asterisk python3 ca-certificates && rm -rf /var/lib/apt/lists/*
COPY scripts/asterisk_agi.py /var/lib/asterisk/agi-bin/secretai.py
RUN chmod 755 /var/lib/asterisk/agi-bin/secretai.py
COPY deploy/asterisk/extensions.conf /etc/asterisk/extensions.conf
COPY deploy/asterisk/rtp.conf /etc/asterisk/rtp.conf
USER asterisk
CMD ["asterisk","-f","-U","asterisk","-G","asterisk"]
