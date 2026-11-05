FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends asterisk python3 ca-certificates && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /run/asterisk /var/log/asterisk /var/spool/asterisk && chown -R asterisk:asterisk /run/asterisk /var/log/asterisk /var/spool/asterisk \
    && test -f /usr/lib/*-linux-gnu/asterisk/modules/app_audiosocket.so
COPY scripts/asterisk_agi.py /var/lib/asterisk/agi-bin/secretai.py
RUN chmod 755 /var/lib/asterisk/agi-bin/secretai.py
COPY deploy/asterisk/extensions.conf /etc/asterisk/extensions.conf
COPY deploy/asterisk/rtp.conf /etc/asterisk/rtp.conf
USER asterisk
CMD ["asterisk","-f","-U","asterisk","-G","asterisk"]
