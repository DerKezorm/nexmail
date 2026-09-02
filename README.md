<div align="center">

<img src="backend/app/vorlagen/logo.png" width="72" alt="nexmail">

# nexmail

**A self-hosted email client. One container, one file, your mailboxes stay with you.**

[Project site](https://nexmail.nexapps.dev) · [Report an issue](https://github.com/DerKezorm/nexmail/issues/new)

<picture>
  <source media="(prefers-color-scheme: light)" srcset="docs/screenshots/mail-hell-en.webp">
  <img src="docs/screenshots/mail-lesen-en.webp" alt="nexmail: folder column, message list and reading pane">
</picture>

</div>

---

nexmail brings several IMAP mailboxes together in one place and runs on your own
machine. It is meant for people who already host things at home: one container,
a single SQLite file, no second database, no cloud account, and no service that
gets to see your mail on the way.

Roundcube is webmail bolted onto one mailbox. Thunderbird does not run in a
browser. Commercial clients want to pull your mail onto their servers. nexmail
is the third option — and if you can use Outlook, you should feel at home.

> **Version 0.3.0.** It reads, writes, searches, sorts, sends, schedules,
> prints and backs itself up. It is used daily by its author against real
> iCloud and IMAP mailboxes, and more than 600 automated tests watch over it —
> including a suite that runs in a real browser. It is still young: try it on
> a mailbox you can afford to have trouble with before you point it at the one
> that matters.

The screenshots below show a throwaway instance filled with invented mail.
Every address in them is under `example.com`, `example.org` or
`example.net`, which RFC 2606 reserves for exactly this purpose.

## What it does

**Mail.** Several mailboxes side by side, plus a merged *All inboxes* view.
Read, reply, reply-all, forward, move, archive, delete, mark, flag, undo. Drag
and drop between folders. Keyboard: `Del` to trash, `E` to archive.

**Conversations.** Related messages fold into one row — matched by the reply
chain first, subject only as a fallback and only when sender, subject and a
30-day window all agree. Off by default: grouping wrongly *hides* a message, and
you notice that at the worst possible moment.

**Writing.** A real formatting toolbar (Tiptap), attachments, pasted images,
drafts stored in the mailbox rather than in the browser, and an outbox that
survives a restart. Recipients become address bubbles as you type; nonsense
turns red instead of hiding inside a comma list. Set importance, get a
question when the text mentions an attachment that is not there, and forward
a message as an untouched `.eml` when someone needs the real thing.

**Send later, take it back.** Schedule a message for this evening, tomorrow
morning or any moment; it waits in nexmail's own outbox, visibly, and
cancelling files it as a draft. Undo send holds every outgoing message for a
few configurable seconds first — undo brings it straight back into the
compose window.

![The compose window with its formatting toolbar](docs/screenshots/verfassen-en.webp)

**Search.** Full-text over everything cached, plus `IMAP SEARCH` at the provider
on request. The interface says how far it looked — a search that hides its own
reach lets you conclude a message does not exist.

![Search results, with a line saying which part was covered](docs/screenshots/suche-en.webp)

**Tasks.** Turn a message into a task, tick it off, drag it into order, give it
a due date. The task survives its message: if the mail is moved from your phone,
the task follows it by `Message-ID`; if the mail is deleted, the task stays and
says so.

**Contacts, rules, signatures.** An address book with vCard import and export
and collection from Sent; contact groups that expand into their members when
picked as a recipient; rules that run after each sync and only on new mail;
signatures per mailbox.

**Housekeeping.** Trash and junk can empty themselves after a number of days —
off by default, measured by how long a message has been in the folder, and
never touching a folder you created yourself. Printing produces a clean
document and goes straight to the print dialog. On a phone, swiping a row
archives or deletes, with the same undo as everywhere else.

| Tasks | Contacts |
|---|---|
| ![The task list](docs/screenshots/aufgaben-en.webp) | ![The address book](docs/screenshots/kontakte-en.webp) |

**Mailbox groups.** Tag mailboxes (`personal`, `work`, `club`) and switch
between them above the folder tree.

**HTML mail, defused.** Server-side sanitising with an allow-list, images
unhooked until you ask for them, and an iframe sandbox without scripts. The same
sanitising runs on what *you* write, on the way out.

## What it is not

* **No calendar.** That is a second mail core in size.
* **No PGP or S/MIME.** Key management is a project of its own.
* **No Microsoft 365 yet.** Basic auth for IMAP/SMTP is switched off in most
  tenants, and OAuth for mailbox access is not built yet. Gmail works with an
  app password and two-factor auth. iCloud, GMX, web.de, mailbox.org and plain
  IMAP servers work without detours.

## Built with

FastAPI · SQLAlchemy · SQLite · React · Vite · Tailwind CSS · Tiptap · IMAPClient

One container. SQLite instead of Postgres is not a shortcut here, it is a
feature: no second container, no database credentials, and a backup is a copy.

## Running with Docker

```yaml
services:
  nexmail:
    image: ghcr.io/derkezorm/nexmail:latest
    container_name: nexmail
    restart: unless-stopped
    ports:
      - "5174:8000"
    volumes:
      - ./data:/data
    environment:
      PUID: 1000
      PGID: 1000
```

```bash
docker compose up -d
```

Then open `http://<server>:5174`. On first run you set a username and password.
After that, this route is closed.

> ⚠️ **Until the first account exists, anyone can create it.** There is no
> account that could authenticate at that point — it cannot work any other way.
> Set it up on your home network before you expose it.

The full compose file with every option and the reasoning behind each one is
[`docker-compose.yml`](docker-compose.yml) in this repository.

### Your mailbox credentials

nexmail asks for them **in its own interface and nowhere else**. You add
mailboxes under *Settings → Mailboxes*. They are stored encrypted and never
leave your server.

![The mailbox list under Settings](docs/screenshots/postfaecher-en.webp)

For iCloud you need an **app-specific password** from `account.apple.com`. Your
normal Apple password is refused, and iCloud reports that with the same message
it uses for a typo. nexmail says so in the connection test, so you do not spend
ten minutes doubting your password.

### What to back up

Everything is under `/data`:

| | |
|---|---|
| `nexmail.db` | mailboxes, messages, contacts, rules, sessions |
| `secret.key` | **the key to every stored mailbox password** |
| `blobs/` | attachments, stored by checksum |

> ⚠️ **`secret.key` and the database belong together.** Without the key the
> database is unreadable. With both, whoever holds them holds your mailboxes.

### Backup and restore

Under *Administration → Backup*. Two things live there, and telling them apart
matters when it counts:

**Restore points** are complete copies next to the database, made automatically
before any schema change and by hand whenever you want, on a schedule if you
like. They are for a failed update or a contact deleted by mistake. If the disk
dies, they die with it.

**A backup** is what you download: an encrypted ZIP, and deliberately **without
the messages**. Those are still in the mailbox on the server, and nexmail
fetches them back after a restore. Measured on a real database: 1890 messages
turn 0.36 MB into 2.79 MB, and the part that cannot be fetched again does not
grow with the mailbox. An archive that grows with your mail is one nobody
downloads.

Restoring happens in two steps. The first only looks: it reports the version,
whether the key is included, and whether the public address in the archive
differs from the one you are using. It has to ask about that one, because
invitation links and the OpenID Connect redirect are built from it — and the
redirect URI registered with your provider is something nexmail cannot change
for you, so the report spells it out.

> ⚠️ **Put `/data` on a local disk, never on an SMB or NFS share.** That is the
> one way SQLite genuinely loses data: its locking does not work reliably over
> network filesystems. On a NAS, use a path on the internal volume.

### Behind a reverse proxy

Set `NEXMAIL_URL_BASE=/nexmail` and nexmail runs under
`https://example.org/nexmail`. It answers every address twice — with and without
the prefix — because proxies are configured both ways.

Set `NEXMAIL_COOKIE_SECURE` to match your setup. `auto` (the default) marks the
session cookie `Secure` when the request arrived over HTTPS. Use `on` only if a
proxy terminates TLS and forwards plain HTTP internally — and never if nexmail
should also be reachable over `http://`, because the browser discards a Secure
cookie sent over http and then nobody gets in.

## Signing in through an external provider

nexmail speaks OpenID Connect: Keycloak, Authentik, Authelia, Pocket ID and
anything else that follows the spec. Add a provider under *Administration →
OIDC*; the redirect URI to register with the provider is shown there with a copy
button.

![The sign-in tab with one registered provider](docs/screenshots/oidc-en.webp)

**Two ways in, and no others:**

1. **An existing link.** You create it while signed in, under *Settings →
   Security → Link*.
2. **An open invitation to exactly that address.** The account is created from
   the invitation, and the invitation is spent.

> ⚠️ **There is deliberately no matching against existing accounts by email.**
> That would be the place where a provider claiming an address it does not own
> could open somebody else's account. An invitation is a decision the operator
> made on purpose.

The address still has to be marked verified by the provider — otherwise a
provider that lets anyone enter any address would be enough to claim an
invitation meant for someone else.

> ⚠️ **The issuer must be one address that both the browser and the server can
> reach.** The browser fetches the sign-in page; the container fetches the
> discovery document and the token. If you run the provider in the same Docker
> network, enter it under the address the *browser* knows, not its container
> name.

## Several people

Invite them under *Administration → Users*. nexmail sends the invitation itself,
which needs an outgoing mail server of its own under *Administration → Server* —
deliberately not the operator's mailbox, so that removing that mailbox does not
take the invitations with it.

The invitation page offers both ways: set a password, or sign in through a
provider. Not everyone has an account with your identity provider, and not
everyone should need a password they will never use.

![Administration with users and open invitations](docs/screenshots/verwaltung-en.webp)

Every user has their own mailboxes, contacts, rules and signatures. A guard test
walks the entire route table and checks that no address answers without
authentication and none hands out another user's data.

## Security, honestly

**Two-factor is available and optional.** TOTP with replay protection, ten
single-use recovery codes, and a per-user switch — including for the operator.
On a purely local network it is reasonable to leave it off; reachable from the
internet it is not, and nexmail says so where you make the choice.

**Sessions live on the server, not in a token.** That costs one query per
request and buys *sign out everywhere* with immediate effect. Devices are listed
and can be revoked individually.

![The security tab with two-factor and signed-in devices](docs/screenshots/sicherheit-en.webp)

**Passwords use Argon2id**, sign-ins are rate-limited, and a spent recovery code
stays spent.

**What two factors cannot do — plainly.** Mailbox passwords must be decryptable
on disk, because syncing runs while nobody is signed in. The key sits in
`/data/secret.key`. **Whoever has file access has your mailboxes**, and no login
changes that. Setting `NEXMAIL_SECRET_KEY` moves the key out of the data
directory, which is the one effective lever: a stolen backup alone is then
worthless.

## Development

```bash
# Backend
cd backend && python -m venv .venv && .venv/bin/pip install -r requirements.txt
NEXMAIL_DATA_DIR=../data-dev .venv/bin/python -m uvicorn app.main:app --reload --port 8010

# Frontend
cd frontend && npm install && npm run dev
```

```bash
cd backend && python -m pytest        # ~590 tests
cd frontend && npm run test:ui        # Playwright, two viewports
```

The interface tests run in a real browser against a real IMAP mailbox. That is
why they prove anything — jsdom would not have found a single one of the layout
and rendering faults they were written for.

## Licence

[GNU Affero General Public License v3.0](LICENSE). Third-party licences,
including the bundled fonts, are listed in [THIRD-PARTY.md](THIRD-PARTY.md).
