"""« Remettre la carte à zéro » : après des essais de firmware, une carte
peut rester en trois à cinq partitions illisibles pour un PC -- Windows ne
sait pas la remettre simplement en état de carte de stockage normale
(constaté en usage réel). Efface toute la table de partitions existante
(MBR ou GPT) et recrée une seule partition exFAT occupant toute la carte.

Réutilise les briques déjà en place plutôt que d'en écrire de nouvelles :
`imaging/write_target.py::prepared_write_target` (verrouillage/démontage
par OS, §4.3, identique à `flash_device`/`create_games_partition`) pour
l'écriture, et `imaging/games_partition.py::format_games_partition` (déjà
multiplateforme : `diskutil eraseVolume` / `mkfs.exfat` / PowerShell
`Format-Volume`) pour le formatage natif -- rien de nouveau à maintenir
par OS pour cette dernière étape.

Différent de `games_partition.py` dans son principe : celui-ci *ajoute*
une partition à une table existante (restauration d'une sauvegarde
système sans les jeux) ; celui-ci *remplace* toute la table par une seule
partition neuve -- la planification (« où commence/finit la partition »)
n'a donc pas besoin de lire de table existante, contrairement à `plan_
games_partition_gpt`/`plan_games_partition_mbr`.

Exposé en deux fonctions distinctes (`erase_partition_table`/`create_
single_partition`) plutôt qu'une seule combinée -- bug corrigé, confirmé
sur du vrai matériel : le formatage échouait *silencieusement* (aucune
partition exFAT créée, carte restée brute) parce que Windows n'avait pas
encore repris en compte la nouvelle table au moment où `format_games_
partition` interrogeait `Get-Partition` (pipeline PowerShell vide, jamais
d'erreur levée -- voir aussi le correctif jumeau dans `games_partition.py
::_format_windows`, qui rend cet échec bruyant au lieu de silencieux).
Séparer les étapes permet à l'appelant (`__main__.py::cmd_reset_card`) de
journaliser et de faire progresser une barre par étape réellement
terminée (§2 n°5 : jamais une progression simulée), et donne un point
précis où insérer le délai de reprise en compte côté Windows."""

from __future__ import annotations

import os
import platform
import time
from dataclasses import dataclass

from r36s_studio.devices import Device

from .games_partition import ALIGNMENT_SECTORS, MBR_NTFS_EXFAT_PARTITION_TYPE
from .mbr import PARTITION_ENTRY_SIZE, PARTITION_TABLE_OFFSET, SECTOR_SIZE
from .write_target import prepared_write_target

# Étiquette simple par défaut (§ demande explicite : « permettre de choisir
# l'étiquette du volume, avec une valeur par défaut simple ») -- ni le nom
# d'une console ni un jargon technique, juste ce qu'un PC affichera pour
# une carte SD ordinaire.
DEFAULT_RESET_LABEL = "SDCARD"

# Efface aussi ce nombre de secteurs en fin de disque avant d'écrire la
# nouvelle table -- une éventuelle table GPT secondaire vit en toute fin
# de disque (§4.3, `imaging/system_backup.py`) ; l'effacer ici évite qu'un
# outil qui la retrouverait malgré un MBR neuf en tête (LBA0) ne continue
# de rapporter l'ancien schéma. Même taille que la marge déjà réservée
# ailleurs pour une table GPT secondaire (`ALIGNMENT_SECTORS`, 1 Mio) --
# largement suffisant, une table GPT réelle (en-tête + 128 entrées de
# 128 octets) tenant dans 33 secteurs.
_WIPE_EDGE_SECTORS = ALIGNMENT_SECTORS

# Bug corrigé, confirmé sur du vrai matériel : Windows n'avait pas encore
# repris en compte le MBR tout juste écrit au moment où le formatage
# interrogeait `Get-Partition` -- ce court délai, après le rafraîchissement
# explicite (`IOCTL_DISK_UPDATE_PROPERTIES`, déjà utilisé par `write_
# target.py` pour ce même disque), laisse à Windows le temps de terminer
# cette reprise en compte avant l'étape suivante. `_format_windows`
# (games_partition.py) réessaie en plus plusieurs fois de son côté --
# défense en profondeur, ce délai n'a pas besoin d'être garanti suffisant
# à lui seul.
_WINDOWS_TABLE_REFRESH_DELAY_SECONDS = 1.0


class CardTooSmallForReset(Exception):
    """La carte est trop petite pour qu'une partition exFAT utile tienne
    entre les deux zones effacées en tête et en fin de disque -- une carte
    SD réelle en fait au minimum plusieurs centaines de Mio, ce cas ne
    devrait jamais se produire en pratique (garde-fou, pas un cas attendu)."""


@dataclass
class ResetCardPlan:
    start_lba: int
    end_lba: int  # inclusif

    @property
    def size_bytes(self) -> int:
        return (self.end_lba - self.start_lba + 1) * SECTOR_SIZE


def plan_full_disk_partition(total_sectors: int) -> ResetCardPlan:
    """Une seule partition, alignée (`ALIGNMENT_SECTORS`, même convention
    que `games_partition.py`), occupant tout le disque entre les deux
    zones effacées (§ docstring de module). Lève `CardTooSmallForReset` si
    ça ne laisse pas de place."""
    start_lba = ALIGNMENT_SECTORS
    end_lba = total_sectors - 1 - _WIPE_EDGE_SECTORS
    if end_lba <= start_lba:
        raise CardTooSmallForReset(f"Carte trop petite pour la remettre à zéro ({total_sectors} secteurs).")
    return ResetCardPlan(start_lba=start_lba, end_lba=end_lba)


def build_full_disk_mbr_sector(plan: ResetCardPlan) -> bytes:
    """Construit un secteur MBR neuf (tous les autres octets à zéro,
    aucun code de démarrage) avec une seule entrée de partition -- à la
    différence de `rewrite_mbr_with_games_partition` (`games_partition.py`)
    qui préserve les entrées déjà présentes, ici on repart d'un secteur
    entièrement vide : toute la table précédente est censée disparaître,
    pas seulement gagner une entrée de plus."""
    sector = bytearray(SECTOR_SIZE)
    entry = bytearray(PARTITION_ENTRY_SIZE)
    entry[4] = MBR_NTFS_EXFAT_PARTITION_TYPE
    entry[8:12] = plan.start_lba.to_bytes(4, "little")
    sector_count = plan.end_lba - plan.start_lba + 1
    entry[12:16] = sector_count.to_bytes(4, "little")
    sector[PARTITION_TABLE_OFFSET : PARTITION_TABLE_OFFSET + PARTITION_ENTRY_SIZE] = bytes(entry)
    sector[510:512] = b"\x55\xaa"
    return bytes(sector)


def erase_partition_table(device: Device) -> None:
    """Étape 1/4 (§4.3 bis) : efface (zéros) une marge en tête *et* en fin
    de disque -- une éventuelle signature GPT (« EFI PART », LBA1) ou une
    table secondaire en fin de disque ne doit pas pouvoir resurgir une
    fois le nouveau MBR écrit par `create_single_partition` (étape
    suivante) par-dessus le seul LBA0."""
    total_sectors = device.size_bytes // SECTOR_SIZE
    zero_edge = b"\x00" * (_WIPE_EDGE_SECTORS * SECTOR_SIZE)
    with prepared_write_target(device) as raw_path:
        with open(raw_path, "r+b") as f:
            f.write(zero_edge)
            f.seek((total_sectors - _WIPE_EDGE_SECTORS) * SECTOR_SIZE)
            f.write(zero_edge)
            f.flush()
            os.fsync(f.fileno())


def create_single_partition(device: Device) -> ResetCardPlan:
    """Étape 2/4 : écrit un MBR neuf (`build_full_disk_mbr_sector`) avec
    une unique partition alignée occupant tout l'espace restant.

    Sur Windows uniquement : `prepared_write_target` rafraîchit déjà la
    vue du disque (`winlock.refresh_disk_properties`, `IOCTL_DISK_UPDATE_
    PROPERTIES`) en quittant son bloc `with` -- mais ce rafraîchissement
    ne garantit pas que Windows ait *terminé* de reprendre en compte la
    nouvelle table au moment où l'appelant interroge `Get-Partition`
    juste après (§ docstring de module, bug confirmé sur du vrai
    matériel : formatage silencieusement sans effet). Cette fonction
    attend donc un court instant supplémentaire avant de rendre la main --
    `_format_windows` (games_partition.py) réessaie en plus plusieurs fois
    de son côté, ce délai n'a donc pas besoin d'être garanti suffisant à
    lui seul."""
    total_sectors = device.size_bytes // SECTOR_SIZE
    plan = plan_full_disk_partition(total_sectors)
    with prepared_write_target(device) as raw_path:
        with open(raw_path, "r+b") as f:
            f.write(build_full_disk_mbr_sector(plan))
            f.flush()
            os.fsync(f.fileno())
    if platform.system() == "Windows":
        time.sleep(_WINDOWS_TABLE_REFRESH_DELAY_SECONDS)
    return plan


__all__ = [
    "DEFAULT_RESET_LABEL",
    "CardTooSmallForReset",
    "ResetCardPlan",
    "plan_full_disk_partition",
    "build_full_disk_mbr_sector",
    "erase_partition_table",
    "create_single_partition",
]
