"""Téléchargement du firmware ROCKNIX pour R36S (§5 mode assisté, étape 5,
et étape C du mode expert) — contrairement à dArkOS (`releases.py`), les
images ROCKNIX sont attachées directement aux releases GitHub
(https://github.com/ROCKNIX/distribution/releases) : le téléchargement
automatique est donc possible, avec progression réelle (règle §2 n°5) et
vérification de somme de contrôle quand le dépôt en publie une.

Toute communication réseau passe par un paramètre `opener` injectable
(callable `url -> objet réponse`, même contrat que `urllib.request.urlopen`)
plutôt que d'appeler `urllib.request.urlopen` en dur — comme les autres
frontières externes du projet (`subprocess.run` mocké par
`tests/conftest.py`), pour que les tests ne dépendent jamais d'un accès
réseau réel."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple

ROCKNIX_RELEASES_API_URL = "https://api.github.com/repos/ROCKNIX/distribution/releases/latest"
ROCKNIX_RELEASES_PAGE_URL = "https://github.com/ROCKNIX/distribution/releases"

# RK3326 est le SoC de la R36S -- ROCKNIX publie une image par SoC plutôt
# que par modèle de console, partagée par les consoles de ce SoC. Extensions
# dans l'ordre du plus spécifique au moins spécifique (§4.3, formats source
# acceptés au flash) : `.endswith(".img.gz")` doit être tenté avant
# `.endswith(".img")`, qui matcherait sinon n'importe quel des trois.
_R36S_ASSET_KEYWORD = "rk3326"
_IMAGE_EXTENSIONS = (".img.gz", ".img.xz", ".img.zip", ".img")
_CHECKSUM_EXTENSIONS = (".sha256", ".sha256sum")
_CHECKSUM_SUMS_FILENAMES = ("sha256sum.txt", "sha256sums.txt", "sha256sums", "checksums.txt")

BLOCK_SIZE = 4 * 1024 * 1024  # 4 MiB, même convention que imaging/copy.py


class RocknixReleaseError(Exception):
    """Base des erreurs de ce module -- toujours un message compréhensible
    sans jargon une fois traduit par la GUI (§5 vocabulaire), le détail
    technique (URL, code HTTP...) restant dans le message brut de
    l'exception pour le journal de bord."""


class RocknixAssetNotFoundError(RocknixReleaseError):
    """Aucun asset de la dernière release ne correspond à une image R36S
    (RK3326) exploitable -- changement de nommage côté ROCKNIX, ou release
    ne publiant temporairement que des notes sans binaire."""


class ChecksumMismatchError(RocknixReleaseError):
    """Le fichier téléchargé ne correspond pas à la somme de contrôle
    publiée par le dépôt -- téléchargement corrompu ou interrompu. Le
    fichier partiel est supprimé plutôt que laissé en place (règle §2 n°6 :
    jamais un résultat silencieusement invalide)."""


class DownloadCancelledError(RocknixReleaseError):
    """Levée par `download_asset` quand `should_cancel` répond True --
    bouton Annuler du journal de bord (§5) pendant un téléchargement.
    Fichier partiel supprimé, même principe que `ChecksumMismatchError`."""


@dataclass
class RocknixAsset:
    name: str
    download_url: str
    size_bytes: int


def _default_opener(url: str):
    request = urllib.request.Request(
        url, headers={"User-Agent": "r36s-studio", "Accept": "application/vnd.github+json"}
    )
    return urllib.request.urlopen(request)


Opener = Callable[[str], object]


def select_r36s_asset(assets: List[dict]) -> RocknixAsset:
    """Choisit, parmi les assets JSON d'une release GitHub (chacun avec au
    moins `name`/`browser_download_url`/`size`), celui qui correspond à
    l'image RK3326 (le SoC de la R36S) — jamais un fichier de somme de
    contrôle, même s'il contient aussi "rk3326" dans son nom."""
    for asset in assets:
        name = asset.get("name", "")
        lowered = name.lower()
        if _R36S_ASSET_KEYWORD not in lowered:
            continue
        if not lowered.endswith(_IMAGE_EXTENSIONS):
            continue
        return RocknixAsset(
            name=name,
            download_url=asset.get("browser_download_url", ""),
            size_bytes=int(asset.get("size") or 0),
        )
    raise RocknixAssetNotFoundError(
        "Aucune image RK3326 (R36S) trouvée dans la dernière release ROCKNIX."
    )


def find_checksum_asset(assets: List[dict], image_name: str) -> Optional[dict]:
    """Cherche un asset de somme de contrôle associé à `image_name` :
    soit un fichier dédié (`{image_name}.sha256`), soit un fichier de
    sommes partagé par toute la release (`sha256sum.txt`...). `None` si
    aucun des deux n'existe -- la vérification est alors simplement
    ignorée (téléchargement quand même utilisable, comme pour dArkOS où
    aucune somme n'est jamais fournie)."""
    lowered_image = image_name.lower()
    for asset in assets:
        name = asset.get("name", "")
        if name.lower() == f"{lowered_image}.sha256" or name.lower() == f"{lowered_image}.sha256sum":
            return asset
    for asset in assets:
        if asset.get("name", "").lower() in _CHECKSUM_SUMS_FILENAMES:
            return asset
    return None


def parse_checksum(text: str, filename: str) -> Optional[str]:
    """Extrait la somme sha256 attendue pour `filename` depuis le contenu
    d'un asset de somme de contrôle. Deux formats supportés : une seule
    ligne "hash  nom_de_fichier" (ou plusieurs, un fichier de sommes
    partagé), ou un fichier ne contenant que le hash seul (convention
    `{image}.sha256`, un seul fichier concerné)."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None

    hash_re = re.compile(r"^[0-9a-fA-F]{64}$")

    for line in lines:
        parts = line.split()
        if len(parts) >= 2 and hash_re.match(parts[0]) and parts[-1].lstrip("*") == filename:
            return parts[0].lower()

    if len(lines) == 1:
        candidate = lines[0].split()[0]
        if hash_re.match(candidate):
            return candidate.lower()

    return None


def fetch_latest_release_assets(opener: Opener = _default_opener) -> List[dict]:
    try:
        with opener(ROCKNIX_RELEASES_API_URL) as response:
            raw = response.read()
    except OSError as exc:
        raise RocknixReleaseError(f"Impossible de contacter GitHub : {exc}") from exc

    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise RocknixReleaseError(f"Réponse GitHub illisible : {exc}") from exc

    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise RocknixReleaseError("Réponse GitHub sans liste d'assets.")
    return assets


def resolve_latest_r36s_asset(opener: Opener = _default_opener) -> Tuple[RocknixAsset, Optional[str]]:
    """Combine la recherche de la dernière release, la sélection de
    l'image RK3326, et la somme de contrôle attendue si le dépôt en publie
    une. Retourne `(asset, expected_sha256_ou_None)`."""
    assets = fetch_latest_release_assets(opener)
    asset = select_r36s_asset(assets)

    checksum_asset = find_checksum_asset(assets, asset.name)
    expected_sha256: Optional[str] = None
    if checksum_asset is not None:
        try:
            with opener(checksum_asset["browser_download_url"]) as response:
                text = response.read().decode("utf-8", errors="replace")
        except OSError:
            # Une somme de contrôle illisible ne doit jamais bloquer le
            # téléchargement lui-même (§2 n°5 : progression réelle, pas de
            # blocage sur une fonctionnalité annexe) -- simplement ignorée.
            text = ""
        expected_sha256 = parse_checksum(text, asset.name)

    return asset, expected_sha256


ProgressCallback = Callable[[int, int], None]


CancelCheck = Callable[[], bool]


def download_asset(
    asset: RocknixAsset,
    destination: Path,
    *,
    expected_sha256: Optional[str] = None,
    on_progress: Optional[ProgressCallback] = None,
    opener: Opener = _default_opener,
    block_size: int = BLOCK_SIZE,
    should_cancel: Optional[CancelCheck] = None,
) -> None:
    """Télécharge `asset` vers `destination`, par blocs (même principe que
    `imaging/copy.py`), en calculant la somme sha256 au fil de l'eau.
    Lève `ChecksumMismatchError` (fichier partiel supprimé) si
    `expected_sha256` est fourni et ne correspond pas, ou
    `DownloadCancelledError` (même sort) si `should_cancel` répond True
    avant la fin -- consulté avant chaque bloc, comme
    `imaging/copy.py::copy_range`."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    done = 0
    total = asset.size_bytes

    try:
        with opener(asset.download_url) as response, open(destination, "wb") as out:
            while True:
                if should_cancel is not None and should_cancel():
                    destination.unlink(missing_ok=True)
                    raise DownloadCancelledError(f"Téléchargement annulé après {done} octets.")
                chunk = response.read(block_size)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if on_progress is not None:
                    on_progress(done, total)
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise RocknixReleaseError(f"Échec du téléchargement : {exc}") from exc

    if on_progress is not None:
        on_progress(done, total)  # dernier événement avec le compte final exact (règle §2 n°5)

    if expected_sha256 is not None and digest.hexdigest().lower() != expected_sha256.lower():
        destination.unlink(missing_ok=True)
        raise ChecksumMismatchError(f"Somme de contrôle invalide pour {asset.name}.")


def default_firmware_downloads_dir() -> Path:
    """Emplacement des images ROCKNIX téléchargées automatiquement --
    même principe que `partitions/archives.py::default_archives_dir()`
    (visible, dans les Documents de l'utilisateur, jamais `~/.config`,
    §6), dans un sous-dossier dédié pour ne pas se mélanger aux archives
    BOOT/EASYROMS horodatées."""
    return Path.home() / "Documents" / "R36S Studio" / "Firmwares"


__all__ = [
    "ROCKNIX_RELEASES_API_URL",
    "ROCKNIX_RELEASES_PAGE_URL",
    "RocknixAsset",
    "RocknixReleaseError",
    "RocknixAssetNotFoundError",
    "ChecksumMismatchError",
    "DownloadCancelledError",
    "select_r36s_asset",
    "find_checksum_asset",
    "parse_checksum",
    "fetch_latest_release_assets",
    "resolve_latest_r36s_asset",
    "download_asset",
    "default_firmware_downloads_dir",
]
