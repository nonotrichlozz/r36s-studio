"""Tests de `consoles_diverses/search_runner.py` -- `rechercher_console`
est mocké au niveau module (même principe que
`tests/test_gui_partition_runner.py::RocknixListRunner`) : aucun accès
réseau réel, et aucune exception ne doit traverser `run()`."""

from __future__ import annotations

from unittest.mock import patch

from r36s_studio.consoles_diverses.client import RechercheErreur, ResultatRecherche
from r36s_studio.consoles_diverses.search_runner import ConsoleSearchRunner


@patch("r36s_studio.consoles_diverses.search_runner.rechercher_console")
def test_search_runner_emits_finished_ok_on_success(mock_rechercher, qapp):
    attendu = ResultatRecherche(statut="aucune_information_trouvee", console=None)
    mock_rechercher.return_value = attendu

    runner = ConsoleSearchRunner("ref", "http://localhost:8787", "cle")
    results = []
    errors = []
    runner.finished_ok.connect(lambda resultat: results.append(resultat))
    runner.error.connect(lambda code, msg: errors.append((code, msg)))

    runner.run()

    assert results == [attendu]
    assert errors == []


@patch("r36s_studio.consoles_diverses.search_runner.rechercher_console")
def test_search_runner_emits_error_on_recherche_erreur(mock_rechercher, qapp):
    mock_rechercher.side_effect = RechercheErreur("serveur_injoignable")

    runner = ConsoleSearchRunner("ref", "http://localhost:8787", "cle")
    results = []
    errors = []
    runner.finished_ok.connect(lambda resultat: results.append(resultat))
    runner.error.connect(lambda code, msg: errors.append((code, msg)))

    runner.run()

    assert results == []
    assert errors == [("serveur_injoignable", "")]


@patch("r36s_studio.consoles_diverses.search_runner.rechercher_console")
def test_search_runner_preserves_server_message_on_error(mock_rechercher, qapp):
    mock_rechercher.side_effect = RechercheErreur("recherche_ia_indisponible", "Réessaie demain.")

    runner = ConsoleSearchRunner("ref", "http://localhost:8787", "cle")
    errors = []
    runner.error.connect(lambda code, msg: errors.append((code, msg)))

    runner.run()

    assert errors == [("recherche_ia_indisponible", "Réessaie demain.")]


@patch("r36s_studio.consoles_diverses.search_runner.rechercher_console")
def test_search_runner_never_lets_an_unexpected_exception_escape(mock_rechercher, qapp):
    mock_rechercher.side_effect = RuntimeError("boum")

    runner = ConsoleSearchRunner("ref", "http://localhost:8787", "cle")
    errors = []
    runner.error.connect(lambda code, msg: errors.append((code, msg)))

    runner.run()  # ne doit lever aucune exception

    assert errors == [("erreur_inattendue", "boum")]


def test_search_runner_passes_custom_opener_through():
    calls = []

    def _opener(request):
        calls.append(request)
        raise AssertionError("ne devrait jamais être vraiment appelé dans ce test")

    with patch("r36s_studio.consoles_diverses.search_runner.rechercher_console") as mock_rechercher:
        mock_rechercher.return_value = ResultatRecherche(statut="aucune_information_trouvee", console=None)
        runner = ConsoleSearchRunner("ref", "http://localhost:8787", "cle", opener=_opener)
        runner.run()

        assert mock_rechercher.call_args.kwargs["opener"] is _opener
