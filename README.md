# Stellar Archive universal SG1_v3 / SG1_v4 installer

Version 1.3.1 contains one entry-point installer and two isolated adapters. It
automatically detects the standard SG1_v3 application or SG1_v4 web layout and
uses only the matching adapter.

## Install

```bash
cd /home/pi
unzip sg1_v3_v4_stellar_archive_universal_v1.3.1.zip
cd sg1-v3-v4-stellar-archive-universal-v1.3.1
./install.sh
```

Use `sudo ./install.sh` on SG1_v3 when the `pi` account cannot write to
`/home/sg1/sg1`. The installer never reboots, restarts software or sends a
hardware command.

Detection can be overridden for a nonstandard test tree:

```bash
./install.sh --platform v3 --target /home/sg1/sg1
./install.sh --platform v4 --target /home/pi/sg1_v4/web
```

Uninstall with the same universal package:

```bash
./install.sh --uninstall
```

## SG1_v4 adapter

SG1_v4 retains the established interactive choices:

- replace the Original address book;
- replace Retro when Retro is installed;
- replace both;
- install Stand-alone and add navigation links.

Non-interactive v4 examples:

```bash
./install.sh --platform v4 --replace original
./install.sh --platform v4 --replace retro
./install.sh --platform v4 --replace both
./install.sh --platform v4 --replace standalone
```

The adapter supports the standard layouts from
`jonnerd154/StargateProject-software` and
`matelv-x/SG1-v4-Pi5-64bit-First-Boot`. Existing backup, mode switching,
optional Retro, direct 9-chevron routing and exact uninstall behavior remain
unchanged from the tested v1.2.8 release.

## SG1_v3 adapter

SG1_v3 has no native web root or HTTP dialing API. The v3 adapter therefore:

1. copies Archive under `/home/sg1/sg1/stellar-archive`;
2. adds the dependency-free `stellar_archive_bridge.py` module;
3. inserts a bounded, marked bridge startup block after `StargateSG1()` is
   constructed in `main.py`;
4. starts a static/API server inside the existing SG1_v3 process on port 80;
5. submits a selected address to the same in-memory outgoing buffer used by the
   physical DHD.

Dialing requires a same-origin JSON POST. GET requests never initiate physical
activity. The bridge rejects malformed, repeated, unknown or busy-state
addresses, appends Earth origin glyph 1, and then sets the normal SG1_v3 centre
button state. It does not bypass SG1_v3 address validation.

Because v3 has no reliable live-status publication for every fan gate, Archive
shows remote status as unknown. It reports the installed gate and local address
without inventing online/offline values.

After v3 installation or removal, restart the SG1_v3 application or reboot the
Pi once. The installer deliberately does not perform that restart.

## URL

After installation (and the required v3 restart), open:

```text
http://DEVICE-IP/stellar-archive/
http://DEVICE-HOSTNAME.local/stellar-archive/
```

## Safety and rollback

- Both adapters validate their platform before changing files.
- The v3 adapter preserves the original `main.py`, any pre-existing bridge and
  any pre-existing Archive directory.
- The v4 adapter preserves Original/Retro pages and navigation as before.
- Updates refuse to overwrite managed files that were changed outside the
  installer.
- `--dry-run` performs detection and validation without writing.

The Gaia artwork, credits and licence remain documented in
`GAIA-ASSET-LICENCE.md`.

## About maintenance controls

The About dialog contains `CHECK FOR UPDATES` and `UNINSTALL`. Both controls
use a same-origin local API; they cannot be triggered by an ordinary cross-site
browser request.

Update checks read the latest public release from
`matelv-x/Stellar-Archive`. Installation starts only when both of these release
assets are present and the downloaded checksum matches:

```text
sg1_v3_v4_stellar_archive_universal_X.Y.Z.zip
sg1_v3_v4_stellar_archive_universal_X.Y.Z.zip.sha256
```

The updater selects the already detected platform and preserves the active v4
replacement mode. After an update or web-triggered uninstall, restart the
Stargate software once so the running Python process loads or removes the
maintenance endpoint.
