#!/usr/bin/env bash
# Re-tag script: mapea tags antiguos a nuevos sin borrar los originales.
#
# Uso:
#   bash scripts/retag_to_semver.sh
#
# Lo que hace:
#   - Crea nuevos tags semver (v0.4.0, v0.3.2, etc.) apuntando a los mismos
#     commits que los tags antiguos (v3.2.7, v3.2.6, ...).
#   - NO elimina los tags antiguos (quedan como referencia histórica).
#   - Empuja los nuevos tags a origin.
#
# IMPORTANTE: este script asume que estás en el directorio raíz del repo
# y que los tags antiguos existen en local y remoto.

set -euo pipefail

# Verificar que estamos en un repo git
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    echo "❌ No estás en un repositorio git."
    exit 1
fi

echo "🏷️  Mapeo de tags antiguos → nuevos (semver honesto)"
echo ""

# Mapeo: tag_antiguo → tag_nuevo
declare -A MAPEO=(
    ["v3.2.7"]="v0.4.0"
    ["v3.2.6"]="v0.3.2"
    ["v3.2.5"]="v0.3.1"
    ["v3.2.4"]="v0.3.0"
    ["v3.2.3"]="v0.2.0"
    ["v3.0.0"]="v0.1.0"
)

for tag_antiguo in "${!MAPEO[@]}"; do
    tag_nuevo="${MAPEO[$tag_antiguo]}"

    # Verificar que el tag antiguo exista
    if ! git rev-parse "$tag_antiguo" > /dev/null 2>&1; then
        echo "⚠️  $tag_antiguo no existe en local — saltando"
        continue
    fi

    # Verificar que el tag nuevo NO exista todavía
    if git rev-parse "$tag_nuevo" > /dev/null 2>&1; then
        echo "ℹ️  $tag_nuevo ya existe — saltando ($tag_antiguo → $tag_nuevo)"
        continue
    fi

    commit=$(git rev-parse "$tag_antiguo")
    echo "  $tag_antiguo ($commit) → $tag_nuevo"

    # Crear tag nuevo apuntando al mismo commit (annotated)
    git tag -a "$tag_nuevo" "$commit" -m "Re-tag from $tag_antiguo (semver reset 2026-05-26)"
done

echo ""
echo "✅ Tags creados localmente. Para publicarlos:"
echo ""
for tag_nuevo in $(echo "${MAPEO[@]}" | tr ' ' '\n' | sort); do
    echo "   git push origin $tag_nuevo"
done
echo ""
echo "O todos a la vez:"
echo "   git push origin --tags"
echo ""
echo "Tags antiguos (v3.2.X) se preservan — NO se eliminan."
