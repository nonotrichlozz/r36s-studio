# `devices/` et `safety/` — détection et filtrage des cartes

À lire quand tu touches à la détection des cartes (`devices/`) ou au garde-fou (`safety/`).

> Les renvois « §N » de ce texte désignent les sections de l'ancien `CLAUDE.md` monolithique (commit `930f3c9`) : §3 → `elevation-macos.md`, §4.1/§4.2 → `devices-safety.md`, §4.3 → `imaging.md`/`reset-card.md`, §4.4 → `partitions.md`, §4.5 → `detect.md`, §4.6 → `firmwares-flash.md`, §5 → `interface.md`/`assisted-wizard.md`, §6 → `packaging.md`, §8 → `testing.md` ; §1/§2/§9 restent dans `CLAUDE.md`.

> 📚 Historique détaillé (bugs corrigés, investigations) : `docs/bugs-devices-partitions.md`

### 4.1 `devices/` — détection des cartes SD

Une implémentation par OS, une interface commune retournant une liste de :

```python
@dataclass
class Device:
    path: str          # \\.\PhysicalDrive2 | /dev/disk4 | /dev/sdb
    display: str       # "SanDisk Ultra 128 Go"
    size_bytes: int
    removable: bool
    bus: str           # "USB", "SD", "NVMe"…
    is_system: bool    # contient l'OS en cours ?
    mountpoints: list[str]
```

| OS | Commande source |
|----|-----------------|
| Linux | `lsblk -J -b -o PATH,SIZE,MODEL,VENDOR,RM,HOTPLUG,TRAN,TYPE,MOUNTPOINTS` |
| macOS | `diskutil list -plist external physical` puis `diskutil info -plist diskN` |
| Windows | PowerShell `Get-Disk \| ConvertTo-Json` + `Get-Partition` pour les lettres |

Sous Windows, `devices/windows.py::list_devices` croise `Get-Disk` avec
`Win32_DiskDrive.MediaType` (`Get-CimInstance`, par index de disque) pour
déterminer si un disque est amovible quand `Get-Disk.IsRemovable` est absent
(`$null`, pas `$false`) — le cas d'un lecteur de carte SD intégré (bus `SCSI`,
pas `USB`). Utilisé seulement en complément, jamais pour contredire une valeur
explicite ; le repli `bus == "USB"` reste le dernier recours.

`_LIST_DEVICES_COMMAND` combine les trois requêtes en une seule invocation
PowerShell (`@{ Disks = …; Partitions = …; Drives = … } | ConvertTo-Json`)
plutôt que trois processus séquentiels -- chacun coûtant de quelques
centaines de ms à plus d'une seconde à démarrer, plus sensible sur un
binaire empaqueté, le cumul pouvait dépasser le seuil du chien de garde de
sondage du parcours de clonage (§5) à chaque tick, empêchant en pratique
la détection automatique d'une carte insérée (bug corrigé, confirmé).

### 4.2 `safety/` — le garde-fou

Un périphérique est **refusé** si l'une de ces conditions est vraie :

- `is_system` est vrai, ou il contient la partition de démarrage
- il contient le dossier d'où l'application s'exécute
- `removable` est faux **et** `bus` n'est pas USB
- `size_bytes` dépasse un seuil configurable (défaut : 1 To)
- `size_bytes` est nul ou inconnu

Un périphérique refusé n'apparaît pas dans la liste — il ne suffit pas de le griser.
Aucune sélection par défaut : l'utilisateur choisit toujours activement.

**Diagnostic dans le journal** : `safety.describe_rejection` (nouveau,
mêmes règles que `is_allowed` mais avec la raison) permet à
`_list_devices_with_diagnostics` de tracer, à chaque sondage dont le
résultat change, combien de cartes sont retenues et lesquelles sont
écartées et pourquoi (« carte système », « ni amovible ni en USB »...)
— dédoublonné par signature pour ne pas noyer le journal d'une ligne
toutes les 1,5 s en attendant une carte.
