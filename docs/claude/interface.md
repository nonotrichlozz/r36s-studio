# Interface — mode expert, thème, journal, messages d'erreur

À lire quand tu touches à `gui/screens.py`, `gui/theme.py`, `gui/strings.py`, au `LogPanel` ou à la présentation du mode expert. Le mode assisté a son propre fichier : `assisted-wizard.md`.

> Les renvois « §N » de ce texte désignent les sections de l'ancien `CLAUDE.md` monolithique (commit `930f3c9`) : §3 → `elevation-macos.md`, §4.1/§4.2 → `devices-safety.md`, §4.3 → `imaging.md`/`reset-card.md`, §4.4 → `partitions.md`, §4.5 → `detect.md`, §4.6 → `firmwares-flash.md`, §5 → `interface.md`/`assisted-wizard.md`, §6 → `packaging.md`, §8 → `testing.md` ; §1/§2/§9 restent dans `CLAUDE.md`.

> 📚 Historique détaillé (bugs corrigés, investigations) : `docs/bugs-interface.md`

1. **Colonne gauche (bandeau + six étapes + sauvegarde)** — un bandeau en
   haut (bordure cyan, coins arrondis) résume la carte détectée : icône de
   console dessinée au `QPainter` (`_ConsoleIcon`, pas une image), modèle et
   taille, bouton « Rafraîchir » aligné à droite, tous sur une seule ligne ;
   une seconde ligne en dessous précise l'état reconnu (« Carte ArkOS
   reconnue », « Carte non préparée », ou « Aucune carte détectée » sans
   carte branchée). En dessous, les six étapes du parcours à deux cartes
   (§4.5/§4.6), **toujours toutes visibles**, dans leur ordre chronologique
   fixe A→F, une ligne par étape (icône lettrée à gauche, titre +
   description au centre, badge de statut à droite, cadre arrondi). Statuts
   (pastilles en forme de capsule) : faisable (vert), déjà faite (gris), non
   pertinente pour la carte branchée (texte seulement, sans badge visible
   dans les faits), ou limitée par la plateforme (orange, « PC ou Linux » —
   §4.5, `StepStatus.PLATFORM_LIMITED`, ex. copier l'EASYROMS sur macOS). Ce
   statut guide sans jamais rien masquer. Sous un titre « Par sécurité », en dehors
   de cette liste, trois lignes : sauvegarde complète, sauvegarde système
   sans les jeux, remise à zéro de la carte — pas des étapes du parcours.
   **Cliquables sauf pendant une opération** : `HomeScreen.set_busy(True)`
   désactive alors les six lignes et la sauvegarde (`setEnabled(False)`,
   qui empêche Qt de délivrer les clics — pas seulement l'apparence) et les
   assombrit visiblement (`QGraphicsOpacityEffect`, ~45 % — une simple
   différence de fond QSS via `:disabled` s'est révélée trop proche de la
   surface habituelle pour se voir clairement sur une palette déjà sombre,
   vérifié en comparant des captures avant/après).
2. **Fenêtre Choix de la carte** (`DeviceDialog`) — liste des cartes
   détectées : modèle, taille, bus. Bouton « Rafraîchir ». Aucune sélection
   par défaut — même quand une seule carte est branchée, et même pour
   l'étape F qui n'ouvre pas de fenêtre Fichier ensuite. « Retour » ferme
   simplement la fenêtre (`close()`), sans rien changer à la vue principale
   derrière.
3. **Fenêtre Choix du fichier** (`FileDialog`) — image source pour le
   flash, fichier de sortie pour la sauvegarde ; pour les étapes A/B
   (extraction), un dossier de destination avec `~/Documents/R36S Studio/`
   proposé par défaut mais toujours remplaçable (y compris par un disque
   externe) — le nom horodaté à l'intérieur reste automatique ; pour les
   étapes D/E (injection sur la carte neuve), une sauvegarde à choisir
   parmi les archives déjà extraites (§4.4), avec un repli « Parcourir… »
   pour une source manuelle. Seule l'étape F (éjection) saute cette
   fenêtre : elle ne demande rien d'autre que la carte.
4. **Fenêtre Confirmation** (`ConfirmDialog`) — fond rouge, récapitulatif
   explicite : *« Toutes les données de SanDisk Ultra 128 Go seront
   effacées. »* + case à cocher obligatoire. Seul le flash (étape C) écrit
   sur le périphérique brut et déclenche cette fenêtre. Annuler ferme la
   fenêtre sans démarrer l'opération, sans rien changer derrière.
5. **Journal de bord permanent** (`LogPanel`, bas de la colonne droite) —
   remplace les anciens écrans Exécution et Résultat, tous deux supprimés :
   tout se passe dans ce panneau, toujours visible, jamais un écran séparé.
   Cadre à bordure cyan, fond très sombre, texte vert clair en police
   monospace pour les lignes du journal (seul endroit de toute l'interface
   en dehors des libellés généraux). En-tête « OPÉRATION ACTIVE » suivi du
   nom de l'étape en cours pendant une opération, ou « En attente » au
   repos. Barre de progression réelle (débit en Mo/s, temps restant estimé)
   sous l'en-tête pendant une opération, bouton Annuler actif à côté du
   titre. En dessous, les lignes horodatées défilent automatiquement au
   format `21:44:02 - Montage des partitions: OK` et s'accumulent pour la
   durée de l'opération en cours — vidées seulement au démarrage de la
   suivante (`start_operation`), jamais entre-temps. Les résultats de fin
   d'opération (succès ou erreur, jamais de jargon — voir Vocabulaire)
   s'affichent comme une ligne de plus dans le journal, avec les actions
   qui suivaient auparavant sur l'écran Résultat réapparaissant dans
   l'en-tête : bouton Éjecter après une opération qui a écrit sur la carte,
   bouton Afficher dans le Finder/l'Explorateur après une extraction ou une
   injection. Pour l'étape F (éjection, immédiate — aucune progression),
   confirme explicitement dans le journal que la carte peut être retirée
   physiquement, jamais un succès silencieux.

**Vocabulaire :** aucun terme technique dans l'interface. Pas de « périphérique bloc »,
pas de `/dev/sdb`, pas de « partition ». On dit « ta carte SD », « les jeux », « le
système de la console ». Le chemin technique — ou tout message brut du backend
(chemin, nom de système de fichiers...) — n'est jamais dans le message principal :
il suit comme ligne supplémentaire dans le journal de bord (`LogPanel.finish_error`)
— plus de panneau « Détails » séparé à déplier depuis la refonte de navigation
ci-dessus, un journal étant par nature un endroit où tout finit par être visible.

Interface en français, avec les chaînes isolées dans un fichier de traduction dès le
départ (l'anglais viendra vite si tu diffuses la vidéo hors France).

**Affichage des tailles, une seule base partout :** toute capacité affichée
(carte entière ou octets copiés) utilise la base 1024 (`size_bytes / 1024**3`,
`gui/screens.py::_capacity_go`/`_format_size`, dupliqué côté CLI dans
`__main__.py` pour ne pas faire dépendre le CLI de PySide6) — jamais la base
1000. Se rapproche de l'Explorateur Windows (la plateforme la plus testée dans
ce projet) au prix d'un désaccord avec le Finder macOS/Nautilus, qui utilisent
la base 1000 : une carte annoncée « 128 Go » par son fabricant s'affiche ici
autour de 119 Go. Délibérément un seul nombre partout, jamais un double
affichage Go/Gio — resterait plus simple qu'introduire un terme technique
inconnu d'un néophyte pour un écart que l'utilisateur ne remarque que s'il
compare activement deux écrans.

**Habillage visuel (phase 8) : `gui/theme.py`.** Palette « poste de commande »
sombre et technique, inspirée des interfaces de console de jeu rétro — fond très
sombre, surfaces légèrement plus claires, bordures cyan fines, une seule couleur
d'accent (le cyan, réutilisée pour les bordures actives, les barres de
progression et les icônes). Aucune lueur, ombre portée ni dégradé — Qt les rend
mal (aliasing grossier) et ça nuit à la lisibilité sur une palette déjà sombre.
Toute la palette vit dans ce seul fichier, sous forme de constantes nommées ;
`gui/app.py` applique la feuille de style QSS qui en résulte une fois,
globalement (`QApplication.setStyleSheet`). Les écrans (`gui/screens.py`) ne
posent jamais de couleur en dur : ils fixent un rôle (`role`, ex. `"title"`,
`"secondary"`, `"row"`, `"log"`, `"danger"`) ou un statut de badge
(`badgeKind`) via `setProperty`, et la feuille de style décide de l'apparence à
partir de là — `theme.repolish(widget)` doit être appelé après tout
`setProperty` sur un widget déjà affiché (Qt ne réévalue les sélecteurs
`[propriété="valeur"]` qu'au moment où le style est recalculé). `screens.Screen`
(classe de base commune à tous les écrans) pose systématiquement l'attribut Qt
`WA_StyledBackground` — sans lui, un `QWidget` nu n'honore `background-color`
en QSS que par accident, quand un parent le peint à sa place.

**Corrigé** en ajoutant ces six codes à `_ERROR_MESSAGE_KEYS`, avec un
message convivial dédié chacun. En complément, `gui/strings.py::
error_log_detail(code, msg)` (nouvelle fonction) garantit qu'un futur
code encore non mappé n'est plus jamais un trou total : quand
`friendly_error_message` retombe sur `error_generic`, le code brut du
protocole précède désormais le message dans le détail journalisé (ex.
`CODE_INCONNU : message brut`) plutôt que de disparaître silencieusement
-- un code déjà traduit n'a pas besoin de cette répétition, le message
brut seul suffit comme avant (§5 vocabulaire : le détail brut suit
toujours le message principal comme ligne supplémentaire du journal).
Les six points d'appel de `gui/main_window.py` qui construisaient
`details=self._last_error_msg or ""` en dur passent désormais par cette
fonction. Un test dédié (`tests/test_gui_strings.py::test_every_cli_
emitted_error_code_is_mapped_to_a_friendly_message`) relit littéralement
tous les `emit_error("CODE", ...)` de `__main__.py` et vérifie qu'aucun
ne retombe sur le message générique -- filet de sécurité pour qu'un
futur code ajouté côté CLI ne reproduise pas ce même trou en silence.

**Second passage, sur maquette de référence.** Coins arrondis sur le bandeau de
détection et les lignes d'étape (`border-radius: 10px`, contre 4px avant) et
badges en forme de capsule plutôt que de simple rectangle arrondi. Le bandeau
de détection regroupe désormais, sur une seule ligne : une icône de console
dessinée au `QPainter` (`screens._ConsoleIcon` — pas une image, pour rester
sans dépendance externe), le modèle et la taille de la carte, et le bouton
Rafraîchir aligné à droite ; le bouton Aide (macOS uniquement, §3) est
descendu sur sa propre ligne, en dessous.

**Deux illustrations décoratives, chacune avec son propre rôle
(`gui/assets/`, `gui/asset_paths.py`) :**

- **`console.png`** (`screens.ConsoleArt`, dans `screens.ConsoleStage`) : la console R36S détourée, en haut de la colonne
  droite, à ~70 % d'opacité fixe peinte à la main dans `paintEvent`
  (`painter.setOpacity`).
- **`circuit.png`** (`screens.WindowBackdrop`) : un motif de circuit
  imprimé, sur **toute la fenêtre**, derrière les deux colonnes, à 15 %
  d'opacité fixe — répété en mosaïque (`QPainter.drawTiledPixmap`, jamais
  mis à l'échelle) pour rester net à n'importe quelle taille de fenêtre,
  contrairement à une image étirée. Les panneaux des colonnes (bandeau,
  lignes d'étape, journal de bord — tous à fond opaque, `theme.py`) restent
  donc lisibles par-dessus, quelle que soit la zone qu'ils recouvrent.
  Assemblé par `screens.MainView`, qui l'envoie derrière (`lower()`) avant
  d'ajouter les deux colonnes.

Toutes deux : jamais cliquables (`WA_TransparentForMouseEvents`), et absentes
sans lever d'exception si le fichier correspondant n'existe pas
(`asset_paths.asset_path`, retourne `None` — l'interface s'affiche
normalement sans elles, vérifié par test). `packaging/r36s_studio.spec`
n'inclut chaque image dans le binaire empaqueté que si elle est présente au
moment de la construction, même principe — vérifié de bout en bout sur le
vrai binaire pour `console.png` (`sys._MEIPASS` résout bien `gui/assets/`
une fois empaqueté, via le même mécanisme que l'horodatage de construction,
§5 plus haut).

**Retiré, ne pas réintroduire** : les animations de la console (`ConsoleHalo`, `ConsoleBasePlate`, `floatOffset`, minuteur de repeint à 30 im/s, réglage « Animations de la console ») — coût de 7-9 % d'un cœur au repos pour un agrément jamais utilisé. `ConsoleArt` est immobile, à opacité fixe (70 %).

**Terminal d'activité disque sur l'écran de la console** (`ConsoleTerminalOverlay`, alimenté par `MainWindow._on_progress`) : une ligne par événement de progression réel. Retiré à tort puis rétabli (récit dans `docs/bugs-interface.md` : le ralentissement venait d'une carte SD bas de gamme, pas du terminal).

**Rétabli entièrement** : `ConsoleTerminalOverlay`, `ConsoleStage.
append_line`/`start_activity`/`stop_activity`, `_SCREEN_RECT_FRACTIONS`,
`_fit_within_aspect_ratio` et `ConsoleArt.source_size` sont de retour
dans `gui/screens.py`, avec le correctif de repeint cadencé/police mise
en cache conservé (sans coût, toujours une bonne pratique, mais plus
présenté comme correctif d'un problème qu'il n'a jamais résolu) ; les
points d'appel `start_activity`/`stop_activity` et le bloc `append_line`
de `_on_progress` (`gui/main_window.py`) aussi. `LogPanel` (bas de la
colonne droite) reste inchangé, le terminal reste un affichage distinct
et complémentaire, jamais un remplacement.
