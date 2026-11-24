"""Der Notfallbefehl: ein Link fuer ein neues Passwort, ohne dass jemand angemeldet ist.

Fuer den einen Fall, den sonst nichts loest: Der einzige Betreiber hat sein Passwort vergessen, und es gibt keinen
Postausgang (oder keine Adresse). Wer an den Container kommt, kommt ohnehin an ``/data``; der Befehl macht also kein
neues Loch auf, er macht ein vorhandenes benutzbar (dieselbe Ueberlegung wie bei ``NEXMAIL_ZWEI_FAKTOR_AUS``).

    docker exec -it nexmail python -m app.notfall reset-link <benutzername oder e-mail> [--tage 1|7|30]

Der Link steht nur auf der Konsole, nie in einer Mail; er gilt einmal. Im Protokoll steht, dass er vom Server kam.
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.notfall", description="nexmail emergency commands")
    befehle = parser.add_subparsers(dest="befehl", required=True)
    link = befehle.add_parser("reset-link", help="make a link to set a new password, shown here once")
    link.add_argument("wer", help="the username or the email address of the account")
    link.add_argument("--tage", type=int, default=1, choices=(1, 7, 30), help="how many days the link holds")
    argumente = parser.parse_args(argv)

    from .db import SessionLocal, init_db
    from .services import konten_store, kontenpost
    from .vendor import nexkonten

    init_db()
    with SessionLocal() as db:
        try:
            ergebnis = nexkonten.resets.server_reset_link(
                konten_store.store_fuer(db), argumente.wer, days=argumente.tage
            )
        except nexkonten.AccountError as fehler:
            print(f"No link: {fehler.message}", file=sys.stderr)
            return 1
        basis = kontenpost.oeffentliche_adresse(db)
    pfad = f"/kennwort/{ergebnis.token}"
    if basis:
        print(f"{basis}{pfad}")
    else:
        print(f"No public address is set; open nexmail and append this path: {pfad}")
    print(f"The link works once and holds until {ergebnis.expires_at:%Y-%m-%d %H:%M} UTC.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
