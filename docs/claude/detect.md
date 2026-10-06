# `detect/` — statut des étapes du mode expert

À lire quand tu touches à `detect/` ou aux badges de statut des six étapes A→F du mode expert.

> Les renvois « §N » de ce texte désignent les sections de l'ancien `CLAUDE.md` monolithique (commit `930f3c9`) : §3 → `elevation-macos.md`, §4.1/§4.2 → `devices-safety.md`, §4.3 → `imaging.md`/`reset-card.md`, §4.4 → `partitions.md`, §4.5 → `detect.md`, §4.6 → `firmwares-flash.md`, §5 → `interface.md`/`assisted-wizard.md`, §6 → `packaging.md`, §8 → `testing.md` ; §1/§2/§9 restent dans `CLAUDE.md`.

**Retiré, ne pas réintroduire** : `CardState`/`detect_card_state` (un état unique de « la » carte branchée n'a pas de sens sur un parcours à deux cartes).

Le module `detect` ne décide donc plus *quoi* mettre en avant — il indique
seulement, pour chacune des six étapes ci-dessous, un statut informatif :

```python
class StepStatus(Enum):
    AVAILABLE      # faisable
    DONE           # déjà faite
    NOT_RELEVANT   # non pertinente pour la carte actuellement branchée
```

Les six étapes (§4.6) restent **toujours toutes visibles et cliquables** — le statut
guide le débutant, il ne masque et ne verrouille jamais rien : un utilisateur averti
garde toujours la main, y compris pour refaire une étape déjà marquée « faite » ou
en tenter une marquée « non pertinente ».

`detect_workflow_status(device)` réutilise `partitions.locate.list_partitions()`
(déjà en lecture seule) et `has_boot_partition`/`has_easyroms_partition`/
`looks_like_arkos` pour déterminer, à partir de la carte *actuellement* branchée,
quelles étapes ont un sens maintenant (ex. : injecter le BOOT ne veut rien dire sur
une carte pas encore flashée) et lesquelles sont déjà accomplies (une archive
existe déjà pour l'extraction ; la carte est déjà ArkOS pour le flash). Aucune
écriture, aucun montage en écriture — ce module doit pouvoir tourner sans
privilèges élevés autant que possible. Toute erreur de lecture (OS non supporté,
carte débranchée entre-temps) retombe sur un statut prudent plutôt que de lever —
l'appli ne doit jamais planter sur une détection ratée.

**Cas non couvert** : plusieurs cartes candidates branchées à la fois — on ne peut
pas savoir laquelle des six étapes concerne. Décision : `detect_workflow_status`
reçoit alors `None` (comme pour aucune carte), tout est marqué « non pertinent »,
mais les six étapes restent affichées normalement — l'écran Choix du périphérique
les liste toutes.

**Statut `PLATFORM_LIMITED`** : `copy_games` (étape E) sur macOS, dont le pilote NTFS intégré est en lecture seule. Prioritaire sur le calcul habituel, badge orange « PC ou Linux ». La limitation n'est levée que si `partitions/locate.py::selected_easyroms_partition` confirme *positivement* un système de fichiers autre que NTFS (ex. exFAT) sur la carte actuellement branchée ; par défaut (aucune carte, ou EASYROMS non identifiable), le badge reste affiché. Voir `partitions.md` (EASYROMS en exFAT).

**`CardSystem` (phase 8) : reconnaissance ROCKNIX, distincte du
`CardState` retiré ci-dessus.** Le mode assisté cherchait une structure
BOOT/EASYROMS façon ArkOS sur *toute* carte source, y compris une carte
déjà flashée avec ROCKNIX (dépôt alternatif proposé au choix du firmware,
§5 étape de flash) — ne la trouvant pas dans la forme attendue, le
parcours guidé échouait avec des messages pensés pour ArkOS
(« carte fraîchement flashée », erreur de partition introuvable...), sans
jamais expliquer ce qui avait réellement été trouvé.

**Structure ROCKNIX relevée sur du vrai matériel** : schéma MBR, deux
partitions seulement — la première étiquetée `ROCKNIX` en FAT32
(~2,1 Go), la seconde Linux (~29,8 Go), opaque depuis macOS/Windows.
Aucune partition de jeux séparée : les ROMs vivent dans la partition
Linux. Conséquence directe : les quatre étapes A (extract_boot), B
(extract_easyroms), D (inject_boot) et E (copy_games) n'ont **aucun**
sens sur une carte ROCKNIX, pas seulement le BOOT comme envisagé dans une
première version de cette note — seuls le flash (C), la sauvegarde
complète de l'image disque (§4.6, en dehors des six étapes lettrées) et
l'éjection (F) restent pertinents.

`CardSystem` (`ARKOS`/`ROCKNIX`/`UNKNOWN`) répond à une question plus
étroite que le `CardState` retiré (ci-dessus) : pas « quelle action
unique mettre en avant sur toute l'appli », mais « quel système est déjà
sur cette carte, pour adapter les étapes qui n'ont de sens que pour
ArkOS ». `detect_card_system(partitions)` reconnaît ROCKNIX par
l'étiquette de sa partition de démarrage (`ROCKNIX_BOOT_LABEL`, un signal
fort et gratuit — contrairement à ArkOS, dont la partition BOOT n'a
jamais d'étiquette, §4.4) ; ArkOS reste reconnu par `looks_like_arkos`
(vérifié après ROCKNIX, dont la structure ne recouvre de toute façon
jamais celle d'ArkOS). Ni l'un ni l'autre → `UNKNOWN`. Toujours en
lecture seule, jamais de montage — même garantie que le reste de ce
module.

**Mode expert** : `detect_workflow_status` marque désormais les quatre
étapes A/B/D/E `StepStatus.SYSTEM_INCOMPATIBLE` (prioritaire sur le
calcul habituel, et sur `PLATFORM_LIMITED` pour `copy_games` — la vraie
raison sur une carte ROCKNIX est l'absence de partition de jeux, pas la
limitation NTFS de macOS, moins précise ici) quand la carte est ROCKNIX.
Badge violet visible « Non applicable — carte ROCKNIX », plutôt que
`NOT_RELEVANT` (qui n'affiche pas de badge visible, ci-dessus) : sur une
carte reconnue et un système *connu* qui ne convient pas, l'utilisateur
doit comprendre pourquoi, pas juste que « ce n'est pas pertinent
maintenant » comme s'il suffisait d'attendre.

**Retiré, ne pas réintroduire** : `detect_card_system_for_device` (adaptation ROCKNIX de l'ancien parcours guidé). `CardSystem`/`detect_card_system`/`ROCKNIX_BOOT_LABEL` restent utilisés par `detect_workflow_status` (badges `SYSTEM_INCOMPATIBLE`).

**EmuELEC (`CardSystem.EMUELEC`, `EMUELEC_BOOT_LABEL`)** — bug corrigé :
l'étape A sur une carte EmuELEC saine finissait en « Impossible de trouver
les fichiers de la console sur cette carte. As-tu bien préparé cette
carte avec R36S Studio ? » + « Partition "BOOT" introuvable ». Cause : sa
forme (FAT32 `EMUELEC` en tête, Linux, FAT32 `STORAGE` en troisième,
structure relevée dans `firmwares-flash.md`) passe `looks_like_arkos`, la
carte était donc prise pour ArkOS. Reconnue désormais à l'étiquette de sa
partition de démarrage, **avant** ArkOS, comme ROCKNIX
(`_SYSTEM_BY_BOOT_LABEL`) ; `OTHER_SYSTEMS` = ROCKNIX + EmuELEC.
`detect_card(device)` renvoie `(CardSystem, statuts)` pour que le badge et
le bandeau nomment le système (« Non applicable — carte EmuELEC »,
« Carte EmuELEC reconnue » plutôt que « Carte non préparée ») ;
`detect_workflow_status` en reste l'enveloppe sans le système.

**Refus avant lancement des étapes A/B/D/E (`arkos_step_refusal(device,
step)`)** — exception voulue au principe « le statut informe, ne verrouille
jamais » ci-dessus, pour ces quatre étapes seulement : les lignes restent
visibles et cliquables, mais le choix de la carte est refusé avec un
message clair (`step_refused_card_system` / `error_card_system_incompatible`)
avant la fenêtre de dossier et toute demande de mot de passe
(`main_window._refuse_non_arkos_card`), puis revérifié par le worker (code
`CARD_SYSTEM_INCOMPATIBLE`, `__main__._refuse_non_arkos_card`). Refusé :
un système de `OTHER_SYSTEMS`, ou — sur toute autre carte lisible — l'absence
de la partition dont l'étape a besoin (BOOT pour A/D, EASYROMS pour B/E),
c.-à-d. exactement les cas où le worker aurait échoué sur une partition
introuvable. **Pas un refus de toute carte non ArkOS** : l'étape A sur la
carte d'origine d'une console (une seule partition FAT, jamais ArkOS)
reste possible. Partitions illisibles → pas de refus, le worker tranche.
