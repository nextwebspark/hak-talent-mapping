#!/usr/bin/env bash
# Scrape all AE sectors that haven't been done yet.
# Already completed: Automobiles & Auto Parts, Retailers, Academic & Educational Services,
#                    Applied Resources, Banking & Investment Services

set -uo pipefail

SECTORS=(
    "Cyclical Consumer Services"
    "Industrial & Commercial Services"
    "Industrial Goods"
    "Institutions, Associations & Organizations"
    "Insurance"
    "Investment Holding Companies"
    "Mineral Resources"
    "Personal & Household Products & Services"
    "Pharmaceuticals & Medical Research"
    "Real Estate"
    "Renewable Energy"
    "Software & IT Services"
    "Technology Equipment"
    "Telecommunications Services"
    "Cyclical Consumer Products"
    "Transportation"
    "Utilities"
)

source .venv/bin/activate

for sector in "${SECTORS[@]}"; do
    echo ""
    echo "========================================"
    echo "Scraping: $sector"
    echo "========================================"
    # Retry up to 3 times on failure (e.g. transient Supabase errors)
    for attempt in 1 2 3; do
        python scripts/run_scraper.py listings --country AE --sector "$sector" && break
        echo "Attempt $attempt failed for '$sector', retrying..."
        sleep 5
    done
done

echo ""
echo "All sectors complete."
