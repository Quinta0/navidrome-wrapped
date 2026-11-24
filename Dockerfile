FROM python:3.14-alpine
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN adduser -D -u 1000 wrapped && mkdir /data && chown wrapped /data
COPY wrapped.py design.py serve.py entrypoint.sh /app/
COPY fonts /app/fonts
USER wrapped
WORKDIR /data
VOLUME /data
EXPOSE 8080
ENTRYPOINT ["sh", "/app/entrypoint.sh"]
