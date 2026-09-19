from __future__ import annotations

from r36s_studio.doublons.extensions import ExtensionKind, classify


def test_manifest_extensions_are_classified_as_manifest():
    for ext in (".cue", ".m3u", ".gdi"):
        assert classify(ext) is ExtensionKind.MANIFEST


def test_bin_is_classified_as_companion_only():
    assert classify(".bin") is ExtensionKind.COMPANION_ONLY


def test_ordinary_rom_extension_is_atomic():
    assert classify(".sfc") is ExtensionKind.ATOMIC
    assert classify(".zip") is ExtensionKind.ATOMIC


def test_unknown_extension_is_unknown():
    assert classify(".txt") is ExtensionKind.UNKNOWN
    assert classify(".png") is ExtensionKind.UNKNOWN


def test_classify_accepts_extension_with_or_without_leading_dot():
    assert classify("sfc") is ExtensionKind.ATOMIC
    assert classify(".sfc") is ExtensionKind.ATOMIC


def test_classify_is_case_insensitive():
    assert classify(".SFC") is ExtensionKind.ATOMIC
    assert classify(".CUE") is ExtensionKind.MANIFEST
