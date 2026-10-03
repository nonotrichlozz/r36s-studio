# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Pages des releases officielles pour la R36S (§4.6, étape C du mode
expert -- choix du firmware au flash, `identify/firmware_catalog.py`).
Ni dArkOS ni EmuELEC n'ont d'assets attachés de façon exploitable
directement aux releases GitHub (contrairement à ROCKNIX, `identify/
rocknix.py`) -- rien à automatiser au-delà de l'ouverture de la page
dans le navigateur ; l'utilisateur télécharge lui-même, puis choisit le
fichier obtenu."""

from __future__ import annotations

DARKOS_R36S_RELEASES_URL = "https://github.com/southoz/dArkOSRE-R36/releases"

# Consoles clones (`identify/__init__.py::CLONE_DTB_FILENAMES`) : les
# images ArkOS/ROCKNIX standard ne démarrent pas sur ce matériel, EmuELEC
# lui fonctionne (confirmé sur du vrai matériel). Même dépôt officiel du
# projet -- pas de correspondance d'assets par SoC (RK3326) vérifiée à ce
# jour, contrairement à ROCKNIX.
EMUELEC_R36S_RELEASES_URL = "https://github.com/EmuELEC/EmuELEC/releases"

# dArkOSen (djparentx/dArkOSen-R36S), distinct de dArkOS (southoz/
# dArkOSRE-R36) : « dArkOS enhanced », construit à partir de
# dArkOS_RG351MP_trixie. Vérifié sur l'API GitHub le 2026-09-29 : non
# archivé, licence MIT, 8 releases depuis le 2026-07-04 (environ toutes les
# deux semaines, tags MMJJAAAA), dernière `09302026` publiée le 2026-09-29.
# Contrairement à dArkOS, l'image **est** attachée à la release, mais en
# archive 7-Zip découpée en deux (`dArkOSen_R36_<tag>.7z.001` + `.002`,
# ~2,9 Go) contenant un seul `dArkOSen_R36_<tag>.img` de ~8,2 Gio (LZMA2,
# CRC32 de l'image dans l'en-tête de l'archive). GitHub fournit un SHA-256
# par partie (champ `digest` de l'API) ; aucun fichier de sommes publié par
# l'auteur. L'app ne décompresse pas le 7-Zip (`SEVEN_ZIP_ARCHIVE`) : lien
# manuel pour l'instant, l'utilisateur extrait le `.img` lui-même.
# R36 d'origine uniquement (README : incompatible avec tout clone, G80CA et
# « Soy Sauce » compris).
DARKOSEN_R36S_RELEASES_URL = "https://github.com/djparentx/dArkOSen-R36S/releases"
