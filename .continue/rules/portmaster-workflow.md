---
name: Gestion des nouveaux portages PortMaster
alwaysApply: true
---

# Règles de mise à jour des portages PortMaster pour R36S Studio

Lorsque l'utilisateur partage un lien, une annonce ou le nom d'un nouveau portage PortMaster :
1. Lis CLAUDE.md et repère le fichier du projet qui gère le catalogue ou les sources de jeux/portages.
2. Ajoute le nouveau portage (nom du jeu, lien du dépôt ou de l'archive, fichiers requis) en respectant strictement le format existant du projet.
3. Une fois le fichier modifié, exécute dans le terminal :
   - git status
   - git add .
   - git commit -m "feat(portmaster): ajout du portage [Nom du jeu]"
   - git push
4. Réponds toujours en français.
