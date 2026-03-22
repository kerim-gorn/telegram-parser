FROM alpine:3.20

RUN apk add --no-cache autossh openssh-client netcat-openbsd

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 1080

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD nc -z 127.0.0.1 1080 || exit 1

ENTRYPOINT ["/entrypoint.sh"]
