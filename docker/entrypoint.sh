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
    echo "nexmail: adjusting ownership of the data directory to $PUID:$PGID."
    chown -R "$PUID:$PGID" /data
fi

# ⚠️ **Besitzer ist nicht dasselbe wie beschreibbar.** Die Pruefung darueber
# fasst die Rechte nur an, wenn der *Besitzer* nicht stimmt. Gehoert das
# Verzeichnis auf dem Wirtssystem bereits dem richtigen Benutzer, ist aber
# ueber Zugriffslisten oder Modus-Bits dicht - auf einem NAS der Normalfall -,
# dann wird nichts korrigiert, und nexmail laeuft eine Sekunde spaeter in ein
# "Permission denied" mitten im Start.
#
# Am 01.09.2026 genau so passiert: vierzig Zeilen Python-Rueckverfolgung, aus
# denen niemand liest, dass es um Ordnerrechte geht. Deshalb wird hier
# wirklich geschrieben, und zwar als der Benutzer, der es spaeter tut.
if ! gosu nexmail sh -c 'touch /data/.schreibprobe' 2>/dev/null; then
    echo "nexmail: the data directory is not writable." >&2
    echo "" >&2
    echo "  nexmail runs as uid $PUID, gid $PGID and cannot write to the" >&2
    echo "  directory mounted at /data. Nothing has been started." >&2
    echo "" >&2
    echo "  On the host, that directory needs to belong to that user:" >&2
    echo "" >&2
    echo "      sudo chown -R $PUID:$PGID /path/to/your/data" >&2
    echo "      sudo chmod -R u+rwX /path/to/your/data" >&2
    echo "" >&2
    echo "  PUID and PGID are set in your compose file. To find your own," >&2
    echo "  run 'id' on the host and use the uid and gid it reports." >&2
    exit 1
fi
rm -f /data/.schreibprobe

exec gosu nexmail "$@"
