"""Tests de l'orchestration d'écriture (imaging/flash.py). Le périphérique
est simulé par un fichier local et `prepared_write_target` (démontage /
verrouillage par OS, déjà couvert par test_write_target.py) est neutralisé.
Aucun disque réel n'est touché."""

from __future__ import annotations

import contextlib
import gzip
import hashlib
import lzma
from unittest.mock import patch

from r36s_studio.devices import Device
from r36s_studio.imaging import flash
from r36s_studio.imaging.flash import flash_device

FAKE_IMAGE_DATA = b"R36S-fake-disk-image-" * 1000  # 22 000 octets


@contextlib.contextmanager
def _no_prep(device):
    yield device.path


def _make_device(path: str, size_bytes: int) -> Device:
    return Device(
        path=path,
        display="Carte SD factice",
        size_bytes=size_bytes,
        removable=True,
        bus="USB",
        is_system=False,
        mountpoints=[],
    )


def _make_fake_target(tmp_path, size: int) -> str:
    """Un fichier régulier assez grand pour recevoir l'image, faisant office
    de périphérique cible ouvert en "r+b"."""
    path = tmp_path / "fake_target.img"
    path.write_bytes(bytes(size))
    return str(path)


@patch("r36s_studio.imaging.flash.reunmount_before_verify")
@patch("r36s_studio.imaging.flash.prepared_write_target", side_effect=_no_prep)
def test_flash_writes_plain_img_and_verifies(mock_prep, mock_reunmount, tmp_path):
    image_path = tmp_path / "src.img"
    image_path.write_bytes(FAKE_IMAGE_DATA)
    target_path = _make_fake_target(tmp_path, len(FAKE_IMAGE_DATA) + 1000)
    device = _make_device(target_path, len(FAKE_IMAGE_DATA) + 1000)

    result = flash_device(device, str(image_path))

    assert result.bytes_written == len(FAKE_IMAGE_DATA)
    assert result.verified is True
    assert result.source_sha256 == hashlib.sha256(FAKE_IMAGE_DATA).hexdigest()
    assert result.written_sha256 == result.source_sha256

    with open(target_path, "rb") as f:
        assert f.read(len(FAKE_IMAGE_DATA)) == FAKE_IMAGE_DATA


@patch("r36s_studio.imaging.flash.reunmount_before_verify")
@patch("r36s_studio.imaging.flash.prepared_write_target", side_effect=_no_prep)
def test_flash_decompresses_gz_on_the_fly(mock_prep, mock_reunmount, tmp_path):
    image_path = tmp_path / "src.img.gz"
    image_path.write_bytes(gzip.compress(FAKE_IMAGE_DATA))
    target_path = _make_fake_target(tmp_path, len(FAKE_IMAGE_DATA) + 1000)
    device = _make_device(target_path, len(FAKE_IMAGE_DATA) + 1000)

    result = flash_device(device, str(image_path))

    assert result.bytes_written == len(FAKE_IMAGE_DATA)
    assert result.verified is True
    with open(target_path, "rb") as f:
        assert f.read(len(FAKE_IMAGE_DATA)) == FAKE_IMAGE_DATA


@patch("r36s_studio.imaging.flash.reunmount_before_verify")
@patch("r36s_studio.imaging.flash.prepared_write_target", side_effect=_no_prep)
def test_flash_never_writes_beyond_source_length(mock_prep, mock_reunmount, tmp_path):
    """Le reste du fichier cible (au-delà de l'image écrite) doit rester
    inchangé -- le flash ne doit jamais écraser plus que la source."""
    image_path = tmp_path / "src.img"
    image_path.write_bytes(FAKE_IMAGE_DATA)
    extra = 5000
    target_path = _make_fake_target(tmp_path, len(FAKE_IMAGE_DATA) + extra)
    device = _make_device(target_path, len(FAKE_IMAGE_DATA) + extra)

    flash_device(device, str(image_path))

    with open(target_path, "rb") as f:
        f.seek(len(FAKE_IMAGE_DATA))
        tail = f.read()
    assert tail == bytes(extra)  # toujours des zéros, jamais touché


@patch("r36s_studio.imaging.flash.reunmount_before_verify")
@patch("r36s_studio.imaging.flash.prepared_write_target", side_effect=_no_prep)
def test_flash_reports_progress(mock_prep, mock_reunmount, tmp_path):
    image_path = tmp_path / "src.img"
    image_path.write_bytes(FAKE_IMAGE_DATA)
    target_path = _make_fake_target(tmp_path, len(FAKE_IMAGE_DATA) + 1000)
    device = _make_device(target_path, len(FAKE_IMAGE_DATA) + 1000)
    events = []

    flash_device(device, str(image_path), on_progress=events.append, block_size=1024)

    assert events
    assert events[-1].done == len(FAKE_IMAGE_DATA)


# --- bug corrigé : progression fausse lors du flash d'une image .xz -------
#
# Constaté en conditions réelles (ArkOS_R35S-R36S..._MultiPanel.img.xz) : la
# barre affichait 100 % et le temps restant 0 s dès le premier octet écrit.
# Cause : `estimate_total_bytes` renvoyait toujours None pour `.xz`, et
# `copy_range` traite alors la copie comme non bornée en rapportant `done`
# comme `total` -- `done == total` était donc vrai dès le premier événement.
# Corrigé en lisant la taille décompressée dans le pied de l'archive xz
# (`image_source._xz_uncompressed_size`).


@patch("r36s_studio.imaging.flash.reunmount_before_verify")
@patch("r36s_studio.imaging.flash.prepared_write_target", side_effect=_no_prep)
def test_flash_reports_bounded_progress_for_compressed_xz_image(mock_prep, mock_reunmount, tmp_path, monkeypatch):
    image_path = tmp_path / "src.img.xz"
    image_path.write_bytes(lzma.compress(FAKE_IMAGE_DATA))
    target_path = _make_fake_target(tmp_path, len(FAKE_IMAGE_DATA) + 1000)
    device = _make_device(target_path, len(FAKE_IMAGE_DATA) + 1000)
    events = []

    # Force un événement de progression à chaque bloc plutôt que de compter
    # sur le seul événement final garanti : `copy_range` ne rapporte qu'au
    # plus 4 fois par seconde (PROGRESS_INTERVAL), ce qu'une copie aussi
    # rapide qu'un test ne dépasserait jamais autrement.
    clock = {"t": 0.0}

    def fake_monotonic():
        clock["t"] += 1.0
        return clock["t"]

    monkeypatch.setattr("r36s_studio.imaging.copy.time.monotonic", fake_monotonic)

    flash_device(device, str(image_path), on_progress=events.append, block_size=1024)

    expected_total = len(FAKE_IMAGE_DATA)
    assert len(events) > 2  # plusieurs événements, pas seulement le final garanti

    for event in events:
        assert event.total == expected_total  # jamais recalculé en cours de route
        assert 0 <= event.done <= event.total  # jamais plus de 100 %

    # Le tout premier événement ne doit jamais afficher 100 % -- c'était
    # exactement le bug (`done == total` dès le premier octet écrit).
    assert events[0].done < events[0].total

    assert events[-1].done == events[-1].total == expected_total

    # Le temps restant estimé ((total - done) / vitesse) décroît de façon
    # cohérente : le nombre d'octets restants ne remonte jamais.
    remaining = [event.total - event.done for event in events]
    assert remaining == sorted(remaining, reverse=True)
    assert remaining[0] > 0


@patch("r36s_studio.imaging.flash.reunmount_before_verify")
@patch("r36s_studio.imaging.flash.estimate_total_bytes", return_value=None)
@patch("r36s_studio.imaging.flash.prepared_write_target", side_effect=_no_prep)
def test_flash_falls_back_to_device_size_when_total_unreadable(
    mock_prep, mock_estimate, mock_reunmount, tmp_path
):
    """Repli explicite (demandé pour ce correctif) : un pied d'archive non
    standard (`estimate_total_bytes` renvoyant None) ne doit pas faire
    retomber la copie en mode non borné -- la taille du périphérique cible
    sert de total plutôt, pour ne jamais reproduire le bug (barre à 100 %
    dès le premier octet écrit)."""
    image_path = tmp_path / "src.img.xz"
    image_path.write_bytes(lzma.compress(FAKE_IMAGE_DATA))
    target_size = len(FAKE_IMAGE_DATA) + 1000
    target_path = _make_fake_target(tmp_path, target_size)
    device = _make_device(target_path, target_size)
    events = []

    flash_device(device, str(image_path), on_progress=events.append, block_size=1024)

    assert events
    assert events[0].total == target_size


@patch("r36s_studio.imaging.flash.reunmount_before_verify")
@patch("r36s_studio.imaging.flash._hash_stream_range", return_value="hash-invalide")
@patch("r36s_studio.imaging.flash.prepared_write_target", side_effect=_no_prep)
def test_flash_reports_verification_failure_without_raising(mock_prep, mock_hash, mock_reunmount, tmp_path):
    image_path = tmp_path / "src.img"
    image_path.write_bytes(FAKE_IMAGE_DATA)
    target_path = _make_fake_target(tmp_path, len(FAKE_IMAGE_DATA) + 1000)
    device = _make_device(target_path, len(FAKE_IMAGE_DATA) + 1000)

    result = flash_device(device, str(image_path))

    assert result.verified is False
    assert result.written_sha256 == "hash-invalide"
    assert result.source_sha256 != result.written_sha256


@patch("r36s_studio.imaging.flash.reunmount_before_verify")
@patch("r36s_studio.imaging.flash.prepared_write_target", side_effect=_no_prep)
def test_flash_uses_prepared_write_target_with_device(mock_prep, mock_reunmount, tmp_path):
    image_path = tmp_path / "src.img"
    image_path.write_bytes(FAKE_IMAGE_DATA)
    target_path = _make_fake_target(tmp_path, len(FAKE_IMAGE_DATA) + 1000)
    device = _make_device(target_path, len(FAKE_IMAGE_DATA) + 1000)

    flash_device(device, str(image_path))

    mock_prep.assert_called_once_with(device)


# --- bug corrigé : vérification SHA-256 faussée par un remontage macOS ----
#
# Constaté sur du vrai matériel : le flash se déroulait sans erreur, mais
# la vérification SHA-256 échouait quand même. Comparaison octet par octet
# de la source et de la relecture : les 16 premiers Mo étaient identiques,
# la première divergence tombait à l'octet 16 778 216 (juste après le
# début de la première partition), et seuls 3 blocs différaient sur les 22
# premiers Mo -- tous dans la zone FAT de la partition BOOT. Cause :
# `diskutil unmountDisk` (appelé une fois avant l'écriture,
# `prepared_write_target`) ne fait rien pour empêcher macOS de remonter
# automatiquement les partitions juste après l'écriture (le disque porte
# désormais une table de partitions et des systèmes de fichiers valides).
# Une fois montée, la partition BOOT (FAT) reçoit aussitôt des fichiers
# d'index (`.Spotlight-V100`, `.fseventsd`, dates d'accès...) qui modifient
# les octets qu'on s'apprête à relire. Corrigé par deux mesures
# complémentaires : (1) démonter à nouveau (`write_target.
# reunmount_before_verify`) juste avant la relecture, pas seulement une
# fois avant l'écriture ; (2) garder le même descripteur d'écriture ouvert
# entre la fin de l'écriture et la relecture (`_hash_stream_range`,
# `flash_device`) plutôt que de le refermer puis rouvrir le même chemin --
# ça referme la fenêtre de course elle-même, la mesure (1) restant un
# filet de sécurité pour le cas où une partition individuelle se monterait
# indépendamment du périphérique brut.


@patch("r36s_studio.imaging.flash.prepared_write_target", side_effect=_no_prep)
def test_flash_reunmounts_before_verification_read(mock_prep, tmp_path):
    image_path = tmp_path / "src.img"
    image_path.write_bytes(FAKE_IMAGE_DATA)
    target_path = _make_fake_target(tmp_path, len(FAKE_IMAGE_DATA) + 1000)
    device = _make_device(target_path, len(FAKE_IMAGE_DATA) + 1000)

    call_order = []
    real_hash_stream_range = flash._hash_stream_range

    def _tracking_hash_stream_range(stream, num_bytes, chunk_size=flash.HASH_CHUNK_SIZE):
        call_order.append("verify")
        return real_hash_stream_range(stream, num_bytes, chunk_size)

    with patch(
        "r36s_studio.imaging.flash.reunmount_before_verify",
        side_effect=lambda d: call_order.append("reunmount"),
    ) as mock_reunmount, patch(
        "r36s_studio.imaging.flash._hash_stream_range", side_effect=_tracking_hash_stream_range
    ):
        result = flash_device(device, str(image_path))

    mock_reunmount.assert_called_once_with(device)
    # Le démontage doit précéder la relecture -- sinon la fenêtre de
    # remontage automatique n'est pas fermée avant de relire.
    assert call_order == ["reunmount", "verify"]
    assert result.verified is True


@patch("r36s_studio.imaging.flash.reunmount_before_verify")
@patch("r36s_studio.imaging.flash.prepared_write_target", side_effect=_no_prep)
def test_flash_keeps_same_destination_handle_open_across_write_and_verify(
    mock_prep, mock_reunmount, tmp_path
):
    """La relecture de vérification doit réutiliser le même descripteur de
    fichier que l'écriture (`_hash_stream_range` reçoit le flux, pas un
    chemin à rouvrir) -- refermer puis rouvrir laisserait la fenêtre de
    course avec un remontage automatique macOS grande ouverte, même avec
    `reunmount_before_verify` en place."""
    image_path = tmp_path / "src.img"
    image_path.write_bytes(FAKE_IMAGE_DATA)
    target_path = _make_fake_target(tmp_path, len(FAKE_IMAGE_DATA) + 1000)
    device = _make_device(target_path, len(FAKE_IMAGE_DATA) + 1000)

    seen_streams = []
    real_hash_stream_range = flash._hash_stream_range

    def _tracking_hash_stream_range(stream, num_bytes, chunk_size=flash.HASH_CHUNK_SIZE):
        seen_streams.append(stream)
        assert not stream.closed  # toujours ouvert au moment de la relecture
        return real_hash_stream_range(stream, num_bytes, chunk_size)

    open_calls = []
    real_open = open

    def _tracking_open(path, mode="r", *args, **kwargs):
        f = real_open(path, mode, *args, **kwargs)
        # N'importe quel mode compte ici : une régression pourrait tout
        # aussi bien rouvrir en lecture seule ("rb") qu'en "r+b" -- seul
        # le nombre total d'ouvertures du périphérique cible importe.
        if path == target_path:
            open_calls.append(f)
        return f

    with patch("r36s_studio.imaging.flash._hash_stream_range", side_effect=_tracking_hash_stream_range), patch(
        "r36s_studio.imaging.flash.open", side_effect=_tracking_open, create=True
    ):
        flash_device(device, str(image_path))

    # Une seule ouverture du périphérique cible, quel que soit le mode :
    # celle utilisée pour l'écriture est la même que celle passée à la
    # relecture -- jamais refermée puis rouverte entre les deux.
    assert len(open_calls) == 1
    assert seen_streams == [open_calls[0]]


@patch("r36s_studio.imaging.flash.reunmount_before_verify")
@patch("r36s_studio.imaging.flash.prepared_write_target", side_effect=_no_prep)
def test_flash_verification_hash_excludes_data_beyond_written_bytes(mock_prep, mock_reunmount, tmp_path):
    """La relecture de vérification ne doit porter que sur exactement les
    octets écrits (`written`, la taille réelle de la source) -- jamais sur
    l'espace non alloué au-delà, qu'il s'agisse de la fin d'une carte plus
    grande que l'image ou d'un reste d'un flash précédent. Le fichier cible
    est ici pré-rempli de données NON nulles au-delà de la taille de
    l'image : si la relecture dépassait `written`, ce contenu changerait le
    hash et ferait échouer `verified` à tort."""
    image_path = tmp_path / "src.img"
    image_path.write_bytes(FAKE_IMAGE_DATA)
    target_path = tmp_path / "fake_target.img"
    target_path.write_bytes(b"\xff" * (len(FAKE_IMAGE_DATA) + 1000))
    device = _make_device(str(target_path), len(FAKE_IMAGE_DATA) + 1000)

    result = flash_device(device, str(image_path))

    assert result.bytes_written == len(FAKE_IMAGE_DATA)
    assert result.verified is True
    assert result.written_sha256 == hashlib.sha256(FAKE_IMAGE_DATA).hexdigest()
