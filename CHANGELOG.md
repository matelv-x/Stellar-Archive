# Changelog

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
