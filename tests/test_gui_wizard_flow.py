"""Tests de gui/wizard_flow.py -- séquencement des 7 étapes du mode assisté
(§5 mode assisté), en particulier la reprise après erreur : elle ne doit
jamais refaire une étape déjà réussie."""

from __future__ import annotations

from r36s_studio.gui.wizard_flow import WizardFlow, WizardJob


def test_current_job_starts_at_detect_source():
    flow = WizardFlow()

    assert flow.current_job() == WizardJob.DETECT_SOURCE


def test_marking_a_job_done_advances_to_the_next_one():
    flow = WizardFlow()

    flow.mark_done(WizardJob.DETECT_SOURCE)

    assert flow.current_job() == WizardJob.IDENTIFY


def test_jobs_are_visited_in_the_documented_order():
    flow = WizardFlow()
    seen = []
    while flow.current_job() is not None:
        job = flow.current_job()
        seen.append(job)
        flow.mark_done(job)

    assert seen == [
        WizardJob.DETECT_SOURCE,
        WizardJob.IDENTIFY,
        WizardJob.EXTRACT_BOOT,
        WizardJob.EXTRACT_EASYROMS,
        WizardJob.DETECT_TARGET,
        WizardJob.FLASH,
        WizardJob.INJECT_BOOT,
        WizardJob.EJECT,
    ]


def test_is_finished_only_after_every_job_is_done():
    flow = WizardFlow()
    assert flow.is_finished() is False

    for job in list(WizardJob):
        flow.mark_done(job)

    assert flow.is_finished() is True
    assert flow.current_job() is None


def test_resume_after_extract_boot_succeeds_and_extract_easyroms_fails_only_redoes_easyroms():
    """Scénario exact décrit par l'utilisateur : le BOOT a été copié avec
    succès, EASYROMS a échoué -- reprendre ne doit relancer que EASYROMS,
    jamais recopier le BOOT."""
    flow = WizardFlow()
    flow.mark_done(WizardJob.DETECT_SOURCE)
    flow.mark_done(WizardJob.IDENTIFY)
    flow.mark_done(WizardJob.EXTRACT_BOOT)
    # EXTRACT_EASYROMS a échoué : jamais marqué fait.

    assert flow.current_job() == WizardJob.EXTRACT_EASYROMS
    assert flow.is_done(WizardJob.EXTRACT_BOOT) is True
    assert flow.is_done(WizardJob.EXTRACT_EASYROMS) is False


def test_reset_returns_to_the_first_job():
    flow = WizardFlow()
    flow.mark_done(WizardJob.DETECT_SOURCE)
    flow.mark_done(WizardJob.IDENTIFY)

    flow.reset()

    assert flow.current_job() == WizardJob.DETECT_SOURCE
    assert flow.is_done(WizardJob.IDENTIFY) is False
