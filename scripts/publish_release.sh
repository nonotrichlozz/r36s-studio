#!/bin/sh
# Publie une Release brouillon SANS ses fichiers (docs/claude/packaging.md).
#
# Usage : scripts/publish_release.sh v0.2.0
#
# Ordre attendu : télécharger les installeurs du brouillon (créé par
# .github/workflows/release.yml), les mettre en vente sur la boutique, puis
# lancer ce script. Il supprime tous les fichiers attachés, vérifie qu'il
# n'en reste aucun (sinon s'arrête sans publier), puis publie la Release :
# le code et les notes deviennent publics, jamais les installeurs.
set -eu

TAG="${1:?Usage : $0 <tag>  (ex. v0.2.0)}"

if [ "$(gh release view "$TAG" --json isDraft --jq .isDraft)" != "true" ]; then
    echo "La Release $TAG n'est pas un brouillon : rien à faire, arrêt." >&2
    exit 1
fi

gh release view "$TAG" --json assets --jq '.assets[].name' | while IFS= read -r asset; do
    [ -n "$asset" ] || continue
    echo "Suppression : $asset"
    gh release delete-asset "$TAG" "$asset" --yes
done

REMAINING="$(gh release view "$TAG" --json assets --jq '.assets | length')"
if [ "$REMAINING" != "0" ]; then
    echo "Il reste $REMAINING fichier(s) attaché(s) à $TAG : publication refusée." >&2
    gh release view "$TAG" --json assets --jq '.assets[].name' >&2
    exit 1
fi

gh release edit "$TAG" --draft=false
echo "Release $TAG publiée, sans fichier attaché."
