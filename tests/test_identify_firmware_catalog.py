from r36s_studio.gui.strings import tr
from r36s_studio.identify.firmware_catalog import FIRMWARE_BY_ID, FIRMWARE_CATALOG, FirmwareEntry


def test_one_entry_per_id_no_duplicates():
    ids = [entry.id for entry in FIRMWARE_CATALOG]
    assert len(ids) == len(set(ids))
    assert FIRMWARE_BY_ID.keys() == set(ids)


def test_exactly_one_clone_safe_entry():
    clone_safe = [entry for entry in FIRMWARE_CATALOG if entry.is_clone_safe]
    assert len(clone_safe) == 1
    assert clone_safe[0].id == "emuelec"


def test_rocknix_is_the_only_automatic_download_entry():
    manual = [entry.id for entry in FIRMWARE_CATALOG if entry.releases_url is not None]
    automatic = [entry.id for entry in FIRMWARE_CATALOG if entry.releases_url is None]
    assert automatic == ["rocknix"]
    assert "rocknix" not in manual


def test_every_entry_has_a_valid_status():
    for entry in FIRMWARE_CATALOG:
        assert entry.status in ("maintained", "archived", "experimental")


def test_arkos_is_archived():
    assert FIRMWARE_BY_ID["arkos"].status == "archived"


def test_every_title_and_desc_key_resolves():
    for entry in FIRMWARE_CATALOG:
        assert tr(entry.title_key)
        assert tr(entry.desc_key)
        assert tr(f"firmware_status_{entry.status}")


def test_firmware_entry_is_frozen():
    entry = FIRMWARE_CATALOG[0]
    try:
        entry.status = "maintained"  # type: ignore[misc]
    except Exception:
        pass
    else:
        raise AssertionError("FirmwareEntry devrait être immuable")


def test_firmware_entry_defaults():
    entry = FirmwareEntry("x", "t", "d", status="experimental")
    assert entry.is_clone_safe is False
    assert entry.releases_url is None
