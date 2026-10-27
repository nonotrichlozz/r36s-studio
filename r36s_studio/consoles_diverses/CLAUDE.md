# Consoles diverses — étape 1 : mode recherche

> Sous-brief du package `r36s_studio/consoles_diverses/`. Complète (ne
> remplace pas) `CLAUDE.md` à la racine du dépôt.

**Statut : étape 1 terminée** (recherche + affichage de la fiche,
réglages). Voir `docs/consoles-diverses-recherche.md` pour le brief
d'origine et les prochaines étapes (analyse de carte SD, installation,
contributions, dédoublonnage des jeux).

## Règle d'isolation

Ce package est volontairement indépendant du reste de R36S Studio :

- Il n'appelle jamais le worker élevé, `imaging/`, `partitions/`, `devices/`
  ni `safety/` -- un simple appel HTTP en lecture, rien à voir avec
  l'écriture disque brute (§3 de CLAUDE.md racine).
- Toutes ses chaînes vivent dans `consoles_diverses/strings.py`, jamais dans
  `gui/strings.py`.
- Le code R36S existant n'est modifié qu'au strict minimum pour le point
  d'entrée dans la navigation : un signal et un bouton sur `HomeScreen`/
  `AssistedLandingScreen` (`gui/screens.py`), leur câblage dans
  `gui/main_window.py`, et un champ dans `AppConfig` (`config.py`). Rien
  d'autre.

## Contrat serveur

Le serveur (`r36s-studio-cloud`, projet séparé, documentation lue en
lecture seule -- jamais `.dev.vars`) expose `POST /recherche` :

```
POST /recherche
Content-Type: application/json
X-Licence-Key: (toujours envoyé, même vide)

{"reference": "..."}
```

Réponses : `200 {"statut": "trouve_dans_catalogue"|"trouve_par_ia"|
"aucune_information_trouvee", ...}`, ou une erreur (`400 reference_
invalide`, `403 licence_requise`/`licence_invalide`, `500 configuration_
manquante`, `503 recherche_ia_indisponible`, `502 erreur_api_ia`/
`reponse_ia_non_json`). Côté client (`client.py`) s'ajoutent
`serveur_injoignable`, `delai_depasse` et `reponse_invalide` (réponse
absente/malformée/trop grande). Une fiche `console` suit
`r36s-studio-catalogue/schema/console.schema.json` (`models.py` en fait un
parsing défensif : seuls les champs d'identité indispensables font échouer
le parsing).

✅ **Serveur de production en ligne, confirmé en conditions réelles** :
`https://r36s-studio-cloud.r36studio.workers.dev` (HTTPS, derrière
Cloudflare -- distinct du serveur local de développement,
`http://localhost:8787`, qui n'a pas Cloudflare devant lui).

⚠️ **Bug corrigé, confirmé sur du vrai serveur en ligne** : une recherche
qui fonctionnait contre le serveur local échouait contre le serveur de
production avec `reponse_invalide` (« Le serveur a renvoyé une réponse
inattendue »). Cause : `urllib.request` n'envoie aucun en-tête `User-
Agent` explicite par défaut, retombant sur `"Python-urllib/{version}"` --
une signature que Cloudflare bloque par défaut (403, `error code: 1010`)
avant même que la requête n'atteigne le Worker. Confirmé en isolant la
piste (curl avec différents en-têtes `User-Agent`, requête sinon
identique) : ni la compression (aucun `Content-Encoding` sur la réponse),
ni l'URL, ni le corps, ni l'encodage n'étaient en cause --
`python-requests/...` n'est pas bloqué, ce n'est donc pas une règle
générique anti-script. `client.py` envoie désormais un en-tête `User-
Agent` explicite (`USER_AGENT`, `"R36S-Studio/{version}"`) sur chaque
requête -- même principe déjà suivi côté serveur pour ses propres
requêtes sortantes vers GitHub/Handhelds Wiki
(`r36s-studio-cloud/lib/sources/userAgent.ts`, lu en lecture seule).

Un échec HTTP dont le corps n'est pas la forme `{"erreur": ...}` attendue
(ex. le blocage Cloudflare ci-dessus) est désormais consigné dans le même
journal que les fiches rejetées (`client.py::_journaliser_erreur_http_
inattendue`, `gui/logs.py::consoles_diverses_log_path`) -- statut HTTP et
extrait du corps, tronqué. Un code `{"erreur": ...}` bien formé du
serveur (référence invalide...) n'est lui jamais journalisé, ce n'est pas
un incident -- exception : `licence_invalide`/`licence_requise`
consignent un diagnostic dédié (`client.py::_journaliser_diagnostic_
licence`), voir ci-dessous.

## Durcissement (une fiche est une donnée externe non fiable)

Le serveur peut renvoyer une fiche générée par IA (`statut: "non_
verifie"`), jamais vérifiée par un humain. Quatre mesures :

1. **Texte brut, jamais interprété** (`screen.py::_plain_label`) --
   `QLabel.setTextFormat(Qt.PlainText)` sur tout texte venu du serveur.
2. **Liens restreints à http(s)** (`screen.py::_est_url_externe_sure`) --
   `file:`/`javascript:`/un chemin local/un schéma absent restent du texte
   simple, jamais un lien ouvert automatiquement.
3. **Adresse du serveur en dur** (`settings_store.py::adresse_serveur`,
   `PRODUCTION_SERVER_URL`) -- jamais saisie ni modifiable depuis la GUI
   (champ retiré des réglages : un client ne saurait pas quoi y mettre, et
   une adresse mal tapée rendait la section inutilisable sans message
   clair). Seule surcharge : la variable d'environnement
   `R36S_STUDIO_CLOUD_URL` (Worker local en développement), validée par
   `valider_adresse_serveur` -- `https://` toujours accepté, `http://`
   seulement pour `localhost`/`127.0.0.1` (sinon la clé de licence
   circulerait en clair) ; une valeur refusée est signalée sur la sortie
   d'erreur, repli sur la production. L'ancien champ `AppConfig.
   consoles_diverses_server_url` n'existe plus : un `config.json` qui le
   porte encore (souvent `http://localhost:8787`) est ignoré.
4. **Réponse plafonnée à 1 Mio** (`client.py::MAX_RESPONSE_BYTES`) avant
   tout `json.loads`.

## Clé de licence : `config.json`

Clé saisie dans les réglages de la section (seul champ restant), mémorisée
dans `config.json` (`AppConfig.consoles_diverses_licence_key`), lue et
écrite par `MainWindow` avec le reste de la configuration -- jamais par
un module à part, qui réécrirait `config.json` dans le dos de
`MainWindow._app_config` (sa copie en mémoire écraserait la clé au
prochain `save_config`). `.strip()` à l'enregistrement et à la lecture :
un copier-coller dans un champ masqué laisse souvent un espace ou un
retour à la ligne invisible (bug réel, clé valide refusée).

Exception assumée au « config.json sans secret » (CLAUDE.md racine) :
une clé par client, révocable côté serveur (KV `LICENCES` de
r36s-studio-cloud, `npm run licence -- revoquer`), pas un mot de passe.
**Historique** : la clé était auparavant au trousseau système
(`keyring`), retiré -- sous Windows, `WinVaultKeyring.set_password` peut
lever après avoir réécrit l'ancienne valeur, laissant une clé figée
quelle que soit la ressaisie (deux signalements réels). Plus de
dépendance `keyring`, ni dans `requirements.txt` ni dans les `.spec`.

Refus serveur et message affiché (`strings.py::_ERROR_MESSAGE_KEYS`) :
`licence_requise`, `licence_invalide`, `licence_expiree`,
`licence_revoquee` (403, bouton « Saisir ma clé » sous le message),
`quota_licence_depasse` (429, quota quotidien du client), `licence_non_
supportee` (500, serveur mal réglé). Sans clé, l'écran l'explique d'emblée
(`_no_licence_frame`) au lieu de rester vide.
`client.py::_journaliser_diagnostic_licence` consigne toujours, à chaque
refus de licence, longueur/hash/URL (jamais la clé en clair).

## Télécharger et installer (2026-10-17)

Une option de fiche peut porter un champ `telechargement` (schéma du
catalogue : `depot`, `motif_fichier`, `url_directe` optionnelle). Sur une
fiche **vérifiée** seulement, l'option affiche alors un bouton
« ⬇ Télécharger et installer » (`screen.py`, signal `install_requested`).

1. `telechargement.py::resoudre` (thread `search_runner.py::
   FirmwareResolveRunner`) cherche dans la **dernière** release GitHub de
   `depot` le fichier dont le nom correspond à `motif_fichier` -- une
   nouvelle version publiée par le projet est prise sans toucher au
   catalogue. Repli sur `url_directe` si l'API ne répond pas (limite
   anonyme de 60 requêtes/heure) ou ne trouve rien.
2. `MainWindow._on_consoles_diverses_install_requested` bascule sur le
   journal de bord (habillage du mode courant, `ui_mode` jamais modifié),
   télécharge avec `RocknixDownloadRunner` (générique malgré son nom :
   progression réelle, annulation, sha256 vérifié quand GitHub publie le
   `digest` du fichier), dans `~/Documents/R36S Studio/Firmwares/`.
3. Puis fenêtre Choix de la carte et fenêtre Confirmation habituelles
   (§2 n°6, jamais sautées). `_catalogue_flash_active` neutralise tout
   réglage lié au firmware du sélecteur R36S (question d'écran ROCKNIX,
   consignes Android) : la console n'est pas forcément une R36S.

**Réglages après flash (`apres_flash`)** : liste de copies à l'intérieur
d'une partition de la carte juste après l'écriture (ex. ROCKNIX sur H700 :
`device_trees/sun50i-h700-anbernic-rg40xx-v.dtb` → `dtb.img`). Transmises
au worker élevé (`flash --copy-after-flash PARTITION SOURCE DESTINATION`,
`partitions/post_flash_copy.py`, mêmes règles de chemin des deux côtés),
avant l'éjection. Échec = avertissement clair, jamais un échec du flash.
Une seule entrée invalide retire le bouton : jamais une installation à
moitié réglée. **Clé `installation` du catalogue** : même contenu que
`telechargement`, lue en priorité, et seulement par les versions ≥ 0.1.10
-- à utiliser dès qu'il y a `apres_flash`, sinon une 0.1.9 (qui ignore ce
champ) afficherait un bouton qui laisse la console sans démarrer.

**Consigne de premier démarrage (`consigne_premier_demarrage`, 0.1.15,
KNULLI : secteur obligatoire)** : texte brut ramené sur une ligne, ≤ 400
caractères, sinon ignoré (jamais tronqué, le bouton reste). Bandeau orange
dans `ConfirmDialog`, puis après un flash réussi ligne du journal et
fenêtre « Avant d'allumer ta console » à fermer (`_show_first_boot_note`,
modes expert et assisté). Champ facultatif : les versions antérieures
l'ignorent, rien à mettre sous `installation`.

**Source MEGA (`"source": "mega"`, 2026-10-17, muOS)** : `dossier` = lien
public `https://mega.nz/folder/<ID>#<CLÉ>`, fichier choisi par
`motif_fichier`, SHA-256 lue dans le `hash.txt` du dossier, contenu
déchiffré en AES-128-CTR pendant le téléchargement (`mega.py`, dépendance
`cryptography`). Pas de `depot` : les versions antérieures n'affichent pas
de bouton. Gofile écarté (jeton calculé par un script obfusqué). Échec
(quota MEGA, lien changé) : message clair + bouton « Ouvrir la page »
(`LogPanel.finish_error(page_url=…)`, page = `url` de l'option), aucun
fichier partiel gardé (`download_asset` : taille annoncée exigée).
**Usage personnel** : toute option `restriction_commerciale` passe par la
fenêtre « Usage personnel uniquement » (`main_window._confirm_personal_use`,
case obligatoire) avant tout téléchargement.
**Point ouvert (RG40XXV)** : muOS installé par le bouton s'éteint au logo
au premier démarrage, alors que l'image téléchargée est identique à celle
qui marchait (SHA-256 vérifiée) ; cause non trouvée.

Durcissement : dépôt au format `propriétaire/nom`, téléchargement depuis
`https://github.com/` (ou dossier `https://mega.nz/` et serveurs
`*.mega.co.nz` en HTTPS) uniquement, taille annoncée ≤ 16 Gio, nom de fichier sans séparateur et
finissant par `.img`/`.img.gz`/`.img.xz` (jamais un `.7z`). Exception
assumée à la règle d'isolation ci-dessus : ce flux réutilise le pipeline
de flash, par `MainWindow` uniquement -- le package lui-même n'écrit
toujours rien sur un disque.

## Installations guidées par USB : mode Download Unisoc (2026-10-27)

Première console : Anbernic RG Rotate, GammaOS Next 1.4.1. Ici on ne
flashe **pas** une carte SD : le système s'écrit dans la mémoire interne,
console branchée en USB en mode Download, **carte SD retirée**. Plan de
test sur la vraie console : `docs/rg-rotate-test-console.md`.

**Moteur générique, piloté par la fiche** (`procedures` du catalogue,
`$defs/procedure` du schéma). Rien de propre à une console dans le code :
une RG Vita ou une RG DS n'aura besoin que de sa fiche.

- `procedures/fiche.py` : lecture défensive (une entrée inexploitable est
  absente, jamais un rejet de la fiche), et plan. Chaque `action` tombe
  dans une phase (`ACTION_VERS_PHASE`), parcourues dans l'ordre de
  `PHASES` : prerequis, telechargement, pilotes, extraction,
  verification_pac, consignes, flash, premier_demarrage. Un flash impose
  toujours téléchargement des outils, pilotes et contrôle du .pac.
  `motif_desactivation` : action inconnue (`etape` -- c'est le cas de
  `selectionner_partitions`, restauration Super), autre `mode`, système
  non listé dans `plateformes`, ou pas de `pac_produit` → procédure
  affichée avec sa raison, sans bouton.
- `procedures/telechargement.py` : reprise par `Range` (`<nom>.part`,
  GitHub répond bien 206, vérifié), SHA-256 obligatoire (un fichier sans
  `sha256` dans la fiche n'est jamais téléchargé automatiquement), fichier
  déjà présent et juste = pas retéléchargé. Cache :
  `~/Documents/R36S Studio/Firmwares/<id de la fiche>/`. Un lien non
  GitHub (Google Drive du firmware d'origine) : l'utilisateur télécharge
  lui-même puis choisit le .pac ou son archive.
- `procedures/outils.py` : zip d'outils extrait une fois (« zip slip »
  refusé), programmes cherchés **par leur nom** (le zip RG Rotate contient
  en réalité `UnisocTools_RG_VITA/`).
- `procedures/septzip.py` : **7-Zip fourni dans les outils**
  (`SPRD_Download_Tool/System/Tools/7zip/32/7z.exe`, 19.02), préféré à
  py7zr (natif, rapide sur 6,7 Go, progression `-bsp1`, morceaux suivis
  seuls ; procédure Windows de toute façon). **Mot de passe sur l'entrée
  standard**, jamais `-p` (visible des autres programmes, et l'appli
  journalise les commandes). Vérifié avec ce 7z.exe : extraction
  identique d'une archive chiffrée en 3 morceaux, mauvais mot de passe
  détecté (« Wrong password » / « Can't open as archive » si en-têtes
  chiffrés). Test du mot de passe avant extraction : `7z t` arrêté au
  premier pourcentage. **Jamais essayé sur la vraie archive GammaOS.**
- `procedures/pac.py` : en-tête `BP_R…` (positions relevées sur le vrai
  .pac Lite : produit `ums512_1h10`, version `1.4.1`, nom
  `RG_ROTATE_GAMMAOS_NEXT_LITE`). Comparé à `pac_produit` (procédure),
  `version` (si c'est un numéro) et `pac_nom` (variante) : sinon refus,
  rien d'écrit.
- `procedures/usb.py` : `Get-CimInstance Win32_PnPEntity` en JSON (champs
  indépendants de la langue). **Tout nouvel appareil USB est journalisé**
  avec son VID:PID. **Confirmé (2026-10-27)** : le port COM5 du flash
  réussi d'UpgradeDownload (journaux `SPRD_Download_Tool/Log/2026_10_27/`)
  est `USB\VID_1782&PID_4D00` (registre des périphériques) : RG Rotate en
  mode Download = `1782:4d00`, « SPRD U2S Diag », pilote `sprdvcom`. Sous
  GammaOS Next : `1782:4003` (« GammaOS Next Lite », MTP + ADB, numéro de
  série `ROTATE…`) ; `1782:d001` vu aussi (ADB seul).
- **Mauvais bouton au branchement** (constaté le 2026-10-27) : seul le
  bouton Retour (au centre de la manette, console ouverte en coulissant)
  met la console en vrai mode Download. Avec un autre, elle apparaît en
  « SPRD U2S Diag » mais ne répond pas au CHECK_BAUD (`[SW2276]Check baud
  time out`), lâchée après ~4 s (`[PS2262]User cancel`). Reconnu dans la
  sortie de CmdDloader et, après un échec, dans les journaux qu'il laisse
  sous `Log/` (`cmddloader.bouton_dans_journaux`) : message
  `proc_flash_bouton_retour`.
- `procedures/pilotes.py` : `pnputil /add-driver …\*.inf /install`
  (paquet `Win10`, sous-dossiers `amd64/`/`i386/` gardés) plutôt que
  DPInst (clics bloqués, constaté). Détection : `sprdvcom.inf` dans
  `pnputil /enum-drivers`. Codes 0 et 3010 (redémarrage conseillé) =
  réussite. **Visual C++ non installé** : les outils n'importent que
  `msvcr100`/`msvcp100`/`msvcp140`/`vcruntime140`, tous fournis dans
  `System/Dependency/` -- à confirmer sur un Windows vierge.
- `procedures/cmddloader.py` : syntaxe ci-dessous. `procedures/veille.py` :
  `SetThreadExecutionState` pendant le flash.
- `procedure_runner.py` (threads Qt) et `procedure_screen.py` (écran).
  Entrée : section « Installations guidées » de la fiche, **seulement pour
  une fiche du catalogue** (`trouve_dans_catalogue`), jamais une fiche IA ;
  bandeau « Expérimental » tant que la fiche n'est pas `verifie`.

**CmdDloader.exe** (27.24.2301, syntaxe lue dans le programme, jamais
lancé sur une console) :

    CmdDloader.exe -pac <fichier.pac> -Version 2 -Port 0 -Timeout <ms> -Reset

`-Version` 0 Research (défaut) / 1 Factory / 2 **Upgrade** (même mode que
l'outil graphique) ; `-Port 0` = détection auto ; `-Timeout` couvre aussi
le chargement du .pac (~2 min), 15 min par défaut, réglable à l'écran ;
`-Reset` redémarre la console à la fin (`-PowerOff` incompatible). Autres
options : `-Policy`, `-Baudrate`, `-SkipFileID a,b`, `-SendFlag`,
`-WriteSN1/2`, `-ReadNV`, `-WriteEfuse`, `-WriteTimeStamp`, `-EZMode`,
`-DDDP`, `-Help`. Sortie lue : `Loading packet progress is N%`,
`PACKET: …; Version: …;`, `Please connect the DUT in Ns`, `PORT = COMn`,
`[Status] N%`, `Download Result = Passed;` / `Failed; Error Messag = …`.
CmdDloader est lancé **avant** le branchement (il charge le .pac puis
attend la console, comme UpgradeDownload) ; annulation possible tant que
`PORT = COM` n'est pas apparu, plus après.

**Sécurité** : case « tout sera effacé » jamais pré-cochée au début, puis
de nouveau juste avant d'écrire (consignes) ; toute relance d'un flash
repasse par cette confirmation. Pilotes : seul passage par le worker
élevé (`install-unisoc-drivers --zip --sha256`, événement
`drivers_result`), fonction injectée par `MainWindow`
(`set_installateur_pilotes`), le worker revérifie la SHA-256 du zip.
Mot de passe : en mémoire seulement, champ vidé dès la lecture.
Jamais redistribué : .pac, archives, mot de passe ; crédit de l'auteur
(propriétaire du dépôt GitHub de `source_url`) et page officielle affichés.

**Repli** : échec de CmdDloader → bouton « Utiliser l'outil graphique »
(UpgradeDownload, chemin du .pac copié dans le presse-papiers, consigne).
La fin de ce flash-là n'est **pas** suivie dans `Log/` (format des lignes
de résultat inconnu) : l'utilisateur lit le résultat dans l'outil.

**Procédures secondaires** : restauration Super désactivée (raison
affichée) -- `ResearchDownload.exe` absent, et la piste CmdDloader
`-Version 0 -SkipFileID <toutes les entrées sauf Super>` écrirait d'autres
partitions à la moindre entrée oubliée ; à n'activer qu'après un essai
contrôlé. Firmware d'origine : téléchargé par l'utilisateur (Google
Drive), puis même moteur ; il lui faut `pac_produit` dans la fiche.

**Piste future, non implémentée** : flash multiplateforme (macOS/Linux)
par `spd_dump` (fourni dans `UnlockBootloader/`), FDL et images extraits
du .pac -- risque de brique trop élevé sans essais, écarté pour l'instant.

**Points à vérifier** (plan de test : `docs/rg-rotate-test-console.md`) :
CmdDloader jamais lancé ; sa sortie peut être mise en mémoire tampon quand
elle n'arrive pas dans une console (progression en bloc à la fin) ; droits
administrateur pour CmdDloader supposés inutiles ; que CmdDloader écrive
bien ses journaux dans `SPRD_Download_Tool/Log/` ; vraie archive (en-têtes chiffrés ou
non) ; Visual C++ inutile sur un Windows vierge ; `pnputil` sans fenêtre.

## Hors périmètre (étape 1)

Analyse de carte SD (`detection_sd` du schéma non affiché), options sans
champ `telechargement` (liens externes ouverts au navigateur uniquement),
systèmes hébergés ailleurs que sur GitHub ou MEGA, ou qui ne s'installent
pas par flash d'image (MinUI : fichiers copiés sur la 2e carte par-dessus
le système d'origine ; TreeFrog UI : `update.zip`),
contribution/soumission au catalogue, cache local des fiches consultées,
sous-commande CLI de diagnostic, dédoublonnage des jeux (détecter qu'un
jeu déjà présent sur la carte correspond à un jeu qu'on s'apprête à
recopier). `pr_creee`/`connecteurs` (diagnostic serveur) ne sont jamais
affichés à l'utilisateur.

## Tests

Toute communication réseau passe par un paramètre `opener` injectable
(`client.py::Opener`, même principe que `identify/rocknix.py`) -- aucun
test de ce package ne fait un appel réseau réel.
