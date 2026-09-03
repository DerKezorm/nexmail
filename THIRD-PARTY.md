# Third-party licences

nexmail itself is licensed under the **GNU Affero General Public License v3.0**
(see [LICENSE](LICENSE)). This file lists what it ships or depends on.

## Fonts — bundled, and that is why they are listed first

nexmail **ships the font files** inside the container image. It deliberately
does not load them from Google Fonts or any other host: a mail client that
phones home the moment you open it would be absurd, given that it blocks
tracking pixels in other people's mail.

Shipping them means their licence travels with them. All three are under the
**SIL Open Font License 1.1**, which permits bundling and redistribution and
requires that this notice accompany the fonts.

| Font | Copyright | Licence |
|---|---|---|
| IBM Plex Sans | © 2017 IBM Corp. | [OFL-1.1](https://github.com/IBM/plex/blob/master/LICENSE.txt) |
| Space Grotesk | © 2020 The Space Grotesk Project Authors | [OFL-1.1](https://github.com/floriankarsten/space-grotesk/blob/master/OFL.txt) |
| JetBrains Mono | © 2020 The JetBrains Mono Project Authors | [OFL-1.1](https://github.com/JetBrains/JetBrainsMono/blob/master/OFL.txt) |

Packaged via [Fontsource](https://fontsource.org/); the npm wrappers are MIT.

## Backend

| Package | Licence |
|---|---|
| FastAPI, SQLAlchemy, pydantic, pydantic-settings, argon2-cffi, pyotp, nh3, charset-normalizer, PyJWT, pyzipper | MIT |
| uvicorn, IMAPClient, httpx, segno | BSD-3-Clause |
| python-multipart, tzdata | Apache-2.0 |
| cryptography, python-dateutil | Apache-2.0 **or** BSD-3-Clause |

## Frontend

| Package | Licence |
|---|---|
| React, React DOM, Tiptap (open-source extensions), i18next, react-i18next, Tailwind CSS, Vite, TypeScript | MIT |
| lucide-react | ISC |
| Playwright | Apache-2.0 |

Only the open-source Tiptap packages (`@tiptap/*`) are used. The commercial
`@tiptap-pro/*` extensions are not part of this project.

## Compatibility

All of the above are permissive licences and may be combined into an
AGPL-3.0 work. The obligation runs one way: nexmail as a whole is AGPL-3.0, and
anyone who runs a modified version as a network service must offer its source.
