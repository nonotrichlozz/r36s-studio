---
name: Gestion des nouveaux portages PortMaster
alwaysApply: true
---

# Règles de mise à jour des portages PortMaster pour R36S Studio

Lorsque l'utilisateur partage un nouveau portage PortMaster :
1. Ouvre uniquement 36s_studio/data/portmaster_ports.json (ne lis jamais CLAUDE.md, irmware_catalog.py ni irmware_folders.json).
2. Ajoute le nouveau jeu dans la liste "ports" avec les champs exacts : id, 
om, categorie, image (data/port_images/<id>.jpg), lien_telechargement, prerequis, 
otes.
3. Si une image est fournie, copie-la dans 36s_studio/data/port_images/<id>.jpg.
4. Exécute ensuite dans le terminal : git add ., git commit -m "feat(portmaster): ajout du portage [Nom du jeu]" et git push.
5. Réponds toujours en français.
