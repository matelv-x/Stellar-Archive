# Changelog

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
