"""Tests de l'orchestration d'écriture (imaging/flash.py). Le périphérique
est simulé par un fichier local et `prepared_write_target` (démontage /
verrouillage par OS, déjà couvert par test_write_target.py) est neutralisé.
Aucun disque réel n'est touché."""

from __future__ import annotations

import contextlib
import gzip
import hashlib
import lzma

import pytest
from unittest.mock import patch

from r36s_studio.devices import Device
from r36s_studio.imaging import flash
from r36s_studio.imaging.flash import flash_device

FAKE_IMAGE_DATA = b"R36S-fake-disk-image-" * 1000  # 21 000 octets
# Sous Windows, le dernier secteur partiel est complété par des zéros
# (écriture brute alignée) : les tests qui regardent juste après l'image
# prennent une image de taille multiple de 512.
SECTOR_ALIGNED_IMAGE = FAKE_IMAGE_DATA[: 41 * 512]


@pytest.fixture(autouse=True)
def _small_deferred_head(monkeypatch):
    """Les images factices font 21 000 octets, bien moins que le début
    d'image écrit en dernier en production (`DEFERRED_HEAD_BYTES`, 1 Mio) :
    sans réduction, tout tiendrait dans ce début et le corps de la copie
    (progression, annulation...) ne serait jamais exercé. 1 024 octets :
    multiple de 512, comme en production."""
    monkeypatch.setattr(flash, "DEFERRED_HEAD_BYTES", 1024)


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
@patch("r36s_studio.imaging.flash._hash_written_body", return_value=hashlib.sha256(b"hash-invalide"))
@patch("r36s_studio.imaging.flash.prepared_write_target", side_effect=_no_prep)
def test_flash_reports_verification_failure_without_raising(mock_prep, mock_hash, mock_reunmount, tmp_path):
    image_path = tmp_path / "src.img"
    image_path.write_bytes(FAKE_IMAGE_DATA)
    target_path = _make_fake_target(tmp_path, len(FAKE_IMAGE_DATA) + 1000)
    device = _make_device(target_path, len(FAKE_IMAGE_DATA) + 1000)

    result = flash_device(device, str(image_path))

    assert result.verified is False
    assert result.written_sha256 == hashlib.sha256(b"hash-invalide").hexdigest()
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
# entre la fin de l'écriture et la relecture (`_hash_written_body`,
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
    real_hash_written_body = flash._hash_written_body

    def _tracking_hash_written_body(stream, head, body_len):
        call_order.append("verify")
        return real_hash_written_body(stream, head, body_len)

    with patch(
        "r36s_studio.imaging.flash.reunmount_before_verify",
        side_effect=lambda d: call_order.append("reunmount"),
    ) as mock_reunmount, patch(
        "r36s_studio.imaging.flash._hash_written_body", side_effect=_tracking_hash_written_body
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
    fichier que l'écriture (`_hash_written_body` reçoit le flux, pas un
    chemin à rouvrir) -- refermer puis rouvrir laisserait la fenêtre de
    course avec un remontage automatique macOS grande ouverte, même avec
    `reunmount_before_verify` en place."""
    image_path = tmp_path / "src.img"
    image_path.write_bytes(FAKE_IMAGE_DATA)
    target_path = _make_fake_target(tmp_path, len(FAKE_IMAGE_DATA) + 1000)
    device = _make_device(target_path, len(FAKE_IMAGE_DATA) + 1000)

    seen_streams = []
    real_hash_written_body = flash._hash_written_body

    def _tracking_hash_written_body(stream, head, body_len):
        seen_streams.append(stream)
        assert not stream.closed  # toujours ouvert au moment de la relecture
        return real_hash_written_body(stream, head, body_len)

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

    with patch("r36s_studio.imaging.flash._hash_written_body", side_effect=_tracking_hash_written_body), patch(
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


# --- format invalide : rejeté avant toute préparation de la carte ---------
# Règle §2 n°6 : ne jamais toucher au périphérique (démontage, verrouillage)
# pour une source dont on sait déjà qu'elle est inutilisable.

_SEVEN_ZIP_MAGIC = bytes.fromhex("377ABCAF271C")


@patch("r36s_studio.imaging.flash.reunmount_before_verify")
@patch("r36s_studio.imaging.flash.prepared_write_target", side_effect=_no_prep)
def test_flash_rejects_seven_zip_image_before_touching_device(mock_prep, mock_reunmount, tmp_path):
    from r36s_studio.imaging.image_source import SevenZipArchiveError

    image_path = tmp_path / "ArkOS.img"  # renommé -- détecté par octets d'en-tête, pas l'extension
    image_path.write_bytes(_SEVEN_ZIP_MAGIC + b"\x00" * 20)
    target_path = _make_fake_target(tmp_path, 1000)
    device = _make_device(target_path, 1000)

    try:
        flash_device(device, str(image_path))
        assert False, "SevenZipArchiveError attendue"
    except SevenZipArchiveError:
        pass

    mock_prep.assert_not_called()


@patch("r36s_studio.imaging.flash.reunmount_before_verify")
@patch("r36s_studio.imaging.flash.prepared_write_target", side_effect=_no_prep)
def test_flash_rejects_unsupported_format_before_touching_device(mock_prep, mock_reunmount, tmp_path):
    from r36s_studio.imaging.image_source import UnsupportedImageFormatError

    image_path = tmp_path / "src.img.zip"
    image_path.write_bytes(b"PK\x03\x04" + b"\x00" * 20)
    target_path = _make_fake_target(tmp_path, 1000)
    device = _make_device(target_path, 1000)

    try:
        flash_device(device, str(image_path))
        assert False, "UnsupportedImageFormatError attendue"
    except UnsupportedImageFormatError:
        pass

    mock_prep.assert_not_called()


# --- `[Errno 9] Bad file descriptor` sous Windows -------------------------
#
# Cause identifiée sur du vrai matériel (11/10/2026, ROCKNIX-RK3326 sur une
# carte de 32 Go vidée par `diskpart clean`) : échec après 160 Mo écrits, et
# aussitôt deux NOUVEAUX lecteurs (« ROCKNIX (D:) », « Disque amovible
# (E:) ») dans l'Explorateur -- Windows avait découvert et monté les
# partitions de l'image en cours d'écriture, parce que sa table de
# partitions (début de l'image) était écrite en premier. Corrigé en écrivant
# ce début en tout dernier (`flash._write_deferred_head`) -- correctif à
# confirmer sur du vrai matériel.


@patch("r36s_studio.imaging.flash.reunmount_before_verify")
@patch("r36s_studio.imaging.flash.prepared_write_target", side_effect=_no_prep)
def test_flash_writes_partition_table_region_last(mock_prep, mock_reunmount, tmp_path):
    """Au moment d'écrire le début de l'image, tout le reste est déjà en
    place et le début de la carte porte toujours son ancien contenu."""
    image_path = tmp_path / "src.img"
    image_path.write_bytes(FAKE_IMAGE_DATA)
    target_path = tmp_path / "fake_target.img"
    target_path.write_bytes(b"\xff" * (len(FAKE_IMAGE_DATA) + 1000))
    device = _make_device(str(target_path), len(FAKE_IMAGE_DATA) + 1000)

    snapshots = []
    real_write_head = flash._write_deferred_head

    def _tracking_write_head(destination, head, sector_size):
        destination.flush()
        with open(target_path, "rb") as f:
            snapshots.append(f.read(len(FAKE_IMAGE_DATA)))
        return real_write_head(destination, head, sector_size)

    with patch("r36s_studio.imaging.flash._write_deferred_head", side_effect=_tracking_write_head):
        result = flash_device(device, str(image_path))

    assert len(snapshots) == 1
    before_head = snapshots[0]
    assert before_head[:1024] == b"\xff" * 1024  # ancienne table toujours là
    assert before_head[1024:] == FAKE_IMAGE_DATA[1024:]  # tout le reste déjà écrit
    assert result.verified is True
    with open(target_path, "rb") as f:
        assert f.read(len(FAKE_IMAGE_DATA)) == FAKE_IMAGE_DATA


@patch("r36s_studio.imaging.flash.reunmount_before_verify")
@patch("r36s_studio.imaging.flash.prepared_write_target", side_effect=_no_prep)
def test_flash_cancelled_mid_copy_never_writes_new_partition_table(mock_prep, mock_reunmount, tmp_path):
    from r36s_studio.imaging.copy import OperationCancelled

    image_path = tmp_path / "src.img"
    image_path.write_bytes(FAKE_IMAGE_DATA)
    target_path = tmp_path / "fake_target.img"
    target_path.write_bytes(b"\xff" * (len(FAKE_IMAGE_DATA) + 1000))
    device = _make_device(str(target_path), len(FAKE_IMAGE_DATA) + 1000)
    calls = {"n": 0}

    def _cancel_after_two_blocks():
        calls["n"] += 1
        return calls["n"] > 2

    with pytest.raises(OperationCancelled):
        flash_device(device, str(image_path), block_size=1024, should_cancel=_cancel_after_two_blocks)

    with open(target_path, "rb") as f:
        assert f.read(1024) == b"\xff" * 1024


# --- bug corrigé : partition de stockage ROCKNIX jamais agrandie -----------
#
# Confirmé sur du vrai matériel (R36S, ROCKNIX 20261001, carte de test ayant
# déjà porté ArkOS et d'autres systèmes) : `fs-resize.log` -> « Can't have
# overlapping partitions », stockage resté à 32 Mo, écran noir après le
# logo. Une table GPT de secours laissée en fin de carte par un ancien
# système survivait au flash. Corrigé en remettant la fin de la carte à
# zéro (`flash._wipe_stale_tail`).


@patch("r36s_studio.imaging.flash.reunmount_before_verify")
@patch("r36s_studio.imaging.flash.prepared_write_target", side_effect=_no_prep)
def test_flash_wipes_stale_data_at_end_of_card(mock_prep, mock_reunmount, tmp_path, monkeypatch):
    monkeypatch.setattr(flash, "TAIL_WIPE_BYTES", 4096)
    image_path = tmp_path / "src.img"
    image_path.write_bytes(SECTOR_ALIGNED_IMAGE)
    size = 64 * 1024
    target_path = tmp_path / "fake_target.img"
    target_path.write_bytes(b"\xee" * size)  # « ancienne table GPT de secours »
    device = _make_device(str(target_path), size)

    result = flash_device(device, str(image_path))

    data = target_path.read_bytes()
    assert result.verified is True
    assert data[: len(SECTOR_ALIGNED_IMAGE)] == SECTOR_ALIGNED_IMAGE
    assert data[size - 4096 :] == bytes(4096)  # fin de carte remise à zéro
    # Entre la fin de l'image et la zone remise à zéro : jamais touché.
    assert data[len(SECTOR_ALIGNED_IMAGE) : size - 4096] == b"\xee" * (size - 4096 - len(SECTOR_ALIGNED_IMAGE))


@patch("r36s_studio.imaging.flash.reunmount_before_verify")
@patch("r36s_studio.imaging.flash.prepared_write_target", side_effect=_no_prep)
def test_flash_never_wipes_tail_overlapping_the_image(mock_prep, mock_reunmount, tmp_path, monkeypatch):
    """Carte à peine plus grande que l'image : la zone de fin chevaucherait
    l'image -- on n'y touche pas plutôt que d'abîmer ce qu'on vient
    d'écrire."""
    monkeypatch.setattr(flash, "TAIL_WIPE_BYTES", 4096)
    image_path = tmp_path / "src.img"
    image_path.write_bytes(SECTOR_ALIGNED_IMAGE)
    size = len(SECTOR_ALIGNED_IMAGE) + 1000
    target_path = tmp_path / "fake_target.img"
    target_path.write_bytes(b"\xee" * size)
    device = _make_device(str(target_path), size)

    result = flash_device(device, str(image_path))

    data = target_path.read_bytes()
    assert result.verified is True
    assert data[: len(SECTOR_ALIGNED_IMAGE)] == SECTOR_ALIGNED_IMAGE
    assert data[len(SECTOR_ALIGNED_IMAGE) :] == b"\xee" * 1000


@patch("r36s_studio.imaging.flash.reunmount_before_verify")
@patch("r36s_studio.imaging.flash.prepared_write_target", side_effect=_no_prep)
def test_flash_warns_but_succeeds_when_tail_wipe_fails(mock_prep, mock_reunmount, tmp_path, monkeypatch):
    monkeypatch.setattr(flash, "TAIL_WIPE_BYTES", 4096)
    image_path = tmp_path / "src.img"
    image_path.write_bytes(FAKE_IMAGE_DATA)
    size = 64 * 1024
    target_path = _make_fake_target(tmp_path, size)
    device = _make_device(target_path, size)
    warnings = []

    with patch("r36s_studio.imaging.flash._wipe_stale_tail", return_value=False):
        result = flash_device(device, str(image_path), on_warning=warnings.append)

    assert result.verified is True
    assert any("fin de la carte" in w for w in warnings)


# --- bug corrigé : « vérification échouée » après un flash Windows réussi --
#
# Constaté sur du vrai matériel (11/10/2026) : écriture complète, puis
# empreinte relue différente. Windows avait monté la partition ROCKNIX dès
# la table écrite et y avait créé `System Volume Information` pendant la
# relecture (`KERNEL` intact, md5 conforme). Corrigé en relisant le corps
# AVANT d'écrire la table (`flash._hash_written_body`), puis seulement le
# début de la carte après (`flash._read_back_head`).


@patch("r36s_studio.imaging.flash.reunmount_before_verify")
@patch("r36s_studio.imaging.flash.prepared_write_target", side_effect=_no_prep)
def test_flash_verification_ignores_os_writes_after_partition_table_appears(mock_prep, mock_reunmount, tmp_path):
    """Ce que le système écrit dans une partition une fois la table posée
    (dossier d'indexation) ne doit pas faire échouer la vérification."""
    image_path = tmp_path / "src.img"
    image_path.write_bytes(FAKE_IMAGE_DATA)
    target_path = _make_fake_target(tmp_path, len(FAKE_IMAGE_DATA) + 1000)
    device = _make_device(target_path, len(FAKE_IMAGE_DATA) + 1000)
    real_write_head = flash._write_deferred_head

    def _write_head_then_os_indexes(destination, head, sector_size):
        real_write_head(destination, head, sector_size)
        # « Windows monte la partition et y crée System Volume Information »
        destination.seek(5000)
        destination.write(b"System Volume Information")
        destination.flush()

    with patch("r36s_studio.imaging.flash._write_deferred_head", side_effect=_write_head_then_os_indexes):
        result = flash_device(device, str(image_path))

    assert result.verified is True


@patch("r36s_studio.imaging.flash.reunmount_before_verify")
@patch("r36s_studio.imaging.flash.prepared_write_target", side_effect=_no_prep)
def test_flash_detects_corrupted_body(mock_prep, mock_reunmount, tmp_path):
    """La relecture du corps reste une vraie vérification : un octet
    différent sur la carte AVANT l'écriture de la table est détecté."""
    image_path = tmp_path / "src.img"
    image_path.write_bytes(FAKE_IMAGE_DATA)
    target_path = _make_fake_target(tmp_path, len(FAKE_IMAGE_DATA) + 1000)
    device = _make_device(target_path, len(FAKE_IMAGE_DATA) + 1000)
    real_hash_body = flash._hash_written_body

    def _corrupt_then_hash(destination, head, body_len):
        destination.seek(3000)
        destination.write(b"\x00\x01\x02")
        destination.flush()
        return real_hash_body(destination, head, body_len)

    with patch("r36s_studio.imaging.flash._hash_written_body", side_effect=_corrupt_then_hash):
        result = flash_device(device, str(image_path))

    assert result.verified is False


@patch("r36s_studio.imaging.flash.reunmount_before_verify")
@patch("r36s_studio.imaging.flash.prepared_write_target", side_effect=_no_prep)
def test_flash_detects_wrong_partition_table_read_back(mock_prep, mock_reunmount, tmp_path):
    image_path = tmp_path / "src.img"
    image_path.write_bytes(FAKE_IMAGE_DATA)
    target_path = _make_fake_target(tmp_path, len(FAKE_IMAGE_DATA) + 1000)
    device = _make_device(target_path, len(FAKE_IMAGE_DATA) + 1000)

    with patch("r36s_studio.imaging.flash._read_back_head", return_value=b"\x00" * 1024):
        result = flash_device(device, str(image_path))

    assert result.verified is False


@patch("r36s_studio.imaging.flash.time.sleep")
@patch("r36s_studio.imaging.flash.reunmount_before_verify")
@patch("r36s_studio.imaging.flash.prepared_write_target", side_effect=_no_prep)
def test_flash_rereads_head_on_fresh_handle_if_write_handle_revoked(mock_prep, mock_reunmount, mock_sleep, tmp_path):
    """Windows peut révoquer la poignée d'écriture dès que la nouvelle table
    apparaît : le début de la carte est alors relu sur une poignée neuve."""
    image_path = tmp_path / "src.img"
    image_path.write_bytes(FAKE_IMAGE_DATA)
    target_path = _make_fake_target(tmp_path, len(FAKE_IMAGE_DATA) + 1000)
    device = _make_device(target_path, len(FAKE_IMAGE_DATA) + 1000)
    real_write_head = flash._write_deferred_head

    class _RevokedAfterHead:
        def __init__(self, inner):
            self._inner = inner
            self.revoked = False

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def seek(self, *args):
            if self.revoked:
                raise OSError(9, "Bad file descriptor")
            return self._inner.seek(*args)

    holder = {}

    def _write_head_then_revoke(destination, head, sector_size):
        real_write_head(destination, head, sector_size)
        holder["wrapped"].revoked = True

    real_hash_body = flash._hash_written_body

    def _wrap_handle(destination, head, body_len):
        holder["wrapped"] = _RevokedAfterHead(destination)
        return real_hash_body(destination, head, body_len)

    real_read_back = flash._read_back_head

    def _read_back_through_wrapper(destination, dev, length):
        return real_read_back(holder["wrapped"], dev, length)

    with patch("r36s_studio.imaging.flash._hash_written_body", side_effect=_wrap_handle), patch(
        "r36s_studio.imaging.flash._write_deferred_head", side_effect=_write_head_then_revoke
    ), patch("r36s_studio.imaging.flash._read_back_head", side_effect=_read_back_through_wrapper):
        result = flash_device(device, str(image_path))

    mock_sleep.assert_called_once_with(flash.WINDOWS_REMOUNT_SETTLE_SECONDS)
    assert result.verified is True
