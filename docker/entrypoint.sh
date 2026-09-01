#!/bin/sh
# Startskript des Containers.
#
# Hintergrund: nexmail soll nicht als Administrator laufen. Sobald das
# Datenverzeichnis aber von aussen eingehaengt wird (NAS, Server), gelten die
# Rechte des Wirtssystems - und die passen praktisch nie zufaellig zu dem
# Benutzer im Abbild. Deshalb startet der Container kurz als Administrator,
# richtet die Rechte am Datenverzeichnis ein und gibt die Kontrolle dann an den
# unprivilegierten Benutzer "nexmail" ab.
#
# Ueber PUID/PGID laesst sich einstellen, welchem Benutzer des Wirtssystems die
# Dateien gehoeren sollen - genauso wie bei den ueblichen Selbsthoster-Abbildern.

set -e

PUID=${PUID:-1000}
PGID=${PGID:-1000}

# Auf welchem Port nexmail lauscht. Standard 8000; ueber NEXMAIL_PORT laesst er
# sich umstellen. Gebraucht wird das im Host-Netzwerk-Betrieb: dort gibt es
# keine Portzuordnung, der Port im Container *ist* der Port des Servers.
#
# Warum hier und nicht im Dockerfile: In der JSON-Form von CMD ersetzt Docker
# keine Variablen. Und warum so weit oben: Weiter unten gibt es einen Ausgang,
# der greift, wenn der Container bereits unprivilegiert startet.
if [ "$1" = "uvicorn" ]; then
    case " $* " in
        *" --port "*) ;;
        *) set -- "$@" --port "${NEXMAIL_PORT:-8000}" ;;
    esac
fi

# Laeuft der Container bereits ohne Administratorrechte (z. B. weil in der
# compose-Datei "user:" gesetzt ist), gibt es nichts einzurichten.
if [ "$(id -u)" != "0" ]; then
    exec "$@"
fi

if [ "$(id -g nexmail)" != "$PGID" ]; then
    groupmod -o -g "$PGID" nexmail
fi
if [ "$(id -u nexmail)" != "$PUID" ]; then
    usermod -o -u "$PUID" nexmail
fi

mkdir -p /data

# Rechte nur anfassen, wenn sie wirklich nicht stimmen: Bei vielen Anhaengen
# wuerde ein "chown -R" bei jedem Start unnoetig Zeit kosten.
if [ "$(stat -c %u /data)" != "$PUID" ] || [ "$(stat -c %g /data)" != "$PGID" ]; then
    echo "nexmail: Rechte am Datenverzeichnis werden auf $PUID:$PGID gesetzt."
    chown -R "$PUID:$PGID" /data
fi

exec gosu nexmail "$@"
