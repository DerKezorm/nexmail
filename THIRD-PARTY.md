# Third-party licences

nexmail itself is licensed under the **GNU Affero General Public License v3.0**
(see [LICENSE](LICENSE)). This file lists what it ships or depends on.

## Fonts — bundled, and that is why they are listed first

nexmail **ships the font files** inside the container image. It deliberately
does not load them from Google Fonts or any other host: a mail client that
phones home the moment you open it would be absurd, given that it blocks
tracking pixels in other people's mail.

Shipping it means its licence travels with it. Inter is under the
**SIL Open Font License 1.1**, which permits bundling and redistribution and
requires that this notice accompany the font.

| Font | Copyright | Licence |
|---|---|---|
| Inter | © 2016 The Inter Project Authors | [OFL-1.1](https://github.com/rsms/inter/blob/master/LICENSE.txt) |

Packaged via [Fontsource](https://fontsource.org/); the npm wrappers are MIT.

## Backend

| Package | Licence |
|---|---|
| FastAPI, SQLAlchemy, pydantic, pydantic-settings, argon2-cffi, pyotp, nh3, charset-normalizer, PyJWT, pyzipper, http-ece, cbor2 | MIT |
| uvicorn, IMAPClient, httpx, segno, webauthn | BSD-3-Clause |
| python-multipart, tzdata | Apache-2.0 |
| cryptography, python-dateutil | Apache-2.0 **or** BSD-3-Clause |
| dnspython | ISC |
| py-vapid | MPL-2.0 (used unmodified, as a separate package; its source is at [github.com/mozilla-services/vapid](https://github.com/mozilla-services/vapid)) |
| Pillow | MIT-CMU |
| pillow-heif | BSD-3-Clause for its own code; the binary wheels are **GPLv2** as a whole, see below |

### HEIC photos: pillow-heif and the libraries it brings

Used only to read a profile picture taken on an iPhone. Its binary wheels, and so the container image, contain libheif
(LGPL-3.0), libde265 (LGPL-3.0) and x265 (GPL-2.0-or-later). The wheel ships these notices in
`pillow_heif-*.dist-info/licenses/`. GPL-2.0-or-later and LGPL-3.0 may be combined with an AGPL-3.0 work, and the
source of every part is public.

## Frontend

| Package | Licence |
|---|---|
| React, React DOM, Tiptap (open-source extensions), i18next, react-i18next, Tailwind CSS, Vite, Vitest | MIT |
| TypeScript | Apache-2.0 |
| lucide-react | ISC |
| Playwright | Apache-2.0 |

Only the open-source Tiptap packages (`@tiptap/*`) are used. The commercial
`@tiptap-pro/*` extensions are not part of this project.

## Compatibility

All of the above are permissive licences and may be combined into an
AGPL-3.0 work. The obligation runs one way: nexmail as a whole is AGPL-3.0, and
anyone who runs a modified version as a network service must offer its source.
