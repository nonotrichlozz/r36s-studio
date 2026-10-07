"""Tests de PartitionJobRunner (gui/partition_runner.py) : traduction des
exceptions de `partitions/jobs.py` en signaux Qt. `inject_boot`/`copy_games`
sont mockés — aucune partition réelle n'est touchée. `run()` est appelé
directement (jamais `.start()`) pour exécuter la logique de façon
synchrone, sans vrai threading, comme le fait déjà `gui/worker_runner.py`
côté worker élevé."""

from __future__ import annotations

from unittest.mock import patch

from r36s_studio.devices import Device
from r36s_studio.gui.partition_runner import PartitionJobRunner, SystemBackupEstimateRunner
from r36s_studio.imaging.copy import OperationCancelled, ProgressEvent
from r36s_studio.imaging.system_backup import GamesPartitionNotFound
from r36s_studio.partitions import (
    MacosNtfsWriteUnsupported,
    MountpointNotWritable,
    PartitionNotFound,
    PartitionNotMounted,
)
from r36s_studio.partitions.locate import PartitionInfo


def _make_device(path="/dev/fake-disk-test-4") -> Device:
    return Device(
        path=path,
        display="Carte SD factice",
        size_bytes=32_000_000_000,
        removable=True,
        bus="USB",
        is_system=False,
        mountpoints=[],
    )


@patch("r36s_studio.gui.partition_runner.inject_boot")
def test_inject_boot_success_emits_finished_true(mock_inject, qapp):
    runner = PartitionJobRunner("inject_boot", _make_device(), "/tmp/boot_backup")
    finished_events = []
    runner.finished_job.connect(lambda ok: finished_events.append(ok))

    runner.run()

    mock_inject.assert_called_once()
    assert mock_inject.call_args.args[:2] == (runner._device, "/tmp/boot_backup")
    assert finished_events == [True]


@patch("r36s_studio.gui.partition_runner.extract_boot", return_value=10)
def test_extract_boot_success_calls_extract_boot(mock_extract, qapp):
    runner = PartitionJobRunner("extract_boot", _make_device(), "/tmp/R36S Studio/BOOT_x")
    finished_events = []
    runner.finished_job.connect(lambda ok: finished_events.append(ok))

    runner.run()

    mock_extract.assert_called_once()
    assert mock_extract.call_args.args[:2] == (runner._device, "/tmp/R36S Studio/BOOT_x")
    assert finished_events == [True]


@patch("r36s_studio.gui.partition_runner.extract_easyroms", return_value=10)
def test_extract_easyroms_success_calls_extract_easyroms(mock_extract, qapp):
    runner = PartitionJobRunner("extract_easyroms", _make_device(), "/tmp/R36S Studio/EASYROMS_x")

    runner.run()

    mock_extract.assert_called_once()
    assert mock_extract.call_args.args[:2] == (runner._device, "/tmp/R36S Studio/EASYROMS_x")


@patch("r36s_studio.gui.partition_runner.extract_boot", side_effect=PartitionNotFound("BOOT", "/dev/x"))
def test_extract_boot_partition_not_found_maps_to_dedicated_code(mock_extract, qapp):
    runner = PartitionJobRunner("extract_boot", _make_device(), "/tmp/dest")
    error_events = []
    runner.error.connect(lambda *a: error_events.append(a))

    runner.run()

    assert error_events[0][0] == "PARTITION_NOT_FOUND"


@patch("r36s_studio.gui.partition_runner.copy_games")
def test_copy_games_forwards_progress_events(mock_copy, qapp):
    def _fake_copy(device, source, on_progress=None, should_cancel=None):
        on_progress(ProgressEvent(done=10, total=100, speed=5.0))
        return 10

    mock_copy.side_effect = _fake_copy
    runner = PartitionJobRunner("copy_games", _make_device(), "/tmp/games")
    progress_events = []
    runner.progress.connect(lambda *a: progress_events.append(a))

    runner.run()

    assert progress_events == [(10, 100, 5.0)]


@patch("r36s_studio.gui.partition_runner.copy_games", side_effect=OperationCancelled(2048))
def test_cancellation_emits_cancelled_error(mock_copy, qapp):
    runner = PartitionJobRunner("copy_games", _make_device(), "/tmp/games")
    error_events = []
    finished_events = []
    runner.error.connect(lambda *a: error_events.append(a))
    runner.finished_job.connect(lambda ok: finished_events.append(ok))

    runner.run()

    assert error_events[0][0] == "CANCELLED"
    assert finished_events == [False]


@patch("r36s_studio.gui.partition_runner.copy_games", side_effect=MacosNtfsWriteUnsupported("EASYROMS"))
def test_macos_ntfs_unsupported_maps_to_dedicated_code(mock_copy, qapp):
    runner = PartitionJobRunner("copy_games", _make_device(), "/tmp/games")
    error_events = []
    runner.error.connect(lambda *a: error_events.append(a))

    runner.run()

    assert error_events[0][0] == "EASYROMS_NTFS_MACOS"


@patch(
    "r36s_studio.gui.partition_runner.inject_boot",
    side_effect=PartitionNotFound("BOOT", "/dev/fake-disk-test-4"),
)
def test_partition_not_found_maps_to_dedicated_code(mock_inject, qapp):
    runner = PartitionJobRunner("inject_boot", _make_device(), "/tmp/boot_backup")
    error_events = []
    runner.error.connect(lambda *a: error_events.append(a))

    runner.run()

    assert error_events[0][0] == "PARTITION_NOT_FOUND"


@patch(
    "r36s_studio.gui.partition_runner.inject_boot",
    side_effect=PartitionNotMounted("BOOT", "/dev/fake-disk-test-4"),
)
def test_partition_not_mounted_maps_to_dedicated_code(mock_inject, qapp):
    runner = PartitionJobRunner("inject_boot", _make_device(), "/tmp/boot_backup")
    error_events = []
    runner.error.connect(lambda *a: error_events.append(a))

    runner.run()

    assert error_events[0][0] == "PARTITION_NOT_MOUNTED"


@patch(
    "r36s_studio.gui.partition_runner.copy_games",
    side_effect=MountpointNotWritable("/Volumes/EASYROMS", "boom"),
)
def test_mountpoint_not_writable_maps_to_dedicated_code(mock_copy, qapp):
    runner = PartitionJobRunner("copy_games", _make_device(), "/tmp/games")
    error_events = []
    runner.error.connect(lambda *a: error_events.append(a))

    runner.run()

    assert error_events[0][0] == "MOUNTPOINT_NOT_WRITABLE"


@patch("r36s_studio.gui.partition_runner.copy_games", side_effect=OSError("disk full"))
def test_generic_os_error_maps_to_io_error(mock_copy, qapp):
    runner = PartitionJobRunner("copy_games", _make_device(), "/tmp/games")
    error_events = []
    runner.error.connect(lambda *a: error_events.append(a))

    runner.run()

    assert error_events[0][0] == "IO_ERROR"


@patch("r36s_studio.gui.partition_runner.copy_games")
def test_cancel_sets_should_cancel_flag_passed_to_job(mock_copy, qapp):
    captured = {}

    def _fake_copy(device, source, on_progress=None, should_cancel=None):
        captured["should_cancel"] = should_cancel
        return 0

    mock_copy.side_effect = _fake_copy
    runner = PartitionJobRunner("copy_games", _make_device(), "/tmp/games")

    runner.cancel()
    runner.run()

    assert captured["should_cancel"]() is True


# --- RocknixListRunner ------------------------------------------------------
# Recherche des variantes ROCKNIX disponibles (§5, étape de flash) --
# `resolve_latest_r36s_assets` (identify/rocknix.py) est mocké ici : aucun
# accès réseau réel, comme pour les autres frontières externes de ce module.

from r36s_studio.gui.partition_runner import RocknixDownloadRunner, RocknixListRunner
from r36s_studio.identify.rocknix import (
    ChecksumMismatchError,
    DownloadCancelledError,
    RocknixAsset,
    RocknixAssetNotFoundError,
    RocknixReleaseError,
)

_VARIANT_A = RocknixAsset("ROCKNIX-RK3326.aarch64-20260801-a.img.gz", "https://example.invalid/a", 100)
_VARIANT_B = RocknixAsset("ROCKNIX-RK3326.aarch64-20260801-b.img.gz", "https://example.invalid/b", 200)


@patch("r36s_studio.gui.partition_runner.resolve_latest_r36s_assets")
def test_rocknix_list_runner_forwards_all_variants_unchosen(mock_resolve, qapp):
    mock_resolve.return_value = [(_VARIANT_A, "cafebabe" * 8), (_VARIANT_B, None)]

    runner = RocknixListRunner()
    results = []
    runner.finished_list.connect(lambda variants: results.append(variants))

    runner.run()

    assert results == [[(_VARIANT_A, "cafebabe" * 8), (_VARIANT_B, None)]]


@patch("r36s_studio.gui.partition_runner.resolve_latest_r36s_assets", side_effect=RocknixAssetNotFoundError("aucune image"))
def test_rocknix_list_runner_maps_asset_not_found(mock_resolve, qapp):
    runner = RocknixListRunner()
    errors = []
    results = []
    runner.error.connect(lambda code, msg: errors.append(code))
    runner.finished_list.connect(lambda variants: results.append(variants))

    runner.run()

    assert errors == ["ROCKNIX_ASSET_NOT_FOUND"]
    assert results == [[]]


@patch("r36s_studio.gui.partition_runner.resolve_latest_r36s_assets", side_effect=RocknixReleaseError("réseau indisponible"))
def test_rocknix_list_runner_maps_generic_release_error(mock_resolve, qapp):
    runner = RocknixListRunner()
    errors = []
    results = []
    runner.error.connect(lambda code, msg: errors.append(code))
    runner.finished_list.connect(lambda variants: results.append(variants))

    runner.run()

    assert errors == ["ROCKNIX_DOWNLOAD_FAILED"]
    assert results == [[]]


def test_rocknix_list_runner_cancel_does_not_raise(qapp):
    """Rien à annuler proprement (aller-retour réseau bref) -- ce test
    garantit seulement que le bouton Annuler du journal de bord (§5) ne
    plante jamais s'il est cliqué pendant cette étape."""
    runner = RocknixListRunner()

    runner.cancel()  # ne doit pas lever


# --- RocknixDownloadRunner ---------------------------------------------------
# Téléchargement d'une variante déjà choisie (§5, étape de flash) --
# `download_asset` (identify/rocknix.py) est mocké ici : aucun accès réseau
# réel, comme pour les autres frontières externes de ce module.


@patch("r36s_studio.gui.partition_runner.default_firmware_downloads_dir")
@patch("r36s_studio.gui.partition_runner.download_asset")
def test_rocknix_download_runner_success_emits_progress_and_final_path(mock_download, mock_dir, qapp, tmp_path):
    mock_dir.return_value = tmp_path

    def fake_download(asset_arg, destination, *, expected_sha256, on_progress, should_cancel):
        on_progress(50, 100)
        on_progress(100, 100)

    mock_download.side_effect = fake_download

    runner = RocknixDownloadRunner(_VARIANT_A, "cafebabe" * 8)
    progress_events = []
    finished = []
    runner.progress.connect(lambda done, total, speed: progress_events.append((done, total)))
    runner.finished_download.connect(lambda ok, path: finished.append((ok, path)))

    runner.run()

    mock_download.assert_called_once()
    assert mock_download.call_args.args[0] is _VARIANT_A
    assert mock_download.call_args.kwargs["expected_sha256"] == "cafebabe" * 8
    assert (100, 100) in progress_events
    assert finished == [(True, str(tmp_path / _VARIANT_A.name))]


@patch("r36s_studio.gui.partition_runner.default_firmware_downloads_dir")
@patch("r36s_studio.gui.partition_runner.download_asset", side_effect=ChecksumMismatchError("somme invalide"))
def test_rocknix_download_runner_maps_checksum_mismatch(mock_download, mock_dir, qapp, tmp_path):
    mock_dir.return_value = tmp_path

    runner = RocknixDownloadRunner(_VARIANT_A, None)
    errors = []
    finished = []
    runner.error.connect(lambda code, msg: errors.append(code))
    runner.finished_download.connect(lambda ok, path: finished.append((ok, path)))

    runner.run()

    assert errors == ["ROCKNIX_CHECKSUM_MISMATCH"]
    assert finished == [(False, "")]


@patch("r36s_studio.gui.partition_runner.default_firmware_downloads_dir")
@patch("r36s_studio.gui.partition_runner.download_asset", side_effect=RocknixReleaseError("réseau indisponible"))
def test_rocknix_download_runner_maps_generic_release_error(mock_download, mock_dir, qapp, tmp_path):
    mock_dir.return_value = tmp_path

    runner = RocknixDownloadRunner(_VARIANT_A, None)
    errors = []
    finished = []
    runner.error.connect(lambda code, msg: errors.append(code))
    runner.finished_download.connect(lambda ok, path: finished.append((ok, path)))

    runner.run()

    assert errors == ["ROCKNIX_DOWNLOAD_FAILED"]
    assert finished == [(False, "")]


@patch("r36s_studio.gui.partition_runner.default_firmware_downloads_dir")
@patch("r36s_studio.gui.partition_runner.download_asset")
def test_rocknix_download_runner_cancel_passes_should_cancel_and_maps_to_cancelled(mock_download, mock_dir, qapp, tmp_path):
    mock_dir.return_value = tmp_path
    mock_download.side_effect = DownloadCancelledError("annulé après 5 octets")

    runner = RocknixDownloadRunner(_VARIANT_A, None)
    runner.cancel()
    errors = []
    finished = []
    runner.error.connect(lambda code, msg: errors.append(code))
    runner.finished_download.connect(lambda ok, path: finished.append((ok, path)))

    runner.run()

    assert mock_download.call_args.kwargs["should_cancel"]() is True
    assert errors == ["CANCELLED"]
    assert finished == [(False, "")]


# --- SystemBackupEstimateRunner (§4.3, sauvegarde système sans les jeux) --
#
# Calcule la taille estimée (rapide -- quelques secteurs, pas de montage)
# puis tente, en best-effort, d'identifier la console pour suggérer un nom
# de fichier (§4.3 : "quand il est connu") -- un échec d'identification ne
# doit jamais empêcher l'estimation elle-même d'être remontée.


@patch("r36s_studio.gui.partition_runner.unmount_forced")
@patch("r36s_studio.gui.partition_runner.identify_from_boot_directory")
@patch(
    "r36s_studio.gui.partition_runner.locate_mounted",
    return_value=PartitionInfo("/dev/fake-disk-test-6s1", "", "fat16", "/Volumes/BOOT"),
)
@patch("r36s_studio.gui.partition_runner.estimate_system_backup_size_unprivileged", return_value=9_000_000_000)
def test_system_backup_estimate_runner_reports_size_and_board(
    mock_estimate, mock_locate, mock_identify, mock_unmount, qapp
):
    from r36s_studio.identify import IdentifyResult
    from r36s_studio.identify.dtb import DtbInfo

    mock_identify.return_value = IdentifyResult(
        info=DtbInfo(board_compatible="rk3326-r35s", panel_compatible="sitronix,st7703", timings={})
    )
    runner = SystemBackupEstimateRunner("/dev/fake-disk-test-6")
    results = []
    runner.finished_estimate.connect(lambda result: results.append(result))

    runner.run()

    assert len(results) == 1
    result = results[0]
    assert result.size_bytes == 9_000_000_000
    assert result.error is None
    assert result.board_compatible == "rk3326-r35s"
    mock_unmount.assert_called_once_with(mock_locate.return_value)


@patch("r36s_studio.gui.partition_runner.estimate_system_backup_size_unprivileged", side_effect=GamesPartitionNotFound("x"))
def test_system_backup_estimate_runner_reports_games_partition_not_found(mock_estimate, qapp):
    runner = SystemBackupEstimateRunner("/dev/fake-disk-test-6")
    results = []
    runner.finished_estimate.connect(lambda result: results.append(result))

    runner.run()

    assert results[0].error == "GAMES_PARTITION_NOT_FOUND"
    assert results[0].size_bytes is None


def test_system_backup_estimate_runner_games_partition_not_found_keeps_the_real_message(qapp):
    """Bug rapporté : le journal n'affichait que le message générique
    « Une erreur est survenue », sans la cause réelle -- `detail` doit
    porter le message de l'exception d'origine, comme pour toute autre
    opération (§5)."""
    with patch(
        "r36s_studio.gui.partition_runner.estimate_system_backup_size_unprivileged",
        side_effect=GamesPartitionNotFound("Aucune partition de jeux reconnue sur cette carte."),
    ):
        runner = SystemBackupEstimateRunner("/dev/fake-disk-test-6")
        results = []
        runner.finished_estimate.connect(lambda result: results.append(result))

        runner.run()

    assert results[0].detail == "Aucune partition de jeux reconnue sur cette carte."


@patch("r36s_studio.gui.partition_runner.estimate_system_backup_size_unprivileged", side_effect=OSError("carte débranchée"))
def test_system_backup_estimate_runner_reports_io_error(mock_estimate, qapp):
    runner = SystemBackupEstimateRunner("/dev/fake-disk-test-6")
    results = []
    runner.finished_estimate.connect(lambda result: results.append(result))

    runner.run()

    assert results[0].error == "IO_ERROR"
    assert results[0].detail == "carte débranchée"


@patch("r36s_studio.gui.partition_runner.locate_mounted", side_effect=PartitionNotMounted("BOOT", "/dev/x"))
@patch("r36s_studio.gui.partition_runner.estimate_system_backup_size_unprivileged", return_value=9_000_000_000)
def test_system_backup_estimate_runner_size_survives_identify_failure(mock_estimate, mock_locate, qapp):
    """L'identification échoue (carte défaillante, montage impossible...)
    -- purement décorative pour le nom de fichier suggéré, ne doit jamais
    faire perdre l'estimation de taille déjà calculée."""
    runner = SystemBackupEstimateRunner("/dev/fake-disk-test-6")
    results = []
    runner.finished_estimate.connect(lambda result: results.append(result))

    runner.run()

    assert results[0].size_bytes == 9_000_000_000
    assert results[0].error is None
    assert results[0].board_compatible is None


@patch(
    "r36s_studio.gui.partition_runner.locate_mounted",
    return_value=PartitionInfo("/dev/fake-disk-test-6s1", "", "fat16", "/Volumes/BOOT"),
)
@patch("r36s_studio.gui.partition_runner.identify_from_boot_directory")
@patch("r36s_studio.gui.partition_runner.estimate_system_backup_size_unprivileged", return_value=None)
def test_system_backup_estimate_runner_requests_elevation_when_light_estimate_unavailable(
    mock_estimate, mock_identify, mock_locate, qapp
):
    """Bug rapporté : lire la table de partitions brute pour l'estimation
    exige les droits administrateur sur macOS -- quand `list_partitions`
    (non élevé) n'expose pas assez d'information (`estimate_system_
    backup_size_unprivileged` renvoie `None`), le repli est demandé
    plutôt qu'un accès brut tenté directement depuis ce thread."""
    from r36s_studio.identify import IdentifyResult
    from r36s_studio.identify.dtb import DtbInfo

    mock_identify.return_value = IdentifyResult(
        info=DtbInfo(board_compatible="rk3326-r35s", panel_compatible="sitronix,st7703", timings={})
    )
    runner = SystemBackupEstimateRunner("/dev/fake-disk-test-6")
    results = []
    runner.finished_estimate.connect(lambda result: results.append(result))

    runner.run()

    assert results[0].needs_elevation is True
    assert results[0].size_bytes is None
    assert results[0].error is None
    # Déjà tentée à ce stade -- l'appelant n'a pas besoin de la refaire
    # après le repli élevé.
    assert results[0].board_compatible == "rk3326-r35s"


# --- IdentifyRunner : relecture élevée quand l'OS refuse l'accès au BOOT -----


def _boot(mountpoint="I:\\"):
    from r36s_studio.partitions.locate import PartitionInfo

    return PartitionInfo(mountpoint, "", "", mountpoint, partition_type="efi")


def test_identify_runner_uses_the_elevated_reader_when_access_is_denied(qapp):
    from r36s_studio.gui.partition_runner import IdentifyRunner
    from r36s_studio.identify import IdentifyFailureReason, IdentifyResult
    from r36s_studio.identify.dtb import DtbInfo

    denied = IdentifyResult(failure_reason=IdentifyFailureReason.ACCESS_DENIED)
    elevated_result = IdentifyResult(info=DtbInfo(board_compatible="rockchip,rk3326-evb-lp3-v12-linux", panel_compatible=None))
    calls, results = [], []
    runner = IdentifyRunner("/dev/fake-disk-test-9", elevated_identify=lambda boot_dir: calls.append(boot_dir) or elevated_result)
    runner.finished_identify.connect(results.append)

    with patch("r36s_studio.gui.partition_runner.locate_mounted", return_value=_boot()), patch(
        "r36s_studio.gui.partition_runner.identify_from_boot_directory", return_value=denied
    ), patch("r36s_studio.gui.partition_runner.unmount_forced"):
        runner.run()

    assert calls == ["I:\\"]
    assert results == [elevated_result]


def test_identify_runner_without_elevated_reader_reports_access_denied(qapp):
    from r36s_studio.gui.partition_runner import IdentifyRunner
    from r36s_studio.identify import IdentifyFailureReason, IdentifyResult

    denied = IdentifyResult(failure_reason=IdentifyFailureReason.ACCESS_DENIED)
    results = []
    runner = IdentifyRunner("/dev/fake-disk-test-9")
    runner.finished_identify.connect(results.append)

    with patch("r36s_studio.gui.partition_runner.locate_mounted", return_value=_boot()), patch(
        "r36s_studio.gui.partition_runner.identify_from_boot_directory", return_value=denied
    ), patch("r36s_studio.gui.partition_runner.unmount_forced"):
        runner.run()

    assert results == [denied]
