FROM python:3.14-alpine
RUN adduser -D -u 1000 wrapped && mkdir /data && chown wrapped /data
COPY wrapped.py entrypoint.sh /app/
USER wrapped
WORKDIR /data
VOLUME /data
EXPOSE 8080
ENTRYPOINT ["sh", "/app/entrypoint.sh"]
