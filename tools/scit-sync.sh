#!/usr/bin/env bash
# Enotna koda Scita: datoteke, ki so v Safeer-linux in Safeer-windows ENAKE (platformne razlike so v core/os_scit_windows.py).
# Uporaba:  tools/scit-sync.sh --preveri /pot/do/Safeer-linux     (samo primerja, izhod 1 ob razliki)
#           tools/scit-sync.sh --prenesi /pot/do/Safeer-linux     (kopira Linux -> Windows; ukaz lastnika, ker prepise)
# adblock.py se NE sinhronizira: Windows policy.py prilagaja besedilo skript (adapt_linux_script) in je s tem vezan.
set -euo pipefail
nacin="${1:-}"; linux="${2:-}"
[ -d "$linux/core" ] || { echo "scit-sync: podaj pot do Safeer-linux" >&2; exit 2; }
koren="$(cd "$(dirname "$0")/.." && pwd)"
DATOTEKE="os_scit os_scit_windows scit_gostitelji scit_pravila root_ukaz webtor shramba_json signed_feed threat_intel doh_proxy webkit_filters"
razlike=0
for f in $DATOTEKE; do
  if ! cmp -s "$linux/core/$f.py" "$koren/core/$f.py"; then
    razlike=1; echo "RAZLIKA core/$f.py"
    [ "$nacin" = "--prenesi" ] && cp "$linux/core/$f.py" "$koren/core/$f.py" && echo "  prenesena"
  fi
done
[ "$razlike" = 0 ] && echo "scit-sync: enako"
[ "$nacin" = "--prenesi" ] && exit 0
exit "$razlike"
