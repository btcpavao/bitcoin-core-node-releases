#!/bin/bash
# Called with a fresh, caller-owned directory. Extract only the named public
# release after checking the signed source and source-commit entries.
fetch_release() (
    set -euo pipefail
    local version=$1 destination=$2 source_digest=$3 commit=$4
    local archive="bitcoin-core-node-$version-source.tar.gz"
    local base="https://github.com/btcpavao/bitcoin-core-node-releases/releases/download/$version"
    local file
    mkdir "$destination/files" "$destination/source"
    cd "$destination/files"
    for file in "$archive" SHA256SUMS SHA256SUMS.asc SOURCE-COMMIT.txt; do
        curl --fail --silent --show-error --location --retry 3 --proto '=https' --proto-redir '=https' \
            --output "$file" "$base/$file"
    done
    mkdir -m 700 gnupg
    gpg --no-options --batch --homedir "$PWD/gnupg" --dearmor < "$recipe/../btcpavao-pgp.asc" > release.gpg
    gpg --no-options --batch --homedir "$PWD/gnupg" --no-default-keyring \
        --keyring "$PWD/release.gpg" --no-auto-key-retrieve --status-fd 1 \
        --verify SHA256SUMS.asc SHA256SUMS > status
    awk -v key="$RELEASE_KEY" '$1 == "[GNUPG:]" && $2 == "VALIDSIG" && $NF == key {valid=1} END {exit !valid}' status
    grep -Fx "$source_digest  $archive" SHA256SUMS >/dev/null
    awk -v src="$archive" '$2 == src || $2 == "SOURCE-COMMIT.txt"' SHA256SUMS > required
    test "$(wc -l < required)" = 2
    sha256sum --check --strict required >&2
    test "$(cat SOURCE-COMMIT.txt)" = "$commit"
    tar -xzf "$archive" --no-same-owner --strip-components=1 -C "$destination/source"
)
