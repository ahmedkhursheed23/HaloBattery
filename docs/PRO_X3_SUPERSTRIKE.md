# Logitech G PRO X3 SUPERSTRIKE support

This feature branch extends HaloBattery's existing Logitech HID++ provider to recognize the Logitech G PRO X3 SUPERSTRIKE on newer HID++ HID collections.

## Changes

- Accept receiver product ID `046D:C54F` alongside the already-known `046D:C54D`.
- For the specific product IDs `C54D`, `C54F`, and `C0A9`, recognize `0xFF43:0x0301` (short HID++ reports) and `0xFF43:0x0302` (long HID++ reports).
- Continue to prefer the existing `0xFF00` interfaces if present.
- Keep unrelated Logitech devices and headset discovery logic unchanged.

## Files

- `providers/logitech.py`: HID collection and receiver detection.
- `tests/test_pro_x3_superstrike.py`: five hardware-free regression tests.

## Testing

A Windows user tested the previously prepared HaloBattery 1.16.0 experimental build with their G PRO X3 SUPERSTRIKE and reported that HaloBattery's battery percentage matched Logitech G HUB. This validates that user's tested setup; it is not a claim of comprehensive compatibility across receivers, connection modes, or other Windows systems.

The tests in this branch are intended to be run from the repository root:

```shell
python -m unittest discover -s tests
```

The GitHub branch itself has not yet been independently run on the user's Windows machine. For deployment, use the project's official Windows PyInstaller build instead of committing an EXE, `_internal`, or precompiled Python runtime to Git.

## Language and icon

HaloBattery already includes the Traditional Chinese locale (`zh_TW`); this branch leaves that existing locale and the original icon unchanged. It is a device compatibility change, not a separate translation patch.

## Upstream

Fork of the HaloBattery project. Keep original copyright notices and the upstream license intact.
