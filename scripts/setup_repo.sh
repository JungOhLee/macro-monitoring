#!/usr/bin/env bash
# One-time repo setup: labels + Pages source. Idempotent.
set -euo pipefail
REPO="JungOhLee/macro-monitoring"

for label in "alert:regime|d64545|Composite regime band changed" \
             "alert:pillar-valuation|e07b3c|Valuation pillar >90" \
             "alert:pillar-leverage|e07b3c|Leverage pillar >90" \
             "alert:pillar-liquidity|e07b3c|Liquidity pillar >90" \
             "alert:pillar-sentiment|e07b3c|Sentiment pillar >90" \
             "alert:pillar-macro|e07b3c|Macro pillar >90" \
             "alert:stage-1|b60205|Seq stage 1 fired" "alert:stage-2|b60205|Seq stage 2 fired" \
             "alert:stage-3|b60205|Seq stage 3 fired" "alert:stage-4|b60205|Seq stage 4 fired" \
             "alert:stage-5|b60205|Seq stage 5 fired" "alert:stage-6|b60205|Seq stage 6 fired" \
             "data-health|fbca04|Series staleness / ingest failures"; do
  IFS="|" read -r name color desc <<<"$label"
  gh label create "$name" --repo "$REPO" --color "$color" --description "$desc" --force
done

# Pages: build via Actions workflow
gh api -X POST "repos/$REPO/pages" -f build_type=workflow 2>/dev/null \
  || gh api -X PUT "repos/$REPO/pages" -f build_type=workflow
echo "setup complete"
