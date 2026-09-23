"""Garde-fou d'empaquetage : tout fichier de données du paquet doit être
déclaré dans chacun des trois spec PyInstaller.

PyInstaller n'embarque que le code Python qu'il découvre par les imports --
jamais un `.json`/`.png` lu à l'exécution. Un fichier oublié ne casse aucun
test lancé depuis les sources, seulement le binaire distribué : c'est
exactement ce qui est arrivé à `doublons/data/extensions.json`, lu à
l'import du module et absent du binaire Windows, qui plantait alors dès le
double-clic (FileNotFoundError)."""

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = PROJECT_ROOT / "r36s_studio"
SPECS = ["r36s_studio.spec", "r36s_studio_windows.spec", "r36s_studio_linux.spec"]

# Fichiers présents dans le paquet mais jamais lus à l'exécution.
_NOT_RUNTIME_DATA = {"CLAUDE.md"}


def _runtime_data_files() -> list[Path]:
    return sorted(
        p
        for p in PACKAGE_DIR.rglob("*")
        if p.is_file()
        and p.suffix not in {".py", ".pyc"}
        and "__pycache__" not in p.parts
        and p.name not in _NOT_RUNTIME_DATA
    )


def test_package_has_runtime_data_files():
    # Si cette liste devenait vide, le test ci-dessous ne vérifierait plus rien.
    assert _runtime_data_files()


@pytest.mark.parametrize("spec_name", SPECS)
def test_every_runtime_data_file_is_declared_in_spec(spec_name):
    spec_text = (PROJECT_ROOT / "packaging" / spec_name).read_text(encoding="utf-8")
    missing = [
        str(p.relative_to(PROJECT_ROOT)) for p in _runtime_data_files() if f'"{p.name}"' not in spec_text
    ]
    assert not missing, f"{spec_name} n'embarque pas : {missing}"
