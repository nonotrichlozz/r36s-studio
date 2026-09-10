# Historique des bugs corrigés — Interface (§5 de CLAUDE.md)

> Ce fichier contient l'historique des investigations et correctifs liés à
> l'interface graphique : refonte de navigation, affichage de la capacité,
> habillage visuel (y compris les animations de la console, ajoutées puis
> entièrement retirées). Le comportement **actuel** est décrit dans
> `CLAUDE.md` §5.

---

> ⚠️ **Refonte de navigation (phase 8)** : l'interface n'était à l'origine
> qu'une succession de six écrans dans un `QStackedWidget` (accueil → choix
> du périphérique → choix du fichier → confirmation → exécution → résultat),
> une étape remplaçant la précédente. Remplacé par une **vue permanente à
> deux colonnes** (`gui/screens.py::MainView`), dont la structure ne change
> jamais, quelle que soit l'opération en cours :
>
> - **Colonne gauche** (`HomeScreen`, largeur fixe ~480 px) : le bandeau de
>   détection, les six étapes A à F, puis la sauvegarde complète sous
>   « Par sécurité » — reste affichée à l'identique en permanence.
> - **Colonne droite** : l'image de la console (`ConsoleArt`) en haut, le
>   journal de bord permanent (`LogPanel`) en bas.
>
> Les choix ponctuels — choix de la carte, choix du fichier/de l'archive,
> confirmation avant écriture, aide macOS — s'ouvrent désormais en
> **fenêtres modales** (`gui/screens.py::Dialog` et ses sous-classes
> `DeviceDialog`/`FileDialog`/`ConfirmDialog`/`HelpDialog`, `QDialog.open()`
> non bloquant plutôt que `exec()`, pour garder le style signal/slot déjà
> utilisé partout ailleurs) **par-dessus** cette vue, jamais en
> remplacement — la structure à deux colonnes reste visible derrière.
> `FileScreen`/`ExecuteScreen`/`ResultScreen` et le `QStackedWidget` qui les
> enchaînait sont supprimés ; leurs rôles sont repris par `FileDialog` et
> par `LogPanel` (progression + résultats, voir plus bas).


---

> ⚠️ **Bug corrigé, signalé sur du vrai matériel : l'app affichait « 31,9
> Go » pour une carte que l'Explorateur Windows affiche « 29,7 Go » --
> même carte, mêmes octets, deux nombres différents. Un utilisateur qui
> compare les deux pouvait croire à une perte de capacité.**
>
> **Cause, plus profonde qu'un simple désaccord avec Windows** : l'app
> calculait déjà la capacité d'une carte de deux façons différentes en
> interne. `gui/screens.py::_format_size` (octets copiés/archivés, ex.
> « 8,4 Go » pour une sauvegarde système) divise par 1024 à chaque palier
> (o -> Ko -> Mo -> Go) -- base 1024, comme l'Explorateur Windows, qui
> fait de même sous une étiquette tout aussi ambiguë. Mais les quatre
> endroits qui affichent la capacité d'une carte *entière* (bandeau de
> détection, liste de `DeviceDialog`, `ConfirmDialog`/`SameCardUnverified
> Dialog`, plus `cmd_list`/`_confirm_flash` côté CLI) divisaient par
> `1_000_000_000` -- base 1000, jamais 1024. Deux conventions
> différentes au sein de la même app, pas seulement un désaccord avec
> Windows.
>
> **Vérifié plutôt que supposé** (demande explicite) ce qu'affichent les
> deux autres OS pour la même carte -- aucun des trois ne fait consensus :
> - **macOS** (Finder) : base 1000 depuis Snow Leopard (10.6, 2009),
>   étiqueté « Go » correctement -- ce que l'app calculait déjà pour la
>   capacité d'une carte (mais pas pour `_format_size`, toujours en base
>   1024 : la même incohérence interne existait donc aussi entre cette
>   fonction-là et macOS, dans l'autre sens).
> - **Linux** : mélangé selon l'outil. GNOME Fichiers (Nautilus) suit la
>   même convention que macOS (base 1000, « Go » correctement étiqueté) ;
>   les outils historiques en ligne de commande (`df`, `lsblk`) utilisent
>   traditionnellement la base 1024 avec un « G » tout aussi ambigu que
>   celui de Windows. Aucune convention unique ne fait consensus sur
>   Linux non plus -- vérifié en connaissance des deux familles d'outils
>   plutôt que jamais testé sur une vraie installation Linux ici (aucune
>   disponible).
>
> **Corrigé** en alignant toute l'app sur une seule et même base --
> celle déjà utilisée par `_format_size`, jamais changée : `gui/screens.py
> ::_capacity_go` et son équivalent local `__main__.py::_capacity_go`
> (dupliqué plutôt qu'importé de `gui/` -- trop petit pour un module
> partagé, et le CLI ne doit pas dépendre de PySide6, §3) remplacent les
> six calculs en base 1000 par `size_bytes / 1024**3`. Plus jamais deux
> nombres différents pour la même carte selon l'écran consulté au sein de
> cette app -- et l'affichage se rapproche au passage de l'Explorateur
> Windows, la plateforme la plus vérifiée sur du vrai matériel dans ce
> projet, au prix d'un désaccord avec le Finder macOS/Nautilus (une carte
> annoncée « 128 Go » par son fabricant s'affichera ici autour de 119 Go,
> comme dans l'Explorateur, plutôt que 128 Go comme dans Finder) --
> aucune option n'évite complètement l'écart avec un OS ou un autre,
> celle-ci l'élimine au moins en interne, et avec la plateforme la plus
> testée ici.
>
> Volontairement **pas** de double affichage (« 31,9 Go / 29,7 Gio ») :
> envisagé, écarté -- introduirait un terme jamais vu par un néophyte
> (« Gio »/GiB) pour un problème que l'utilisateur ne remarque de toute
> façon que s'il compare activement les deux écrans, contraire à la règle
> §5 (aucun jargon technique dans l'interface). Un seul nombre cohérent
> partout dans l'app est plus simple à comprendre qu'une explication de
> la différence entre deux conventions de calcul.


---

> ⚠️ **Piège Qt rencontré en construisant cet habillage** : un `QWidget` nu
> n'honore `background-color` en feuille de style que si l'attribut
> `WA_StyledBackground` est posé — sans lui, le fond ne se peint que par
> accident, quand l'écran a un parent qui le peint à sa place (vrai dans
> `MainWindow`/`QStackedWidget`, faux dès qu'un écran est affiché seul, ex. un
> rendu isolé pour vérification visuelle — confirmé en capturant chaque écran
> en image hors écran, `QWidget.grab()`, avant de constater le fond gris clair
> par défaut du système plutôt que le fond sombre voulu). `screens.Screen`,
> classe de base commune à tous les écrans, pose cet attribut une fois pour
> toutes plutôt que de compter sur le contexte d'affichage.


---

> ⚠️ **Illustration décorative, remplacée par la refonte de navigation
> (phase 8).** La console R36S (`gui/assets/console.png`) pulsait
> auparavant en fond discret de l'accueil (10 % à 16 % d'opacité,
> `QPropertyAnimation`) ; elle est désormais affichée en grand, bien
> visible, à une opacité fixe d'environ 70 % — en haut de la colonne
> droite (`screens.ConsoleArt`), toujours à l'écran, sans animation.
> `ConsoleArt.resizeEvent` la remet à l'échelle (`Qt.KeepAspectRatio`,
> jamais déformée) à chaque redimensionnement de la fenêtre.


---

> ⚠️ **Dérogation délibérée à la contrainte « jamais de dégradé ni de
> lueur ».** Cette règle, posée pour le premier habillage (ci-dessus),
> visait les aplats de l'interface elle-même (boutons, bandeaux, badges) —
> Qt les rend mal. Elle a été explicitement levée, sur demande, pour un seul
> élément décoratif : la console de la colonne droite porte deux effets
> lumineux permanents, tous deux peints en Qt pur, sans image
> supplémentaire.
>
> - **Socle lumineux** (`screens.ConsoleBasePlate`) : une ellipse aplatie
>   sous la console (~70 % de sa largeur), peinte via `QRadialGradient`
>   (cyan → transparent) dans `paintEvent` — technique de repère mis à
>   l'échelle (`painter.scale`) pour obtenir un dégradé radial elliptique à
>   partir d'un `QRadialGradient` qui n'accepte qu'un rayon unique. Son
>   opacité pulse entre 25 % et 55 % sur un cycle de 3 s.
> - **Halo** (`ConsoleHalo`) : une ellipse plus large que la console,
>   centrée derrière elle, peinte comme le socle (`QRadialGradient` cyan →
>   transparent). Son opacité pulse entre 15 % et 38 % sur un cycle de 4 s.
>   Peinte plutôt qu'un `QGraphicsDropShadowEffect` — voir le correctif de
>   performance ci-dessous, c'est le second essai de cet élément.
> - **Flottaison** : la console se déplace de ±6 px sur un cycle de 6 s, via
>   une propriété `floatOffset` animée qui décale le point de dessin dans
>   `paintEvent` plutôt que la géométrie du widget (évite tout conflit avec
>   le système de layout).
>
> Les trois animations (`QPropertyAnimation`, `QEasingCurve.InOutSine`,
> boucle infinie) sont regroupées dans un unique `QParallelAnimationGroup`
> (`ConsoleStage._group`) pour une pause/reprise centralisée. Le socle et le
> halo sont volontairement déphasés (périodes différentes, 3 s vs 4 s, plus
> un décalage de départ explicite sur l'animation du halo,
> `setCurrentTime(cycle // 2)`) pour qu'ils ne « respirent » jamais à
> l'unisson. `ConsoleStage.pause()`/`.resume()` sont appelés par
> `MainWindow` autour de chaque opération disque (`_start_worker`/
> `_on_worker_finished`) pour ne pas consommer de ressources pendant une
> écriture. Un réglage (case à cocher « Animations de la console »,
> `MainView.animation_toggle`) permet de les désactiver complètement —
> `set_animations_enabled(False)` arrête le groupe et remet les trois
> valeurs à leur état de repos plutôt que de les figer à une valeur
> intermédiaire arbitraire.

> ⚠️ **Correctif de performance, constaté en conditions réelles :
> l'animation de la console saccadait fortement.** Cause : le halo
> d'origine (ci-dessus) était un `QGraphicsDropShadowEffect` — Qt
> recalcule le flou gaussien de cet effet à chaque repeint du widget
> source, quel que soit le rayon demandé, et la flottaison changeait
> justement l'apparence de `ConsoleArt` en continu (donc un recalcul de
> flou à chaque frame). Trois correctifs, tous dans `screens.py` :
>
> 1. **Le halo n'est plus un `QGraphicsEffect`.** `ConsoleHalo` (ci-dessus)
>    le remplace par une ellipse peinte, sur le même principe que le socle
>    -- seule l'opacité s'anime (entre 15 % et 38 %), plus de rayon de flou
>    à recalculer.
> 2. **Le dégradé radial est mis en cache.** `_RadialGlowWidget`, classe de
>    base commune à `ConsoleBasePlate` et `ConsoleHalo`, ne reconstruit son
>    `QRadialGradient` que dans `resizeEvent` (peint une fois dans un
>    `QPixmap` mis en cache) — jamais depuis le setter de `glowOpacity`.
>    `paintEvent` se limite à un `drawPixmap` + `painter.setOpacity`.
> 3. **Le repeint est cadencé et limité en surface.** Les setters de
>    propriété (`floatOffset`, `glowOpacity`) ne déclenchent plus eux-mêmes
>    de `update()` — `QPropertyAnimation` met sinon à jour ses valeurs à la
>    fréquence du taux de rafraîchissement de l'écran, bien plus vite que
>    nécessaire pour une respiration sur plusieurs secondes.
>    `ConsoleStage._repaint_timer`, un `QTimer` cadencé à 33 ms
>    (~30 images/seconde), impose un unique repeint groupé par tick, limité
>    à `_console_update_rect` (union de la console, de son halo et de son
>    socle, recalculée dans `resizeEvent`) plutôt que `self.rect()` (qui
>    couvrirait toute la zone du haut de la colonne droite, marges vides
>    comprises) — et à plus forte raison jamais toute la fenêtre. Ce
>    minuteur ne tourne que pendant que le groupe d'animations tourne
>    réellement : arrêté dans `pause()` (déjà appelé autour de chaque
>    opération disque) et à la désactivation du réglage, démarré dans
>    `resume()`.
>
> **Vérifié** : mesure de charge CPU (`resource.getrusage`, backend Qt
> `offscreen`) sur `MainWindow` au repos, animations actives, sur 15 s :
> environ 7 à 9 % d'un cœur, entièrement imputable à la boucle de repeint
> de la console (retombe à 0 % avec `set_animations_enabled(False)`,
> confirmé en isolant la mesure). Ce chiffre est probablement surestimé
> par rapport à un vrai écran : le backend `offscreen` rasterise tout en
> logiciel à chaque repeint, sans la compositing GPU dont bénéficierait un
> affichage réel — mais aucun écran physique n'était disponible pour
> confirmer un chiffre définitif en conditions réelles.


---

> ⚠️ **Bug corrigé, constaté en conditions réelles : le bas de la console
> tronqué net (rognée sous les joysticks) et le socle lumineux jamais
> visible du tout — uniquement sur l'accueil du mode assisté, jamais sur
> la colonne droite du mode expert.** Confirmé en désactivant le réglage
> « Animations de la console » : l'image s'affichait alors entière,
> pointant directement vers la flottaison (`floatOffset`) comme cause.
>
> Cause réelle : `ConsoleStage.resizeEvent` donnait à `ConsoleArt` tout
> `self.rect()`, sans aucune marge réservée, avant de mettre le pixmap à
> l'échelle (`Qt.KeepAspectRatio`). Quand la hauteur de la boîte devient la
> contrainte liante du redimensionnement proportionnel — le cas sur
> l'accueil du mode assisté, dont la `ConsoleStage` est délibérément « plus
> grande, plus carrée » (note plus haut) que celle, plus large que haute,
> du mode expert — le pixmap scalé remplit *exactement* toute la hauteur
> du widget, laissant zéro marge : `floatOffset` pousse alors le bas de la
> console hors des limites de peinture du widget dès qu'il devient positif
> (Qt rogne toute peinture au-delà du rect propre d'un widget), et le halo/
> le socle (calculés à partir de cette même hauteur rendue, sans marge) se
> retrouvent positionnés hors des limites de `ConsoleStage` lui-même —
> rognés à leur tour, puisque Qt rogne aussi un widget enfant aux bornes de
> son parent.
>
> **Corrigé à deux niveaux, complémentaires :**
> 1. `ConsoleArt.resizeEvent` met désormais à l'échelle vers une taille
>    cible réduite de `2 * _FLOAT_AMPLITUDE` en hauteur (au lieu de
>    `self.size()` telle quelle) — garantit `rendered.height() <=
>    self.height() - 2 * amplitude`, donc au moins l'amplitude de marge de
>    chaque côté *dans les limites propres du widget*, quelle que soit la
>    contrainte liante. Fixe le rognage du bas de la console.
> 2. `ConsoleStage.resizeEvent` réserve en plus une marge verticale (haut
>    et bas) *autour* de la boîte donnée à `ConsoleArt`, dérivée des mêmes
>    constantes que la taille du halo (`_HALO_SCALE`, jusqu'à 17,5 % de la
>    hauteur rendue au-delà du haut et du bas de la console) et du socle
>    (`_PLATE_WIDTH_RATIO`/`_PLATE_HEIGHT_RATIO`) — calculée à partir des
>    dimensions du widget lui-même plutôt que de la taille rendue (majorants
>    sûrs, la console rendue ne pouvant jamais dépasser la boîte qu'on lui
>    donne), pour éviter la dépendance circulaire entre marge réservée et
>    taille rendue. Fixe l'invisibilité du socle et un éventuel rognage du
>    halo.
>
> `ConsoleArt._FLOAT_AMPLITUDE` devient la source de vérité unique (déplacé
> depuis `ConsoleStage`, qui la référence désormais) : `ConsoleArt` en a
> besoin pour sa propre réserve de marge (point 1), `ConsoleStage` pour la
> sienne (point 2). Vérifié par des tests couvrant plusieurs formes de
> boîte (plus haute que large, plus large que haute, très petite) balayant
> tout le cycle de `floatOffset`, pas seulement ses deux bornes
> (`tests/test_gui_screens.py`).


---

> ⚠️ **Trois régressions du correctif ci-dessus, corrigées à nouveau,
> constatées en conditions réelles après coup.** (1) La console avait
> disparu de l'accueil du mode assisté (seul le bouton « Préparer ma carte
> automatiquement » restait visible). (2) En mode expert, la console était
> devenue nettement plus petite qu'avant le premier correctif. (3) Le
> défaut de découpe persistait, différemment : pendant la flottaison, une
> partie de l'image restait fixe pendant que le reste montait/descendait
> — un morceau semblait se détacher ou s'enfoncer selon le sens du
> mouvement.
>
> **Causes réelles, trois bugs distincts :**
> 1. **(1) et (2), une vraie image (499×500, quasi carrée) contre des
>    boîtes synthétiques dans les tests.** Le calcul de marge du premier
>    correctif estimait la taille du socle/du halo à partir de
>    `self.width()`/`self.height()` (la boîte entière) plutôt que de la
>    taille *rendue* réellement — un majorant délibérément généreux
>    « pour ne jamais être insuffisant », mais qui surestimait
>    grossièrement dès que la console est engendrée par la hauteur (le
>    cas normal : une image quasi carrée dans une boîte plus large que
>    haute, en mode expert *comme* sur l'accueil assisté — l'hypothèse
>    initiale que le mode expert avait une marge naturelle suffisante
>    était fausse). Sur l'accueil (boîte plus grande), la surestimation
>    mangeait toute la hauteur disponible ; en mode expert, elle
>    rétrécissait fortement sans l'annuler complètement.
>
>    **Corrigé** par un calcul en deux passes, purement mathématique
>    (`_fit_within_aspect_ratio`, réplique `QPixmap.scaled(...,
>    Qt.KeepAspectRatio)` par le calcul) : une première passe estime le
>    rendu *naturel* (sans marge) pour dériver des tailles de socle/halo
>    réalistes, puis les marges réservées ne descendent jamais sous la
>    marge déjà présente naturellement (`max(marge_naturelle,
>    marge_requise)`) — de quoi éviter de rétrécir une boîte qui
>    contenait déjà tout, et de ne réserver que ce qui manque vraiment
>    sinon. Réserve aussi une marge *horizontale* (pas seulement
>    verticale) : le halo étant `_HALO_SCALE` fois plus large que la
>    console, son bord peut dépasser `self.width()` dès que la console
>    s'ajuste par la largeur, ce qu'une réserve uniquement verticale ne
>    couvrait pas.
>
>    Ce calcul en deux passes a révélé un piège Qt distinct au passage :
>    lire `ConsoleArt.rendered_size()` juste après `setGeometry()`,
>    *depuis l'intérieur du `resizeEvent` d'un widget parent*, peut
>    refléter l'état *précédent* — Qt diffère alors la livraison du
>    `resizeEvent` de l'enfant plutôt que de l'envoyer immédiatement
>    (constaté en conditions réelles : le calcul lisait `(0, 0)`, une
>    valeur périmée, menant à des tailles de socle grossièrement fausses
>    — ex. un socle large de 450px pour une console rendue à 184px). Ce
>    piège ne se manifestait pas dans les tests unitaires les plus
>    simples (`ConsoleStage` redimensionnée directement, hors de tout
>    layout parent), où `setGeometry` livre bien `resizeEvent`
>    immédiatement — d'où son absence de détection avant la vraie
>    application. `_fit_within_aspect_ratio` (calcul pur, indépendant de
>    tout événement Qt) contourne le problème plutôt que de tenter de le
>    résoudre : `setGeometry` reste appelé pour que Qt peigne
>    effectivement le bon résultat dès que l'événement différé arrive,
>    mais plus aucun calcul de `ConsoleStage` n'attend cette livraison.
> 2. **(3)** `ConsoleBasePlate` avait une géométrie fixe, calculée une
>    fois dans `resizeEvent` sans jamais suivre `floatOffset` — la
>    console flottait pendant que son socle restait immobile, donnant
>    l'impression qu'un morceau se détachait ou s'enfonçait selon le sens
>    du mouvement (les deux n'étaient pas dessinés dans le même repère).
>    **Corrigé** : `_repaint_console_area` repositionne désormais le
>    socle (`QWidget.move`, qui ne redéclenche jamais `resizeEvent` —
>    seule la position change, pas la taille, donc aucun recalcul du
>    dégradé mis en cache) à sa position de repos décalée de l'offset
>    courant, exactement comme `ConsoleArt.paintEvent` décale son propre
>    tracé — les deux widgets partagent ainsi la même valeur à chaque
>    tick. `set_animations_enabled(False)` remet aussi le socle à sa
>    position de repos, symétriquement à `floatOffset = 0.0`.
> 3. **(3), également** : le rectangle d'invalidation par tick
>    (`_console_update_rect`, une sous-région calculée) ne suivait pas
>    exactement chaque élément mobile, laissant une partie de l'image
>    sans repeint. **Corrigé** en invalidant `self.rect()` en entier à
>    chaque tick plutôt qu'une sous-région — `ConsoleStage` reste petit
>    et le repeint déjà cadencé à 30 im/s (§5 correctif de performance
>    précédent), le coût reste négligeable ; `_console_update_rect` est
>    retiré, devenu inutile.
>
> **Vérifié** : nombres réels recalculés avec la vraie `console.png`
> (499×500) dans les proportions réelles des deux écrans (mode expert
> ~616×415, accueil du mode assisté ~1072×329) — rendu contenu dans les
> deux cas (socle et halo compris), à une taille visiblement raisonnable
> (~60-70 % de la hauteur disponible), plus grande qu'avec le calcul
> buggé. Captures d'écran (`QWidget.grab()`, backend `offscreen`) des deux
> écrans, animations activées (à `floatOffset` bas/médian/haut) puis
> désactivées : console et halo visibles sur les deux écrans, rien ne
> semble tronqué. Non confirmé sur un vrai écran, faute d'écran physique
> disponible ici (même limite que la mesure de charge CPU plus haut).


---

