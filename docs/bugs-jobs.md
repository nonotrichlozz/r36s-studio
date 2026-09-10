# Historique des bugs corrigés — Jobs / firmwares (§4.6 de CLAUDE.md)

> Ce fichier contient l'historique des investigations liées au choix et au
> flash des firmwares tiers (détection de panneau d'écran Android, boot
> Android sur clone RK3326). Le comportement **actuel** est décrit dans
> `CLAUDE.md` §4.6.

---

> **Usage non prévu de `identify --boot-dir`, utile à documenter** : cette
> commande de diagnostic (§4.6, pensée à l'origine pour valider le parseur
> DTB sur des variantes de console) s'est révélée très efficace pour
> trier les `.dtb` d'un dossier `Panels/` extrait -- exécutée sur chacun
> des sept sous-dossiers de panels de cette image R36Droid, elle a écarté
> quatre d'entre eux en identifiant la carte (`board_compatible`) à
> laquelle chaque `.dtb` est réellement destiné (une autre console de la
> même famille RK3326, pas la R36S/R35S) -- ne laissant que les trois
> panels ci-dessus comme candidats plausibles pour cette console, avant
> même de les essayer un par un sur du vrai matériel. Aucun code n'a
> changé pour permettre cet usage : la commande fonctionne déjà sur
> n'importe quel dossier de `.dtb` local, indépendamment de son origine
> (carte réelle ou dossier `Panels/` extrait d'une image).


---

> ⚠️ **Investigation clôturée, confirmée sur du vrai matériel : ce build
> Android/LineageOS (R36Droid/andr36oid) ne démarre pas sur cette console,
> et ce n'est pas une histoire de panel.** Deuxième round de test complet,
> sur une carte différente de celle du round précédent (ci-dessus, 3
> panels compatibles testés) : cette fois, **les huit variantes distinctes
> de `Panels/` compatibles `rockchip,rk3326-rg351mp-linux` (après
> dédoublonnage par timing exact) ont toutes figé** -- écran noir ou allumé
> puis gelé/frisant selon le candidat, jamais un démarrage complet.
>
> **Isolation de la cause, méthodique :**
> 1. Premier piège rencontré pendant ce round : `identify --boot-dir`
>    identifie toujours le **premier `.dtb` par ordre alphabétique** d'un
>    dossier (§4.5) -- sur cette image, c'est `rg351mp-kernel.dtb`/
>    `rg351v-kernel.dtb`, jamais celui que `boot.ini` charge réellement au
>    boot (`load mmc 1:1 ${fdt_addr_r} rk3326-r36s-android.dtb`, vérifié en
>    lisant `boot.ini` directement). Un premier essai basé sur le mauvais
>    fichier n'a donc rien changé au boot réel -- corrigé en cours de route
>    en parsant directement `rk3326-r36s-android.dtb` de chaque dossier
>    (`identify.dtb.parse_dtb_file`, appelable directement sur un fichier
>    précis, pas seulement via `--boot-dir` sur un dossier entier).
> 2. Une fois sur le bon fichier : son `board_compatible` racine ne
>    correspond **jamais** à `rg351mp`/`r36s` -- systématiquement
>    `odroidgo3`, `g80ca`, ou `type3` selon le dossier. Seul le nœud panel
>    (timings d'écran) semble avoir été retouché par variante ; le
>    compatible racine reste celui de la base clonée par le porteur
>    communautaire. Filtrer sur ce champ pour ce fichier précis n'a donc
>    aucun sens ici (contrairement à l'usage habituel de ce module sur un
>    BOOT ArkOS/ROCKNIX, §4.5) -- seul le dédoublonnage par timing exact et
>    le contrôleur d'écran (`elida,kd35t133` vs `sitronix,st7703` pour un
>    seul candidat) restent des signaux valides.
> 3. **Test décisif** : même après avoir restauré le fichier *d'origine*,
>    jamais modifié, la console fige exactement pareil -- et, câble/port
>    USB confirmés fonctionnels (même câble, même port, ROCKNIX sur la même
>    console reconnue instantanément par le PC juste après), **aucun
>    périphérique n'apparaît côté PC** (`adb devices` vide, aucune entrée
>    même en échec dans le Gestionnaire de périphériques Windows) pendant
>    le freeze -- ni avec l'original, ni avec aucun des huit candidats.
>    Le blocage survient donc **avant l'initialisation USB du noyau**,
>    un point commun à toutes les configurations testées, écran compris ou
>    non -- la preuve que le panel n'est pour rien dans ce freeze.
>
> **Conclusion, non résolue plus loin faute de matériel** : ce build
> Android ne s'initialise pas correctement sur ce clone, indépendamment du
> panel choisi. Voir le point précis où ça bloque demanderait une capture
> UART (`boot.ini` route la console noyau sur `ttyS2, 115200n8` -- la seule
> fenêtre sur ce qui se passe avant l'USB), non disponible lors de cette
> investigation. `adb`/USB ne peuvent structurellement rien montrer ici,
> quel que soit le câble : le point de blocage est en amont de leur
> initialisation.
>
> **Implication pour une future automatisation de sélection de panel**
> (idée envisagée à ce moment, jamais implémentée en conséquence) : un tel
> outil (détection automatique d'un dossier `Panels/` au flash, application
> du candidat suivant sans reflasher) n'aurait rien résolu pour ce cas
> précis -- le problème n'est pas le choix du panel. Reste potentiellement
> utile pour un autre build Android qui, lui, initialiserait correctement
> le matériel mais afficherait sur le mauvais écran -- mais ne plus jamais
> le présenter comme la réponse à un simple freeze sans d'abord vérifier,
> comme ici, que la configuration d'origine ne fige pas elle aussi.


---

