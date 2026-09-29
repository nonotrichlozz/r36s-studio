# « Remettre la carte à zéro » (`imaging/reset_card.py`)

À lire quand tu touches à `imaging/reset_card.py`, `cmd_reset_card`, `ResetCardLabelDialog` ou `_format_windows` (partagé avec la partition de jeux).

> Les renvois « §N » de ce texte désignent les sections de l'ancien `CLAUDE.md` monolithique (commit `930f3c9`) : §3 → `elevation-macos.md`, §4.1/§4.2 → `devices-safety.md`, §4.3 → `imaging.md`/`reset-card.md`, §4.4 → `partitions.md`, §4.5 → `detect.md`, §4.6 → `firmwares-flash.md`, §5 → `interface.md`/`assisted-wizard.md`, §6 → `packaging.md`, §8 → `testing.md` ; §1/§2/§9 restent dans `CLAUDE.md`.

> 📚 Historique détaillé (bugs corrigés, investigations) : `docs/bugs-imaging-partitions.md`

**« Remettre la carte à zéro » (§4.3 bis, mode expert uniquement).** Besoin
constaté en usage réel : après des essais de firmware, une carte peut
rester en trois à cinq partitions illisibles pour un PC -- Windows ne sait
pas la remettre simplement en état de carte de stockage normale. Nouvelle
opération : efface toute la table de partitions existante (MBR ou GPT) et
recrée une seule partition exFAT occupant toute la carte.

`imaging/reset_card.py` (nouveau module, délibérément distinct de
`games_partition.py` -- celui-ci *ajoute* une partition à une table
existante, celui-là *remplace* toute la table par une seule partition
neuve, la planification n'a donc pas besoin de lire de table existante)
réutilise les briques déjà en place plutôt que d'en écrire de nouvelles :
`imaging/write_target.py::prepared_write_target` (verrouillage/démontage
par OS, §4.3, identique à `flash_device`/`create_games_partition`) pour
l'écriture, et `imaging/games_partition.py::format_games_partition` (déjà
multiplateforme : `diskutil eraseVolume`/`mkfs.exfat`/PowerShell `Format-
Volume`) pour le formatage natif -- rien de nouveau à maintenir par OS
pour cette dernière étape. Exposé en deux fonctions distinctes plutôt
qu'une seule combinée (§ correctif ci-dessous) :
1. `erase_partition_table` -- efface (zéros) une marge de 1 Mio
   (`ALIGNMENT_SECTORS`) en tête *et* en fin de disque -- une éventuelle
   signature GPT (« EFI PART », LBA1) ou une table secondaire en fin de
   disque ne doit pas pouvoir resurgir une fois le nouveau MBR écrit
   par-dessus le seul LBA0 (un outil qui la retrouverait malgré un MBR
   neuf continuerait de rapporter l'ancien schéma GPT).
2. `create_single_partition` -- écrit un MBR neuf (`build_full_disk_mbr_
   sector` -- contrairement à `rewrite_mbr_with_games_partition`, ne lit
   jamais de secteur existant : tout le reste de la table précédente doit
   disparaître, pas gagner une entrée de plus) avec une unique partition
   alignée occupant tout l'espace restant. Sur Windows uniquement, attend
   ensuite un court instant (§ correctif ci-dessous).

CLI : `python -m r36s_studio reset-card --device X [--label ÉTIQUETTE]`
(`__main__.py::cmd_reset_card`) -- écrit sur le périphérique brut comme
`flash` : même confirmation explicite obligatoire (règle §2 n°6,
réutilise `_confirm_flash` tel quel, son texte générique s'applique sans
changement). Quatre étapes réelles, chacune journalisée avant et après
(effacement, création, formatage, éjection -- voir le correctif
ci-dessous) ; nouveau code d'erreur dédié, `RESET_CARD_FAILED` (carte
trop petite, ou une vraie erreur d'écriture/formatage, avec l'étape en
cause dans le message).

GUI (mode expert uniquement, §5) : troisième ligne sous « Par sécurité »,
à côté des deux sauvegardes -- jamais dans le parcours assisté, une
opération destructrice qui n'en fait pas partie. Carte choisie (fenêtre
habituelle) puis, avant même la fenêtre Confirmation, `screens.
ResetCardLabelDialog` (nouvelle fenêtre) demande l'étiquette du volume --
un champ de texte pré-rempli avec une valeur simple par défaut
(`DEFAULT_RESET_LABEL = "SDCARD"`), jamais imposée, jamais vide (le
bouton Continuer n'émet rien tant que le champ est vide plutôt que de
laisser passer une étiquette vide vers le formatage natif). Fenêtre
Confirmation ensuite, obligatoire, avant toute écriture réelle -- jamais
sautée, exactement comme pour un flash.

Mécanisme actuel des quatre étapes (effacement, création, formatage,
éjection), partagé avec la création de la partition de jeux
(`_format_windows` est la même fonction pour les deux) : sur Windows,
`create_single_partition` attend un court instant après avoir écrit le
nouveau MBR, puis `_format_windows` réessaie `Get-Partition` plusieurs
fois côté PowerShell avant d'abandonner — un échec au-delà de ces
réessais fait sortir le script en erreur explicite (`exit 1`) plutôt que
de réussir silencieusement sans avoir rien fait. Une fois le volume
formaté, `_format_windows` lui assigne la première lettre de lecteur
libre (`Add-PartitionAccessPath -AssignDriveLetter`) et la fait remonter
à l'appelant (`drive_letter` sur `GamesPartitionResult`) ; sur macOS/Linux
(aucune notion de lettre de lecteur), un montage explicite best-effort
(`diskutil mount` / `udisksctl mount -b`) est tenté après le formatage au
cas où l'automontage ne s'en chargerait pas. La progression de ces quatre
étapes est communiquée par un événement dédié (`step_progress`,
`{step_index, step_count, step_name}`) plutôt qu'une barre basée sur un
débit — aucune estimation de temps n'a de sens pour un formatage.

⚠️ **Point non vérifié à ce jour** : la branche Windows de ce mécanisme
est confirmée sur du vrai matériel ; les branches macOS et Linux
(y compris le montage best-effort) ne le sont pas, faute de matériel
disponible lors de leur écriture.

## FAT32 et SF3000HD : ce qui est vérifié

Le choix exFAT/FAT32 a été ajouté après un signalement : une carte de
128 Go pour une SF3000HD, inutilisable après le formatage exFAT alors
systématique. Le code disait depuis « la SF3000HD ne lit que le FAT32 » --
**faux pour la console elle-même**, corrigé le 2026-09-28 :

- **Carte d'origine de la SF3000HD : exFAT**, lue par le menu d'origine
  (inventaire en lecture seule d'une vraie carte d'origine : partition
  unique exFAT, clusters de 64 Kio, début à 16 Kio).
- **Guide d'installation de TreeFrogUI** (`install.md` du dépôt
  tzubertowski/TreeFrogUI) : « format the SD card » pour la SF3000/SF3000 HD,
  sans système de fichiers imposé ; FAT32 **explicitement** exigé
  seulement pour la R36HD (« freshly FAT32-formatted card »).
- **Carte TreeFrogUI de l'utilisateur** : FAT32, étiquette `SDCARD` --
  l'étiquette par défaut de cette remise à zéro, donc très probablement
  formatée ici en FAT32 avant l'installation de TreeFrogUI.

Conclusion retenue : la contrainte FAT32 vient du contexte TreeFrogUI (ou
de la R36HD), pas de la SF3000HD. **Non vérifié** : que TreeFrogUI refuse
réellement une carte exFAT sur SF3000 -- personne ne l'a testé dans ce
projet. FAT32 reste un choix explicite de l'utilisateur, jamais présumé.
