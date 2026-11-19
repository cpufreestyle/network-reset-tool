# Network Toolbox v4.6.3

## Changes
- Fix update detection: query the GitHub Releases API first, with Gitee as a fallback. Gitee latest was stale at v3.3.1 and incorrectly reported v4.6.1 as current.
- Select the matching asset for Windows 7 x86/x64 and Windows 10/11 x64.
- Accept the new English asset names and GitHub checksum manifest while preserving fail-closed SHA256 verification.

## Downloads
- `NetworkToolbox_x64.exe` — Windows 10/11 x64, Python 3.13.
- `NetworkToolbox_win7_x86.exe` — Windows 7 x86, Python 3.8.
- `NetworkToolbox_win7_x64.exe` — Windows 7 x64, Python 3.8.

See `sha256sums.txt` for SHA256 checksums.

## Validation
- 418 smoke tests pass.
- Live GitHub Release lookup identifies v4.6.2 as an update from v4.6.1.
- Windows 7 x64 asset selection and checksum verification pass against v4.6.2.
