# Changelog

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
- Disabled automatic Alarm Clock uninstall because its legacy rollback restores
  the whole SG1 tree and could erase later add-ons.
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
