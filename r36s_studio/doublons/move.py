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

import errno
import hashlib
import json
import os
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from r36s_studio.gui import logs as gui_logs

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
    "MoveFileFailed",
    "PartialMoveFailure",
    "FatFileSizeLimitExceeded",
    "default_destination",
    "check_destination_allowed",
    "is_cross_volume_destination",
    "move_duplicates",
    "has_pending_journal_entries",
    "free_space_at_destination",
    "fat_oversized_members",
    "is_fat_filesystem",
    "destination_filesystem_kind",
]

JOURNAL_FILENAME = "journal.json"

MoveProgressCallback = Callable[[int, int], None]  # (fait, total)
# Un fichier en cause, l'étape (copie/vérification/suppression source) --
# `bool` renvoyé indique si l'utilisateur choisit d'ignorer ce fichier et
# de continuer (`True`) ou d'arrêter le lot entier (`False`/callback
# absent), § demandé explicitement : « proposer de continuer en ignorant
# ce fichier ».
MoveFileErrorCallback = Callable[["MoveFileFailed"], bool]

_PROBE_FILENAME = ".r36s_studio_doublons_write_test"
_PARTIAL_SUFFIX = ".r36s_studio_doublons_partial"
# Limite réelle d'un fichier unique sur FAT12/16/32 (champ de taille sur
# 32 bits, 2**32 - 1 octets) -- la même limite s'applique aux trois
# variantes, pas seulement FAT32 (§ demandé explicitement, point 6).
FAT_MAX_FILE_SIZE_BYTES = 2**32 - 1
_FAT_FILESYSTEM_NAMES = {"fat", "fat12", "fat16", "fat32", "vfat", "msdos", "msdosfs"}


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


# Raisons traduites d'un échec système (§ demandé explicitement, point 3 :
# « afficher... la raison traduite »). `REASON_UNKNOWN` reste un repli
# honnête plutôt qu'une fausse précision quand l'erreur ne correspond à
# aucun cas reconnu.
REASON_ACCESS_DENIED = "access_denied"
REASON_READ_ONLY = "read_only"
REASON_PATH_TOO_LONG = "path_too_long"
REASON_DRIVE_REMOVED = "drive_removed"
REASON_INSUFFICIENT_SPACE = "insufficient_space"
REASON_UNKNOWN = "unknown"


class MoveFileFailed(Exception):
    """Échec système réel (accès refusé, disque retiré, espace
    insuffisant...) survenu à une étape précise du déplacement d'un
    fichier précis -- distincte de `CopyVerificationFailed` (le contenu
    copié ne correspond pas à la source, jamais une erreur système).
    Porte tout ce qu'il faut pour un message précis côté GUI (§ demandé
    explicitement, point 3) plutôt qu'un message générique : le fichier
    en cause, l'étape (`step` : `"copy"`, `"verify"`, `"delete_source"`,
    ou `"rename"` pour un déplacement même disque), la raison traduite
    (`reason`, une des constantes `REASON_*` ci-dessus), le message brut
    de l'exception d'origine (`detail`, jamais affiché directement --
    réservé au journal, §5 vocabulaire), et `copy_succeeded` : vrai
    uniquement quand l'échec porte sur la suppression de l'original alors
    que la copie vérifiée est déjà en place à destination (« le dire
    explicitement », § demandé)."""

    def __init__(self, path: str, step: str, reason: str, detail: str, copy_succeeded: bool = False):
        super().__init__(f"Échec ({step}) sur « {path} » : {detail}")
        self.path = path
        self.step = step
        self.reason = reason
        self.detail = detail
        self.copy_succeeded = copy_succeeded
        # Renseigné par `move_duplicates` au moment de la propagation --
        # les `Unit` déjà entièrement déplacées avant cet échec, pour que
        # l'appelant retire du résultat affiché ce qui a réellement
        # bougé sans jamais relancer une analyse complète (§ demandé
        # explicitement, bug corrigé).
        self.moved_units: List[Unit] = []


class PartialMoveFailure(Exception):
    """Le lot s'est terminé après que l'utilisateur a choisi d'ignorer au
    moins un fichier en échec (§ demandé, point 4 : « proposer de
    continuer en ignorant ce fichier ») -- pas un abandon complet, mais
    pas un succès total non plus : porte les unités réellement déplacées
    et celles ignorées (avec leur raison), pour le même traitement
    d'affichage qu'un abandon complet (jamais de nouvelle analyse,
    sélection intacte pour ce qui n'a pas bougé)."""

    def __init__(self, moved_units: List[Unit], skipped: List[Tuple[Unit, "MoveFileFailed"]], moved_count: int):
        super().__init__(f"{moved_count} fichier(s) déplacé(s), {len(skipped)} ignoré(s) après échec.")
        self.moved_units = moved_units
        self.skipped = skipped
        self.moved_count = moved_count


class FatFileSizeLimitExceeded(Exception):
    """Un ou plusieurs fichiers à déplacer dépassent la limite FAT (4 Gio
    par fichier, `FAT_MAX_FILE_SIZE_BYTES`) et la destination est
    positivement identifiée comme FAT -- annoncé *avant* de commencer
    (§ demandé explicitement, point 6), jamais découvert en cours de
    route sur un fichier parmi d'autres."""

    def __init__(self, oversized: List[Tuple[Unit, Path, int]]):
        names = ", ".join(str(path) for _unit, path, _size in oversized)
        super().__init__(f"Dépasse la limite FAT (4 Gio) : {names}.")
        self.oversized = oversized


def _classify_os_error(exc: OSError) -> str:
    """Traduit une `OSError` brute en raison reconnaissable (§ demandé,
    point 3) -- `winerror` (Windows uniquement, absent ailleurs) consulté
    en complément d'`errno`, jamais à sa place : les deux mondes
    n'exposent pas toujours la même information pour la même situation
    réelle. Un cas non reconnu retombe sur `REASON_UNKNOWN` plutôt qu'une
    fausse correspondance -- jamais deviné."""
    winerror = getattr(exc, "winerror", None)
    if exc.errno == errno.ENOSPC or winerror == 112:  # ERROR_DISK_FULL
        return REASON_INSUFFICIENT_SPACE
    if exc.errno == errno.ENAMETOOLONG or winerror == 206:  # ERROR_FILENAME_EXCED_RANGE
        return REASON_PATH_TOO_LONG
    if exc.errno == errno.EROFS:
        return REASON_READ_ONLY
    if exc.errno in (errno.EACCES, errno.EPERM) or winerror == 5:  # ERROR_ACCESS_DENIED
        return REASON_ACCESS_DENIED
    if exc.errno in (errno.EIO, errno.ENODEV, errno.ENXIO) or winerror in (21, 1117):  # ERROR_NOT_READY/IO_DEVICE
        return REASON_DRIVE_REMOVED
    return REASON_UNKNOWN


_LONG_PATH_PREFIX = "\\\\?\\"
_LONG_PATH_UNC_PREFIX = "\\\\?\\UNC\\"


def _long_path_str(path: Path) -> str:
    """Windows uniquement : forme absolue préfixée `\\\\?\\` (accès
    étendu, contourne la limite historique MAX_PATH de 260 caractères) --
    utilisée pour *tous* les appels bas niveau de ce module (§ demandé
    explicitement, point 5 : « gérer les chemins longs... préfixe
    \\\\?\\ »), pas seulement en réaction à un échec déjà survenu -- un
    chemin de jeu R36S dépasse facilement cette limite (dossiers de
    système imbriqués, noms de ROM longs avec tags de région). Sans effet
    sur macOS/Linux, qui n'ont pas cette limite. Un chemin UNC
    (`\\\\serveur\\partage\\...`) prend le préfixe dédié `\\\\?\\UNC\\` --
    la spec Windows ne permet pas de préfixer un UNC avec le préfixe
    simple."""
    if platform.system() != "Windows":
        return str(path)
    resolved = str(path.resolve())
    if resolved.startswith(_LONG_PATH_PREFIX):
        return resolved
    if resolved.startswith("\\\\"):
        return _LONG_PATH_UNC_PREFIX + resolved[2:]
    return _LONG_PATH_PREFIX + resolved


def _path_exists_long(path: Path) -> bool:
    """Équivalent de `Path.exists()`, mais via la forme longue Windows --
    `Path.exists()` seule reste sujette à la même limite MAX_PATH que les
    autres appels bas niveau de ce module."""
    try:
        os.stat(_long_path_str(path))
        return True
    except OSError:
        return False


def _log_move_file_failure(exc: MoveFileFailed) -> None:
    """Consigne l'échec dans `doublons.log` (`gui/logs.py::
    doublons_log_path`, § demandé explicitement, point 2 : « journaliser
    l'exception exacte, l'étape... et le chemin complet du fichier ») --
    best-effort, un journal inaccessible ne doit jamais masquer l'échec
    réel déjà en cours de propagation. Appelé pour *toute* occurrence,
    que l'utilisateur choisisse ensuite d'ignorer ce fichier et de
    continuer, ou que ça interrompe le lot entier."""
    try:
        chemin = gui_logs.doublons_log_path()
        horodatage = datetime.now(timezone.utc).isoformat(timespec="seconds")
        ligne = (
            f"{horodatage} étape={exc.step} raison={exc.reason} "
            f"copie_reussie={exc.copy_succeeded} chemin={exc.path} : {exc.detail}\n"
        )
        with open(chemin, "a", encoding="utf-8") as fichier:
            fichier.write(ligne)
    except OSError:
        pass


def _fail_move_step(path: Path, step: str, exc: OSError, copy_succeeded: bool = False) -> None:
    """Construit, journalise puis lève `MoveFileFailed` -- point de
    passage unique pour ne jamais oublier de journaliser un de ces trois
    cas (copie, vérification, suppression de la source)."""
    failure = MoveFileFailed(str(path), step, _classify_os_error(exc), str(exc), copy_succeeded=copy_succeeded)
    _log_move_file_failure(failure)
    raise failure from exc


def _nearest_existing_ancestor(path: Path) -> Path:
    """`path` peut ne pas encore exister (destination jamais créée) -- le
    premier ancêtre déjà présent sur le disque est le seul endroit où une
    sonde d'écriture ou un `os.stat` peuvent porter sans effet de bord de
    création. Ne remonte jamais au-delà de la racine du système de
    fichiers (`parent == path` : condition d'arrêt, cas extrême d'un
    chemin déjà entièrement absent jusqu'à la racine)."""
    current = path
    while not _path_exists_long(current):
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
    probe_str = _long_path_str(probe)
    try:
        with open(probe_str, "wb") as handle:
            handle.write(b"\0")
    except OSError as exc:
        raise DestinationNotWritable(str(directory), str(exc)) from exc
    finally:
        try:
            os.unlink(probe_str)
        except OSError:
            pass


def _check_writable(directory: Path) -> None:
    """Variante qui crée `directory` (et ses parents) avant de sonder --
    réservée à l'exécution réelle d'un déplacement (`move_duplicates`),
    qui a de toute façon besoin que ce dossier existe pour y écrire des
    fichiers juste après."""
    try:
        os.makedirs(_long_path_str(directory), exist_ok=True)
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
    if not _path_exists_long(dest):
        return dest
    counter = 2
    while True:
        candidate = dest.with_name(f"{dest.stem}_{counter}{dest.suffix}")
        if not _path_exists_long(candidate):
            return candidate
        counter += 1


def _hash_file(path: Path) -> Optional[str]:
    hasher = hashlib.sha256()
    try:
        with open(_long_path_str(path), "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
    except OSError:
        return None
    return hasher.hexdigest()


def _cleanup_partial(temp_destination: Path) -> None:
    """Jamais un fichier temporaire orphelin après un échec -- source
    toujours intacte à ce stade, rien n'a encore été supprimé."""
    try:
        os.unlink(_long_path_str(temp_destination))
    except OSError:
        pass


def _move_one_file(member: Path, destination: Path, expected_sha256: Optional[str], cross_volume: bool) -> None:
    """Trois étapes distinctes côté disque différent (copie, vérification,
    suppression de la source, § demandé explicitement point 3 -- chacune
    journalisée/traduite séparément via `_fail_move_step` en cas
    d'échec) : copie vers un nom temporaire, vérifie, renomme
    atomiquement, *puis seulement* supprime la source."""
    member_str = _long_path_str(member)
    destination_str = _long_path_str(destination)
    try:
        os.makedirs(_long_path_str(destination.parent), exist_ok=True)
    except OSError as exc:
        _fail_move_step(member, "copy", exc)

    if not cross_volume:
        try:
            shutil.move(member_str, destination_str)
        except OSError as exc:
            _fail_move_step(member, "rename", exc)
        return

    temp_destination = destination.with_name(destination.name + _PARTIAL_SUFFIX)
    temp_destination_str = _long_path_str(temp_destination)
    try:
        shutil.copyfile(member_str, temp_destination_str)
    except OSError as exc:
        _cleanup_partial(temp_destination)
        _fail_move_step(member, "copy", exc)

    try:
        shutil.copystat(member_str, temp_destination_str)
    except OSError:
        # § demandé explicitement, point 5 : ignorer un échec de copie
        # des métadonnées (dates, permissions) -- FAT/exFAT ne les
        # supportent pas toutes, et ça ne concerne jamais le contenu déjà
        # copié (vérifié séparément juste après).
        pass

    try:
        source_size = os.stat(member_str).st_size
        copied_size = os.stat(temp_destination_str).st_size
    except OSError as exc:
        _cleanup_partial(temp_destination)
        _fail_move_step(member, "verify", exc)
    if copied_size != source_size:
        _cleanup_partial(temp_destination)
        raise CopyVerificationFailed(str(member), f"taille différente après copie ({copied_size} != {source_size})")
    if expected_sha256 is not None:
        digest = _hash_file(temp_destination)
        if digest != expected_sha256:
            _cleanup_partial(temp_destination)
            raise CopyVerificationFailed(str(member), "SHA-256 différent après copie")

    try:
        os.replace(temp_destination_str, destination_str)
    except OSError as exc:
        _cleanup_partial(temp_destination)
        _fail_move_step(member, "copy", exc)

    # La copie vérifiée est déjà en place sous son nom final -- seulement
    # maintenant la source peut être retirée. Un échec ici ne perd jamais
    # rien (`copy_succeeded=True`, § demandé explicitement : « le dire
    # explicitement ») -- surtout ne pas supprimer la copie déjà vérifiée
    # pour "annuler" cet échec, ça perdrait un fichier pour de vrai.
    try:
        os.unlink(member_str)
    except OSError as exc:
        _fail_move_step(member, "delete_source", exc, copy_succeeded=True)


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


def is_fat_filesystem(kind: Optional[str]) -> bool:
    """`kind` : chaîne brute rendue par `destination_filesystem_kind`
    (`"FAT32"`, `"vfat"`, `"msdos"`...) -- normalisée (casse, espaces)
    avant comparaison à l'ensemble des noms connus pour une famille FAT
    (FAT12/16/32, indifféremment -- la limite de 4 Gio par fichier leur
    est commune, § demandé explicitement point 6). `None`/inconnu :
    jamais affirmé FAT sans preuve positive."""
    if kind is None:
        return False
    return kind.strip().lower() in _FAT_FILESYSTEM_NAMES


def _windows_volume_filesystem(root: str) -> Optional[str]:
    """`root` : racine de volume Windows (`"D:\\\\"`) -- `GetVolumeInformationW`
    (API native, aucun sous-processus) rend directement le nom du système
    de fichiers (`"NTFS"`, `"FAT32"`, `"exFAT"`...). Fonction séparée du
    dispatcher ci-dessous pour rester substituable en test (mêmes
    principes que le point d'injection `opener` de `consoles_diverses/
    client.py` -- `ctypes` n'est pas mockable directement)."""
    import ctypes

    fs_name_buffer = ctypes.create_unicode_buffer(261)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(  # type: ignore[attr-defined]
        ctypes.c_wchar_p(root), None, 0, None, None, None, fs_name_buffer, len(fs_name_buffer)
    )
    if not ok:
        return None
    return fs_name_buffer.value or None


def _posix_mount_filesystem(target: str) -> Optional[str]:
    """macOS/Linux : interroge `mount` (déjà présent nativement sur les
    deux, aucune dépendance supplémentaire) et retient le système de
    fichiers du point de montage correspondant le plus précisément à
    `target` -- le plus long préfixe qui matche, comme pour tout choix de
    point de montage le plus spécifique. `None` si `mount` échoue ou si
    aucune ligne ne correspond -- jamais une exception, jamais une
    supposition. Best-effort : non vérifié sur du vrai matériel macOS/
    Linux à ce jour (même réserve honnête que le reste de ce document
    pour les sondes spécifiques à une plateforme non testée ici)."""
    try:
        result = subprocess.run(["mount"], capture_output=True, text=True, timeout=5, check=False)
    except OSError:
        return None
    if result.returncode != 0:
        return None

    best_match: Optional[str] = None
    best_len = -1
    for line in result.stdout.splitlines():
        if " on " not in line:
            continue
        _source, _, rest = line.partition(" on ")
        mountpoint, _, remainder = rest.partition(" ")
        if not (target == mountpoint or target.startswith(mountpoint.rstrip("/") + "/")):
            continue
        if len(mountpoint) <= best_len:
            continue
        fstype: Optional[str] = None
        remainder = remainder.strip()
        if remainder.startswith("("):
            fstype = remainder.strip("()").split(",")[0].strip()
        elif remainder.startswith("type "):
            fstype = remainder[len("type "):].split(" ")[0]
        if fstype:
            best_match = fstype
            best_len = len(mountpoint)
    return best_match


def destination_filesystem_kind(path: str) -> Optional[str]:
    """Système de fichiers du volume contenant `path` -- utilisé
    uniquement pour détecter une limite FAT (§ demandé explicitement,
    point 6) avant de commencer un déplacement, jamais pour une autre
    décision. `None` si indéterminable (jamais une exception) : dans ce
    cas, l'avertissement FAT est simplement omis plutôt que de bloquer un
    déplacement sur une plateforme où cette sonde échoue."""
    ancestor = _nearest_existing_ancestor(Path(path).resolve())
    try:
        if platform.system() == "Windows":
            drive = os.path.splitdrive(str(ancestor))[0]
            if not drive:
                return None
            return _windows_volume_filesystem(drive + "\\")
        return _posix_mount_filesystem(str(ancestor))
    except OSError:
        return None


def fat_oversized_members(units: List[Unit]) -> List[Tuple[Unit, Path, int]]:
    """Fichiers réellement au-dessus de la limite FAT (§ demandé
    explicitement, point 6) parmi les membres de `units` -- taille lue en
    direct (`os.stat`, jamais `Unit.total_size_bytes`, qui est la *somme*
    des membres d'une unité liée, pas la taille d'un seul fichier -- la
    limite FAT s'applique fichier par fichier). Pure : ne dépend jamais du
    système de fichiers réel de la destination, laissé à l'appelant
    (`is_fat_filesystem`/`destination_filesystem_kind`) -- ne sert donc à
    rien seule, mais reste testable sans dépendre d'une vraie sonde
    système."""
    oversized: List[Tuple[Unit, Path, int]] = []
    for unit in units:
        for member in unit.members:
            try:
                size = os.stat(_long_path_str(member)).st_size
            except OSError:
                continue
            if size > FAT_MAX_FILE_SIZE_BYTES:
                oversized.append((unit, member, size))
    return oversized


def move_duplicates(
    root: str,
    units: List[Unit],
    dry_run: bool = False,
    on_progress: Optional[MoveProgressCallback] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    destination: Optional[str] = None,
    on_file_error: Optional[MoveFileErrorCallback] = None,
) -> int:
    """Déplace les fichiers de `units` (déjà exclues du/des fichier(s)
    gardé(s) -- construit ainsi par l'appelant, l'écran de résultats) vers
    `destination/<chemin relatif à root>` (un `Unit` entier ou rien,
    jamais un membre isolé d'un groupe lié). `destination=None` retombe
    sur `default_destination(root)` (`root/_doublons`, comportement
    historique). Retourne le nombre de fichiers déplacés (ou qui
    l'auraient été, en simulation).

    `on_file_error` (§ demandé explicitement, point 4 : « proposer de
    continuer en ignorant ce fichier ») : appelé avec le `MoveFileFailed`
    en cause dès qu'une étape échoue pour un fichier précis -- un retour
    `True` ignore le reste de l'unité en cours (ses membres déjà déplacés
    le restent, jamais annulés) et poursuit avec la suivante ; `False`
    (ou callback absent) relève l'exception, comme avant ce paramètre.
    Toute interruption (annulation, échec non ignoré, vérification de
    contenu ratée) porte désormais un attribut `moved_units` : les
    `Unit` déjà entièrement déplacées avant l'interruption -- pour que
    l'appelant ne relance jamais une analyse complète après une erreur,
    en retirant seulement ce qui a réellement bougé (§ demandé
    explicitement, bug corrigé)."""
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

    # § demandé explicitement, point 6 : annoncé *avant* de commencer,
    # jamais découvert en cours de route sur un fichier parmi d'autres --
    # `destination_filesystem_kind` best-effort (`None` : sonde
    # indéterminable, jamais bloquant dans ce cas).
    if is_fat_filesystem(destination_filesystem_kind(str(destination_path))):
        oversized = fat_oversized_members(units)
        if oversized:
            raise FatFileSizeLimitExceeded(oversized)

    journal_path = destination_path / JOURNAL_FILENAME
    done = 0
    moved_units: List[Unit] = []
    skipped: List[Tuple[Unit, MoveFileFailed]] = []
    try:
        for unit in units:
            if should_cancel is not None and should_cancel():
                raise MoveCancelled(done)
            try:
                for member in unit.members:
                    relative = member.resolve().relative_to(root_path)
                    final_destination = _unique_destination(destination_path / relative)
                    expected_sha256 = unit.known_sha256 if member == unit.representative else None
                    _move_one_file(member, final_destination, expected_sha256, cross_volume)
                    _append_journal_entry(journal_path, str(member), str(final_destination))
                    done += 1
                    if on_progress is not None:
                        on_progress(done, total)
            except MoveFileFailed as exc:
                if on_file_error is not None and on_file_error(exc):
                    skipped.append((unit, exc))
                    continue
                raise
            else:
                moved_units.append(unit)
    except BaseException as exc:
        # Attaché à *toute* interruption (annulation, échec système non
        # ignoré, échec de vérification de contenu) -- pas seulement
        # `MoveFileFailed` : quelle que soit la cause exacte, l'appelant
        # doit toujours pouvoir retirer ce qui a réellement bougé sans
        # relancer une analyse complète.
        setattr(exc, "moved_units", moved_units)
        raise

    if skipped:
        raise PartialMoveFailure(moved_units, skipped, done)
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
