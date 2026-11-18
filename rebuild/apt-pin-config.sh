#!/bin/bash
# Check the local release metadata after every builder or live-build APT refresh.
set -euo pipefail
here=$(dirname -- "$0")
source "$here/inputs.env"
echo 'APT::Update::Error-Mode "any";'
while read -r digest index; do
    case "$index" in
        trixie.InRelease|trixie-updates.InRelease) mirror=$DEBIAN_SNAPSHOT ;;
        trixie-security.InRelease) mirror=$SECURITY_SNAPSHOT ;;
        *) exit 1 ;;
    esac
    [[ $digest =~ ^[0-9a-f]{64}$ && $mirror =~ ^https://snapshot\.debian\.org/archive/(debian|debian-security)/[0-9]{8}T[0-9]{6}Z$ ]]
    mirror=${mirror#https://}
    path="/var/lib/apt/lists/${mirror//\//_}_dists_${index%.InRelease}_InRelease"
    printf 'APT::Update::Post-Invoke { "echo %s  %s | sha256sum --check --status"; };\n' "$digest" "$path"
done < "$here/InRelease.sha256"
