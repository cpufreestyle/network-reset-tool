# Network Toolbox v4.6.2

## Downloads

- `NetworkToolbox_x64.exe` — Windows 10/11 x64, built with Python 3.13.
- `NetworkToolbox_win7_x86.exe` — Windows 7 x86, built with Python 3.8.
- `NetworkToolbox_win7_x64.exe` — Windows 7 x64, built with Python 3.8.

All executables include the administrator manifest. Windows 7 users must download the asset matching their system architecture; do not use the Python 3.13 build on Windows 7.

## SHA256

| Asset | SHA256 |
|---|---|
| `NetworkToolbox_x64.exe` | `375AD72BDB866DE04C06F6BF377FC8BBA5DC561862CC5382FDC61B66F89F6F67` |
| `NetworkToolbox_win7_x86.exe` | `5D8489AA27DF24DB47D8555C0EE4D6D969959B074EC66AB4D39474B3705B2BDD` |
| `NetworkToolbox_win7_x64.exe` | `563AD9B55DD7CADB984A604B7426BC3FA1087E6CF648E17408CF1F1A9BA452F1` |

## Changes

- Add dedicated Python 3.8 builds for Windows 7 x86 and x64 compatibility.
- Use English executable names for release assets to avoid filename encoding issues.
- Update README download links and checksums.
- Preserve silent subprocess execution and faster network diagnostics from v4.6.1.

## Validation

- `python tests/smoke_test.py`: 413 passed.
- x64 Windows 10/11 and Win7 x64 builds verified to include `requireAdministrator` manifest.
