# Stellar Archive universal SG1_v3 / SG1_v4 installer

Version 1.5.22 contains one entry-point installer and two isolated adapters. It
automatically detects the standard SG1_v3 application or SG1_v4 web layout and
uses only the matching adapter.

For a host that needs a different HOME destination, create
`.stellar-archive-addon/home-routes.json` in the SG1_v4 web root before running
the installer again. The file is a JSON object mapping lowercase hostnames to
same-origin receiver paths. For a matching host, the map controls the Archive
logo, HOME button and DIAL receiver; installations without a map continue to
follow the selected Original or Retro integration mode.

## Install

```bash
cd /home/pi
unzip sg1_v3_v4_stellar_archive_universal_1.5.22.zip
cd sg1-v3-v4-stellar-archive-universal-v1.5.22
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

On SG1_v4, a transient central-directory failure is retried after 2, 4, 8 and
at most 15 minutes while the configured normal refresh interval remains
unchanged. A valid retry updates the address book immediately. Until then,
stale Standard and FAN records remain fail-closed rather than appearing online.

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
- The v4 adapter preserves Original/Retro pages, navigation and the original
  address manager for exact uninstall restoration.
- Updates refuse to overwrite managed files that were changed outside the
  installer.
- `--dry-run` performs detection and validation without writing.

The Gaia artwork, credits and licence remain documented in
`GAIA-ASSET-LICENCE.md`.

## License

Original Stellar Archive software is released under the MIT License. See
`LICENSE`. Gaia-derived artwork and other third-party material remain governed
by their separately documented licenses and are not relicensed by the MIT
License.

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

## Installed matelv-x add-ons

The same About dialog scans the current Raspberry Pi for supported add-ons from
the `matelv-x` GitHub organization. Detection uses each add-on's installed files
and, when present, its local Git checkout. It is not tied to ***, a Pi
model, a host name or an IP address.

The About dialog contains two expandable sections. `INSTALLATIONS` shows Stellar
Archive and every detected managed add-on with update and surgical uninstall
controls. `MATELV-X ADD-ONS` shows compatible public add-ons which are not yet
installed. Its `INSTALL` button remains locked until the adjacent information
button opens the repository, allowing the user to review the add-on first.

The public catalogue currently includes Alarm Clock, Aquila Symbol Patch,
Connection History, DHD LED Test, Dynamic Wormhole, FAN113 Home, LAN Discovery,
Lamp Mode, Retro Visuals, Retro Wormhole Animation, SG1 Iris, Silence Mode,
Stargate Ring Symbols, Switch To Retro and Visual Volume Meter. Alarm Clock now has a bounded
uninstall which removes only its owned files and exact integration blocks; it
does not restore the complete SG1 tree.

Before running downloaded code the manager verifies all of the following:

- the repository belongs to `matelv-x`;
- the remote repository contains `stargate-addon.json` with maintenance
  contract version 1 and surgical uninstall contract version 2;
- the manifest identity matches the selected add-on;
- the requested command is declared in that verified manifest;
- a new installation declares both install and uninstall procedures;
- no Archive or other add-on maintenance operation is already active.

Before every add-on removal the manager silently resolves the current GitHub
HEAD revision with a fresh operation-time query; catalogue display cache is
never trusted for removal. If that exact verified uninstaller is already cached on the Pi
or present in its managed checkout, it is used locally and nothing is
downloaded. A newer revision is downloaded, identity-checked and cached before
its declared surgical removal command can run. If the lightweight revision
check cannot confirm the result, the manager does not use a possibly stale
local copy: it always downloads the current default branch from GitHub and
verifies that fresh checkout before removal.

Managed procedures run with `STARGATE_ADDON_NO_RESTART=1`. They can update web
files but do not restart Stargate software or reboot the Pi. The progress window
shows Download, Verify, Install and Complete stages. When a verified add-on
declares that a restart is required, the user can choose `LATER` or explicitly
authorize `RESTART SERVICE`. That action targets only the exact systemd service
detected for the installed application root; if no unique service is found, the
web restart remains unavailable. Private repositories
are supported only when the Pi already has Git credentials for them and their
installed checkout contains the same manifest. The installer never embeds or
stores a GitHub token.

On phones, tapping `INFO` may open the GitHub mobile app. The browser session
remembers that explicit review action, so returning to Stellar Archive unlocks
`INSTALL` without requiring GitHub to remain inside the browser tab. The mobile
Archive uses a native stacked layout instead of shrinking the desktop canvas.

Older private or hardware-control repositories that restore an entire SG1 tree,
change system services, or lack this contract are intentionally not exposed in
the About dialog. They must first be converted to a bounded, reversible
installer so removing one add-on cannot remove another.
