"""`RocknixVariantDialog` : consoles de chaque variante et recommandation
R36S, d'après le tableau de la release (`identify/rocknix.py`)."""

from __future__ import annotations

from r36s_studio.gui.screens import RocknixVariantDialog
from r36s_studio.gui.strings import tr
from r36s_studio.identify.rocknix import RocknixAsset


def test_variant_labels_show_consoles_and_r36s_mark_without_preselecting(qapp):
    dialog = RocknixVariantDialog()
    a = RocknixAsset("ROCKNIX-a.img.gz", "", 0, ("Anbernic Rg351m", "Gameconsole R36s"))
    b = RocknixAsset("ROCKNIX-b.img.gz", "", 0, ("Gameconsole Eeclone",))
    bare = RocknixAsset("ROCKNIX-c.img.gz", "", 0)

    dialog.set_variants([(a, None), (b, None), (bare, None)])

    labels = [dialog._list.item(i).text() for i in range(dialog._list.count())]
    assert tr("rocknix_variant_r36s") in labels[0] and "Gameconsole R36s" in labels[0]
    assert tr("rocknix_variant_r36s") not in labels[1] and "Gameconsole Eeclone" in labels[1]
    assert labels[2] == "ROCKNIX-c.img.gz"
    assert not dialog._list.selectedItems()  # jamais de choix à la place de l'utilisateur
