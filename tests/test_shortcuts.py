"""Raccourcis web personnels (`r36s_studio/shortcuts.py`) : liste livrée
vide, fichier de l'utilisateur hors dépôt, seuls les liens https gardés."""

from __future__ import annotations

import json
import re

from r36s_studio import shortcuts


def test_shipped_list_is_empty_and_the_file_is_absent_by_default():
    assert not shortcuts.shortcuts_path().exists()
    assert shortcuts.load_shortcuts() == []


def test_only_https_links_with_a_short_name_are_kept(tmp_path):
    path = tmp_path / "raccourcis.json"
    path.write_text(
        json.dumps(
            [
                {"nom": "  Mon   tableau ", "url": "https://exemple.org/a"},
                {"nom": "En clair", "url": "http://exemple.org"},
                {"nom": "Script", "url": "javascript:alert(1)"},
                {"nom": "Fichier", "url": "file:///etc/passwd"},
                {"nom": "", "url": "https://exemple.org/b"},
                {"nom": "x" * 61, "url": "https://exemple.org/c"},
                "pas un objet",
            ]
        ),
        encoding="utf-8",
    )
    assert shortcuts.load_shortcuts(path) == [shortcuts.Shortcut("Mon tableau", "https://exemple.org/a")]


def test_unreadable_file_gives_an_empty_list_and_the_list_is_capped(tmp_path):
    path = tmp_path / "raccourcis.json"
    path.write_text("{pas du json", encoding="utf-8")
    assert shortcuts.load_shortcuts(path) == []
    path.write_text(json.dumps([{"nom": f"n{i}", "url": f"https://e.org/{i}"} for i in range(50)]), encoding="utf-8")
    assert len(shortcuts.load_shortcuts(path)) == shortcuts.MAX_SHORTCUTS


def test_no_link_is_hard_coded_in_the_bot_or_the_module():
    from pathlib import Path

    root = Path(shortcuts.__file__).resolve().parent
    for source in [root / "shortcuts.py", *sorted((root / "bot").glob("*.py"))]:
        text = source.read_text(encoding="utf-8")
        hosts = set(re.findall(r"https://([A-Za-z0-9.-]+)", text)) - {"exemple.org", "github.com"}
        assert hosts == set(), source
