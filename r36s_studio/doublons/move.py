# R36S Studio
# Copyright (C) 2026 nonotrichlozz
#
# Ce fichier fait partie de R36S Studio. R36S Studio est un logiciel libre :
# vous pouvez le redistribuer et/ou le modifier selon les termes de la GNU
# General Public License telle que publiée par la Free Software Foundation,
# version 3 de la licence.
#
# R36S Studio est distribué dans l'espoir qu'il sera utile, mais SANS
# AUCUNE GARANTIE ; sans même la garantie implicite de QUALITÉ MARCHANDE ou
# d'ADÉQUATION À UN USAGE PARTICULIER. Consultez la GNU General Public
# License pour plus de détails.
#
# Vous devez avoir reçu une copie de la GNU General Public License avec
# R36S Studio. Si ce n'est pas le cas, consultez <https://www.gnu.org/licenses/>.

"""Déplacement des doublons écartés vers un dossier de destination
(docs/doublons.md) -- **jamais une suppression** : la source n'est
retirée qu'une fois la copie en place déjà vérifiée (même disque ou non).

**Destination configurable** (signalé : « permettre de choisir
l'emplacement... au lieu de _doublons imposé à la racine ») -- `root/
_doublons` reste la proposition par défaut, mais n'importe quel dossier
peut être choisi (`gui/screens.py::DoublonsResultsScreen`, champ
Destination + bouton Changer…). Deux façons de déplacer un fichier selon
que la destination partage le même volume que `root` ou non
(`_is_cross_volume`) :

- **Même disque** -- `shutil.move` (rename, quasi instantané), comme
  avant cette fonctionnalité.
- **Disque différent** -- jamais un simple `shutil.move` (qui retomberait
  silencieusement sur une copie, sans jamais vérifier son intégrité avant
  de supprimer la source) : copie vers un nom temporaire, vérifie la
  taille (et le SHA-256 s'il a déjà été calculé pendant l'analyse,
  `scan.py::Unit.known_sha256`), renomme atomiquement vers le nom final
  *seulement* si la vérification réussit, et ne supprime la source
  qu'après -- une interruption à n'importe quel instant de cette séquence
  laisse soit la source intacte et rien de plus qu'un fichier temporaire
  orphelin (nettoyé au prochain essai), soit la source intacte et une
  copie déjà vérifiée en place (jamais les deux perdus, jamais un fichier
  à moitié écrit au nom final, demandé explicitement).

Garde-fous ajoutés après validation du plan, dans cet ordre, tous avant
le premier octet réellement déplacé :

1. `check_destination_allowed` -- la destination doit être hors du dossier
   analysé, ou exactement `root/_doublons` (ou un sous-dossier de celui-ci)
   -- sinon la prochaine analyse la retrouverait et la reproposerait comme
   doublon (`DestinationInsideRootNotAllowed`) ; jamais la racine d'un
   disque entier (`DestinationIsFilesystemRoot`) ; jamais un dossier en
   lecture seule (`DestinationNotWritable`, sondé sans jamais créer la
   destination elle-même à ce stade -- réutilisé tel quel par la
   validation immédiate du choix « Changer… » côté GUI, avant même
   d'ouvrir la fenêtre de confirmation).
2. Chaque fichier des unités à déplacer doit se trouver sous `root`
   (`DuplicatesOutsideRoot` sinon) -- cette liste ne doit structurellement
   contenir que des fichiers issus du scan de ce même dossier.
3. La destination doit être accessible en écriture pour de vrai
   (`DestinationNotWritable`, sonde réelle, pas seulement les bits de
   permission).
4. L'espace disque disponible *sur le volume de la destination* doit
   couvrir le total à déplacer (`InsufficientDiskSpace`) -- vérifié avant
   de commencer, jamais découvert fichier par fichier en cours de route.

**Mode simulation** (`dry_run=True`) -- mêmes vérifications de
destination, mais aucun fichier déplacé, aucune écriture dans le journal :
rien à annuler puisque rien n'a bougé.

**Journal au fil de l'eau, dans la destination elle-même** (signalé :
« toujours écrit dans le dossier de destination, avec des chemins
absolus ») -- une entrée ajoutée et le fichier `journal.json` réécrit sur
disque immédiatement après *chaque* fichier réellement déplacé, jamais
accumulées en mémoire jusqu'à la fin du lot : une interruption brutale
(crash, coupure) laisse un journal qui reflète exactement ce qui a
réellement été déplacé, exploitable par `undo.undo_all`."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

from .safety import is_filesystem_root
from .scan import DUPLICATES_DIR_NAME, Unit

__all__ = [
    "JOURNAL_FILENAME",
    "MoveProgressCallback",
    "MoveCancelled",
    "DestinationNotWritable",
    "InsufficientDiskSpace",
    "DestinationInsideRootNotAllowed",
    "DestinationIsFilesystemRoot",
    "CopyVerificationFailed",
    "DuplicatesOutsideRoot",
    "default_destination",
    "check_destination_allowed",
    "is_cross_volume_destination",
    "move_duplicates",
    "has_pending_journal_entries",
]

JOURNAL_FILENAME = "journal.json"

MoveProgressCallback = Callable[[int, int], None]  # (fait, total)

_PROBE_FILENAME = ".r36s_studio_doublons_write_test"
_PARTIAL_SUFFIX = ".r36s_studio_doublons_partial"


class MoveCancelled(Exception):
    def __init__(self, files_moved: int):
        super().__init__(f"Déplacement annulé après {files_moved} fichier(s).")
        self.files_moved = files_moved


class DestinationNotWritable(Exception):
    def __init__(self, path: str, reason: str = ""):
        detail = f" ({reason})" if reason else ""
        super().__init__(f"Impossible d'écrire dans « {path} »{detail}.")
        self.path = path


class InsufficientDiskSpace(Exception):
    def __init__(self, path: str, needed_bytes: int, available_bytes: int):
        super().__init__(
            f"Espace insuffisant sur « {path} » : {needed_bytes} octets nécessaires, "
            f"{available_bytes} disponibles."
        )
        self.path = path
        self.needed_bytes = needed_bytes
        self.available_bytes = available_bytes


class DestinationInsideRootNotAllowed(Exception):
    def __init__(self, destination: str, root: str):
        super().__init__(
            f"« {destination} » est à l'intérieur de « {root} » sans être le dossier _doublons par défaut "
            "-- la prochaine analyse le retrouverait."
        )
        self.destination = destination
        self.root = root


class DestinationIsFilesystemRoot(Exception):
    def __init__(self, destination: str):
        super().__init__(f"« {destination} » est la racine d'un disque entier.")
        self.destination = destination


class CopyVerificationFailed(Exception):
    def __init__(self, path: str, reason: str):
        super().__init__(f"Copie de « {path} » non conforme après vérification : {reason}.")
        self.path = path
        self.reason = reason


class DuplicatesOutsideRoot(Exception):
    def __init__(self, path: str, root: str):
        super().__init__(f"« {path} » n'est pas sous « {root} ».")
        self.path = path
        self.root = root


def _nearest_existing_ancestor(path: Path) -> Path:
    """`path` peut ne pas encore exister (destination jamais créée) -- le
    premier ancêtre déjà présent sur le disque est le seul endroit où une
    sonde d'écriture ou un `os.stat` peuvent porter sans effet de bord de
    création. Ne remonte jamais au-delà de la racine du système de
    fichiers (`parent == path` : condition d'arrêt, cas extrême d'un
    chemin déjà entièrement absent jusqu'à la racine)."""
    current = path
    while not current.exists():
        parent = current.parent
        if parent == current:
            break
        current = parent
    return current


def _probe_writable(directory: Path) -> None:
    """Sonde d'écriture réelle (même principe que `partitions/copy.py::
    _check_writable`, non réutilisé directement pour ne pas introduire de
    dépendance vers `partitions/` -- § architecture, l'outil doit rester
    autonome) -- **sans** créer `directory` elle-même si elle n'existe pas
    encore : réutilisée pour la validation immédiate d'un choix de
    destination, avant toute confirmation, qui ne doit jamais avoir
    d'effet de bord de création de dossiers tant que l'utilisateur n'a
    rien confirmé."""
    probe = directory / _PROBE_FILENAME
    try:
        with open(probe, "wb") as handle:
            handle.write(b"\0")
    except OSError as exc:
        raise DestinationNotWritable(str(directory), str(exc)) from exc
    finally:
        try:
            probe.unlink()
        except OSError:
            pass


def _check_writable(directory: Path) -> None:
    """Variante qui crée `directory` (et ses parents) avant de sonder --
    réservée à l'exécution réelle d'un déplacement (`move_duplicates`),
    qui a de toute façon besoin que ce dossier existe pour y écrire des
    fichiers juste après."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DestinationNotWritable(str(directory), str(exc)) from exc
    _probe_writable(directory)


def default_destination(root: str) -> str:
    """`root/_doublons` -- proposition par défaut du champ Destination
    (§ écran de résultats), jamais imposée : l'utilisateur peut la changer
    via « Changer… »."""
    return str(Path(root).resolve() / DUPLICATES_DIR_NAME)


def _is_default_destination_or_inside_it(root_path: Path, destination_path: Path) -> bool:
    default = (root_path / DUPLICATES_DIR_NAME).resolve()
    if destination_path == default:
        return True
    try:
        destination_path.relative_to(default)
        return True
    except ValueError:
        return False


def check_destination_allowed(root: str, destination: str) -> None:
    """Vérifications pures (§ garde-fous demandés, points 1 et 3) --
    aucune écriture ici hormis la sonde d'écriture elle-même (qui ne crée
    jamais la destination), jamais un déplacement. Réutilisée à deux
    endroits : systématiquement par `move_duplicates` (y compris en
    simulation), et par la validation immédiate du choix « Changer… »
    côté GUI, avant même d'ouvrir la fenêtre de confirmation -- un
    dossier refusé doit l'être tout de suite, jamais découvert seulement
    au moment de déplacer pour de vrai."""
    root_path = Path(root).resolve()
    destination_path = Path(destination).resolve()

    if is_filesystem_root(str(destination_path)):
        raise DestinationIsFilesystemRoot(str(destination_path))

    try:
        destination_path.relative_to(root_path)
        inside_root = True
    except ValueError:
        inside_root = False
    if inside_root and not _is_default_destination_or_inside_it(root_path, destination_path):
        raise DestinationInsideRootNotAllowed(str(destination_path), str(root_path))

    _probe_writable(_nearest_existing_ancestor(destination_path))


def _volume_id(path: Path) -> Optional[int]:
    try:
        return os.stat(_nearest_existing_ancestor(path)).st_dev
    except OSError:
        return None


def is_cross_volume_destination(root: str, destination: str) -> bool:
    """`True` seulement si les deux volumes sont *positivement* connus et
    différents -- jamais affirmé sans preuve (même principe que le
    filtrage par appareil de l'outil Android, `android/emulators.py::
    filter_for_device`) : quand l'un des deux ne peut pas être déterminé,
    reste sur le chemin rapide par défaut plutôt que de supposer un
    ralentissement qui n'a pas été prouvé."""
    root_volume = _volume_id(Path(root).resolve())
    destination_volume = _volume_id(Path(destination).resolve())
    if root_volume is None or destination_volume is None:
        return False
    return root_volume != destination_volume


def _check_disk_space(destination_path: Path, needed_bytes: int) -> None:
    ancestor = _nearest_existing_ancestor(destination_path)
    usage = shutil.disk_usage(ancestor)
    if usage.free < needed_bytes:
        raise InsufficientDiskSpace(str(destination_path), needed_bytes, usage.free)


def free_space_at_destination(destination: str) -> Optional[int]:
    """Octets disponibles au premier ancêtre existant de `destination` --
    jamais une exception (`None` si indéterminable) : réservé à
    l'affichage informatif de la fenêtre de confirmation (§ demandé
    explicitement, « espace libre à destination »), jamais à une décision
    qui bloquerait quoi que ce soit -- `move_duplicates`/`_check_disk_
    space` ci-dessus restent seuls habilités à réellement refuser un
    déplacement faute d'espace, au moment de l'exécuter pour de vrai."""
    try:
        ancestor = _nearest_existing_ancestor(Path(destination).resolve())
        return shutil.disk_usage(ancestor).free
    except OSError:
        return None


def _unique_destination(dest: Path) -> Path:
    """`dest` existe déjà (un précédent passage a déjà déplacé un fichier
    au même chemin relatif) -- ajoute un suffixe numérique avant
    l'extension plutôt que d'écraser silencieusement."""
    if not dest.exists():
        return dest
    counter = 2
    while True:
        candidate = dest.with_name(f"{dest.stem}_{counter}{dest.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def _hash_file(path: Path) -> Optional[str]:
    hasher = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
    except OSError:
        return None
    return hasher.hexdigest()


def _move_one_file(member: Path, destination: Path, expected_sha256: Optional[str], cross_volume: bool) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not cross_volume:
        shutil.move(str(member), str(destination))
        return

    # Disque différent (signalé, point 2) : copie vers un nom temporaire,
    # vérifie, renomme atomiquement, *puis seulement* supprime la source.
    temp_destination = destination.with_name(destination.name + _PARTIAL_SUFFIX)
    try:
        shutil.copy2(str(member), str(temp_destination))
        source_size = member.stat().st_size
        copied_size = temp_destination.stat().st_size
        if copied_size != source_size:
            raise CopyVerificationFailed(str(member), f"taille différente après copie ({copied_size} != {source_size})")
        if expected_sha256 is not None:
            digest = _hash_file(temp_destination)
            if digest != expected_sha256:
                raise CopyVerificationFailed(str(member), "SHA-256 différent après copie")
        os.replace(str(temp_destination), str(destination))
    except BaseException:
        # Jamais un fichier temporaire orphelin après un échec -- source
        # toujours intacte à ce stade, rien n'a encore été supprimé.
        try:
            temp_destination.unlink()
        except OSError:
            pass
        raise

    # La copie vérifiée est déjà en place sous son nom final -- seulement
    # maintenant la source peut être retirée sans jamais rien perdre.
    member.unlink()


def _read_journal(journal_path: Path) -> List[dict]:
    try:
        raw = journal_path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        data = json.loads(raw)
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def _write_journal(journal_path: Path, entries: List[dict]) -> None:
    journal_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")


def _append_journal_entry(journal_path: Path, source: str, destination: str) -> None:
    entries = _read_journal(journal_path)
    entries.append(
        {
            "source": source,
            "destination": destination,
            "moved_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    _write_journal(journal_path, entries)


def move_duplicates(
    root: str,
    units: List[Unit],
    dry_run: bool = False,
    on_progress: Optional[MoveProgressCallback] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    destination: Optional[str] = None,
) -> int:
    """Déplace les fichiers de `units` (déjà exclues du/des fichier(s)
    gardé(s) -- construit ainsi par l'appelant, l'écran de résultats) vers
    `destination/<chemin relatif à root>` (un `Unit` entier ou rien,
    jamais un membre isolé d'un groupe lié). `destination=None` retombe
    sur `default_destination(root)` (`root/_doublons`, comportement
    historique). Retourne le nombre de fichiers déplacés (ou qui
    l'auraient été, en simulation)."""
    root_path = Path(root).resolve()
    destination_path = Path(destination).resolve() if destination is not None else root_path / DUPLICATES_DIR_NAME

    check_destination_allowed(root, str(destination_path))

    all_members: List[Path] = [member for unit in units for member in unit.members]
    for member in all_members:
        try:
            member.resolve().relative_to(root_path)
        except ValueError:
            raise DuplicatesOutsideRoot(str(member), str(root_path)) from None

    total = len(all_members)
    cross_volume = is_cross_volume_destination(str(root_path), str(destination_path))

    if dry_run:
        done = 0
        for unit in units:
            if should_cancel is not None and should_cancel():
                raise MoveCancelled(done)
            done += len(unit.members)
            if on_progress is not None:
                on_progress(done, total)
        return done

    total_bytes = sum(unit.total_size_bytes for unit in units)
    _check_writable(destination_path)
    _check_disk_space(destination_path, total_bytes)

    journal_path = destination_path / JOURNAL_FILENAME
    done = 0
    for unit in units:
        if should_cancel is not None and should_cancel():
            raise MoveCancelled(done)
        for member in unit.members:
            relative = member.resolve().relative_to(root_path)
            final_destination = _unique_destination(destination_path / relative)
            expected_sha256 = unit.known_sha256 if member == unit.representative else None
            _move_one_file(member, final_destination, expected_sha256, cross_volume)
            _append_journal_entry(journal_path, str(member), str(final_destination))
            done += 1
            if on_progress is not None:
                on_progress(done, total)
    return done


def has_pending_journal_entries(destinations: List[str]) -> bool:
    """`True` si l'une des destinations connues porte encore au moins une
    entrée de journal -- sert à activer/désactiver le bouton « Tout
    annuler » côté GUI. `destinations` : la destination de la session en
    cours plus l'historique mémorisé (`AppConfig.doublons_recent_
    destinations`, § demandé explicitement : « pour que Tout annuler
    retrouve le journal même si la destination a changé »)."""
    for path in destinations:
        journal_path = Path(path).resolve() / JOURNAL_FILENAME
        if _read_journal(journal_path):
            return True
    return False
