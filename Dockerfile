# nexmail als ein einziger, schlanker Container.
#
# Zwei Stufen: erst wird die Oberflaeche gebaut, dann landen nur die fertigen
# Dateien im Abbild. Node und die node_modules bleiben draussen - im Betrieb
# liefert FastAPI die gebauten Dateien einfach mit aus.

# --- Stufe 1: Oberflaeche bauen ---------------------------------------------
#
# ⚠️ **`--platform=$BUILDPLATFORM` gehoert hierher, und es spart Stunden.**
# Das Abbild wird fuer amd64 *und* arm64 gebaut. Ohne diese Angabe baut Docker
# auch diese Stufe zweimal - die zweite davon unter Emulation, und ein "npm ci"
# unter emuliertem ARM ist absurd langsam.
#
# Noetig ist das nie: Aus dieser Stufe wandert unten ausschliesslich
# /build/dist weiter, und das ist HTML, CSS und JavaScript. Da steckt nichts
# Architekturabhaengiges drin.
FROM --platform=$BUILDPLATFORM node:22-alpine AS oberflaeche

WORKDIR /build

# Erst nur die Abhaengigkeitsdateien: Solange sie sich nicht aendern, nutzt
# Docker beim naechsten Bauen den Zwischenstand und spart die Minuten fuer
# "npm ci".
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# --- Stufe 2: Laufzeit -------------------------------------------------------
FROM python:3.13-slim

# PYTHONUNBUFFERED: Ausgaben landen sofort im Docker-Protokoll statt erst beim
# Beenden. PYTHONDONTWRITEBYTECODE: keine .pyc-Dateien im Abbild.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NEXMAIL_DATA_DIR=/data \
    NEXMAIL_STATIC_DIR=/app/static

WORKDIR /app

# curl fuer den Healthcheck, gosu zum Ablegen der Administratorrechte beim
# Start. --no-install-recommends haelt das Abbild klein.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gosu \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY --from=oberflaeche /build/dist ./static

# Der Benutzer, unter dem nexmail spaeter laeuft. Der Container startet zwar
# als Administrator, gibt die Rechte im Startskript aber sofort wieder ab -
# das ist noetig, um ein von aussen eingehaengtes Datenverzeichnis nutzbar zu
# machen.
RUN useradd --system --create-home --uid 1000 nexmail \
    && mkdir -p /data \
    && chown -R nexmail:nexmail /data /app

COPY docker/entrypoint.sh /entrypoint.sh
# Das sed entfernt Windows-Zeilenenden: Wer unter Windows auscheckt und baut,
# bekaeme sonst ein Skript, das Linux gar nicht erst startet.
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

VOLUME ["/data"]
# Nur eine Angabe fuer Werkzeuge, die sie auslesen - der tatsaechliche Port
# kommt aus NEXMAIL_PORT und wird im Startskript gesetzt.
EXPOSE 8000

# Der Healthcheck fragt genau das, was auch die Oberflaeche braucht. Ohne
# Anmeldung - er soll ja gerade dann antworten, wenn etwas nicht stimmt.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${NEXMAIL_PORT:-8000}/api/health" || exit 1

# ⚠️ **Ein Arbeitsprozess.** Die Datenbank ist SQLite, und der Abgleich der
# Postfaecher soll nicht mehrfach laufen - zwei Prozesse wuerden dasselbe
# Postfach gleichzeitig abfragen, und Apple wirft bei zu vielen gleichzeitigen
# IMAP-Verbindungen heraus.
ENTRYPOINT ["/entrypoint.sh"]
# Ohne "--port": den haengt das Startskript aus NEXMAIL_PORT an.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--workers", "1"]
