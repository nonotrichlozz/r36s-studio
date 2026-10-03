import io
import json

from r36s_studio import update_check


def test_is_newer_compares_numerically():
    assert update_check.is_newer("v0.10.0", "0.9.1")
    assert not update_check.is_newer("v0.1.0", "0.1.0")
    assert not update_check.is_newer("v0.0.9", "0.1.0")
    assert not update_check.is_newer("nightly", "0.1.0")


def test_fetch_latest_reads_tag_and_notes():
    body = json.dumps({"tag_name": "v1.2.0", "body": "Notes"}).encode()
    assert update_check.fetch_latest(opener=lambda req, timeout: io.BytesIO(body)) == ("v1.2.0", "Notes")


def test_fetch_latest_is_silent_on_network_error():
    def offline(req, timeout):
        raise OSError("hors ligne")

    assert update_check.fetch_latest(opener=offline) is None
