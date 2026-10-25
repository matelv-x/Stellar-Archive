# Changelog

## 1.5.10

- Preserves declared add-on overlays while Archive temporarily restores its
  clean baseline during an update. This keeps the combined Retro Visuals and
  Stellar Archive backend plus Retro navigation intact across updates.
- Safely removes only Archive's own stand-alone Retro link during uninstall,
  without removing the add-on navigation around it.

## 1.5.9

- Extends the bounded Retro Visuals migration to its declared `web_server.py`
  integration. The exception applies only to a recorded, currently detected
  add-on and only to the files declared by that add-on; unrelated backend
  changes remain blocked.

## 1.5.8

- Adds a bounded legacy migration for add-ons installed before 1.5.7. Only
  integration files explicitly declared by a detected, recorded Matelv-x
  add-on are adopted, allowing Retro Visuals users to update Archive without
  weakening validation of backend or unrelated files.

## 1.5.7

- Preserves verified add-on edits to Archive-managed navigation pages by
  refreshing the bounded integration snapshots after each successful managed
  add-on operation. This prevents a later Archive update from rejecting a
  legitimate Retro Visuals menu change.

## 1.5.6

- Rebuilds Stellar Archive navigation automatically after a managed add-on is
  installed, updated or uninstalled, so newly added pages such as Retro
  Visuals appear in Archive without reinstalling Archive.

## 1.5.5

- Fixed add-on actions behind reverse proxies and in Safari/WebViews that send
  an opaque or proxy-mismatched Origin while preserving cross-site rejection.
- INFO review state now survives a return from the GitHub mobile app within the
  browser session, so INSTALL unlocks correctly on phones.
- Added a native responsive phone layout based on the established public
  Archive presentation: stacked panels, horizontal destination catalogue,
  readable navigation, responsive address glyphs and mobile maintenance dialogs.

## 1.5.4

- The About header now displays the installed Stellar Archive version.
- The maintenance heading and both software groups now explicitly identify all
  managed entries as Matelv-x software and add-ons.

## 1.5.3

- Added a prominent add-on operation window with Download, Verify, Install and
  Complete stages, live status messages and visible failure reporting.
- Added a post-operation restart choice and automatic reconnection status.
- The restart endpoint is restricted to the exact systemd service detected for
  the installed application root, preventing SG2 maintenance from restarting a
  colocated public SG1 service.
- Add-on tasks now publish structured phase and progress information.

## 1.5.2

- Fixed add-on actions on SG1_v4 by passing the JSON body already parsed by the
  web server instead of attempting to read the request stream a second time.
- Corrected Dynamic Wormhole detection to match its installed active manager
  and pattern-manager implementation.
- Removed Visual Volume Meter from the installable catalogue because it is a
  standard component of the SG1_v4 image.

## 1.5.1

- Fixed update, uninstall and add-on maintenance POST requests in Safari and
  embedded WebViews which omit both `Origin` and `Referer` on a same-origin
  request.
- Added a dedicated `X-Stellar-Archive-Request` header and a JSON-content
  compatibility fallback. Explicit foreign origins remain rejected and the
  local server does not grant cross-origin preflight requests.

## 1.5.0

- Replaced the flat maintenance area with expandable `INSTALLATIONS` and
  `MATELV-X ADD-ONS` sections.
- Added an installable public add-on catalogue. `INSTALL` remains locked until
  the user opens that add-on's repository with the adjacent information button.
- Blocked installation unless the verified remote maintenance contract declares
  both an installer and an uninstall procedure.
- Added Aquila Symbol Patch, DHD LED Test, Dynamic Wormhole and Visual Volume
  Meter to the managed public catalogue.
- Replaced Alarm Clock's legacy full-tree rollback with a bounded surgical
  uninstall so later add-ons are not removed.

## 1.4.0

- Added a universal About-panel manager for installed `matelv-x` SG1 add-ons.
- Detects add-ons by their real files and repository identity on SG1_v3 and
  SG1_v4 instead of using a device-specific list.
- Added verified update actions and, where safe, surgical uninstall actions for
  ten public add-ons.
- Requires the repository's maintenance contract before running any downloaded
  installer and suppresses service restarts during web-managed operations.
- Supports private `matelv-x` add-ons when their installed checkout contains the
  same contract and the Pi already has GitHub access; no credentials are stored.
- Initially disabled automatic Alarm Clock uninstall because its legacy rollback
  restored the whole SG1 tree and could erase later add-ons.
- Added exact preservation and restoration of manager metadata on Archive
  uninstall.

## 1.3.1

- Fixed installation when an existing root-owned `classes/__pycache__` blocks
  bytecode output. Python sources are now compiled entirely in memory.
- Added exact recovery for a ***-style installation interrupted during
  the 1.3.0 validation step.

## 1.3.0

- Added one automatic installer for SG1_v3 and SG1_v4.
- Added a dependency-free SG1_v3 web and dialing bridge.
- Preserved all SG1_v4 Original, optional Retro, Both and Stand-alone modes.
- Added About controls for verified GitHub updates and safe uninstall.
- Required a matching SHA-256 release asset before automatic installation.
- Added same-origin protection and asynchronous maintenance tasks.
- Added exact pre-install restoration for the v3 bridge and v4 API extension.
- Retained the Gaia differential-rotation visual and responsive layout from
  the accepted v1.2.8 SG1_v4 build.
