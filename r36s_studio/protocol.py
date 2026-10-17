# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Émission d'événements JSON Lines sur stdout — protocole GUI ↔ worker du
brief (§3). Une ligne JSON par événement, pour que la future interface
graphique puisse lire `stdout` ligne par ligne."""

from __future__ import annotations

import json
import sys

_stream = None  # None -> sys.stdout, résolu dynamiquement à chaque emit()


def configure(stream) -> None:
    """Redirige les événements vers `stream` au lieu de stdout. Utilisé par
    le worker élevé (`--progress-file`, voir `gui/elevate.py`) : une fois
    la frontière de privilège franchie (UAC, osascript, pkexec), le
    processus appelant ne peut plus lire le stdout du worker en flux sans
    mécanisme supplémentaire — un fichier partagé est la solution la plus
    simple et portable sur les trois OS."""
    global _stream
    _stream = stream


def emit(event: dict) -> None:
    stream = _stream if _stream is not None else sys.stdout
    stream.write(json.dumps(event, ensure_ascii=False) + "\n")
    stream.flush()


def emit_progress(done: int, total: int, speed: float) -> None:
    emit({"type": "progress", "done": done, "total": total, "speed": round(speed)})


def emit_phase(name: str) -> None:
    """Début d'une nouvelle passe d'une opération qui en a plusieurs
    (`copy`, `verify_source`, `verify_image`, `copy.ProgressEvent.phase`) :
    les événements `progress` qui suivent repartent de 0 pour cette passe
    -- une vraie relecture, jamais une barre simulée (§2 n°5)."""
    emit({"type": "phase", "name": name})


def emit_stalled(seconds: float, limit: float) -> None:
    """La carte source ne renvoie plus rien depuis `seconds` secondes
    (abandon à `limit`, `imaging/source.py::StallWatchedReader`) -- émis
    environ chaque seconde pendant l'attente : la GUI montre qu'on est
    bloqué plutôt qu'une barre figée en silence. Le prochain `progress`
    signifie que les données reviennent."""
    emit({"type": "stalled", "seconds": round(seconds), "limit": round(limit)})


def emit_log(msg: str, level: str = "info") -> None:
    emit({"type": "log", "level": level, "msg": msg})


def emit_error(code: str, msg: str) -> None:
    emit({"type": "error", "code": code, "msg": msg})
    # Toujours aussi sur le vrai stderr du processus, même quand `emit()`
    # est redirigé vers le fichier de progression (`--progress-file`) : si
    # le worker termine en erreur, c'est ce texte que `do shell script`
    # (macOS) construit comme message d'erreur, et ce que `pkexec`/`sudo`
    # (Linux) laissent passer tels quels. Sans ça, une commande annexe
    # (`diskutil unmountDisk`, par exemple) ayant écrit un message anodin
    # sur un flux resté inspecté peut se retrouver prise pour l'erreur —
    # c'est bien l'erreur réelle du worker qui doit apparaître.
    print(f"[{code}] {msg}", file=sys.stderr)


def emit_done(ok: bool) -> None:
    emit({"type": "done", "ok": ok})


def emit_step_progress(step_index: int, step_count: int, step_name: str) -> None:
    """Progression par étapes réelles plutôt que par octets (§2 n°5 :
    jamais une progression simulée) -- pour une opération qui n'a rien à
    copier (« Remettre la carte à zéro », §4.3 bis) mais dont chaque étape
    est un jalon réel (effacement, création, formatage, éjection).
    `step_index` : nombre d'étapes déjà terminées (0 au tout début,
    `step_count` à la toute fin). `step_name` : l'étape EN COURS, affichée
    à la place d'un débit/temps restant qui n'auraient aucun sens ici
    (quelques secondes, non prévisibles)."""
    emit({"type": "step_progress", "step_index": step_index, "step_count": step_count, "step_name": step_name})


def emit_estimate(size_bytes: int) -> None:
    """Résultat d'un calcul de taille élevé (`backup --system-only
    --estimate-only`, §4.3) -- repli quand `partitions/locate.py::
    list_partitions` (non élevé) n'expose pas assez d'information pour
    l'estimer sans lire la table de partitions brute."""
    emit({"type": "estimate", "size_bytes": size_bytes})


def emit_eject_result(ok: bool, msg: str = "") -> None:
    """Résultat d'une éjection chaînée dans un worker élevé qui vient de
    faire autre chose (§5 mode assisté, `cmd_backup --eject-after`) --
    distinct du `log` best-effort déjà utilisé par `cmd_flash --eject-
    after` (§4.6) : là où le flash ne fait jamais échouer sur un échec
    d'éjection (un bonus après une écriture déjà vérifiée), la GUI a ici
    besoin de savoir *précisément* si l'éjection a réussi ou non, pour
    décider d'enchaîner directement sur l'étape suivante du parcours
    guidé ou de retomber sur un worker d'éjection dédié -- sans jamais
    refaire toute la sauvegarde juste pour réessayer l'éjection seule."""
    emit({"type": "eject_result", "ok": ok, "msg": msg})


def emit_post_flash_note(name: str) -> None:
    """Consigne à afficher après un flash, décidée sur la carte écrite
    (`cmd_flash`) -- la GUI la traduit (`main_window._POST_FLASH_NOTE_KEYS`)."""
    emit({"type": "post_flash_note", "name": name})


def emit_identify_result(result: dict) -> None:
    """Résultat d'identification de la console (`identify.result_to_dict`)
    lu par un worker élevé -- Windows, BOOT EFI lisible seulement en
    administrateur (`gui/elevate.py::run_elevated_identify`)."""
    emit({"type": "identify_result", "result": result})


def emit_boot_sets_result(result: dict) -> None:
    """Jeux de fichiers du BOOT et état de la carte (`boot-sets`) -- lu par
    un worker élevé quand le BOOT n'est lisible qu'en administrateur."""
    emit({"type": "boot_sets_result", "result": result})


def emit_drive_letter_result(result: list) -> None:
    """Lettres attribuées aux partitions de jeux par le worker élevé
    (`assign-letter`, Windows) : liste de `AssignedLetter.to_dict()`."""
    emit({"type": "drive_letter_result", "result": result})
