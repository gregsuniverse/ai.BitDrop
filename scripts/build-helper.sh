#!/usr/bin/env bash
set -euo pipefail
project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
upstream_commit=6f2e8ea99aed0687558d78a1dd49154ab3a5fa76
mkdir -p "$project_root/build"
source_dir=$(mktemp -d "$project_root/build/upstream.XXXXXX")
trap 'rm -rf -- "$source_dir"' EXIT
git -C "$source_dir" init -q
git -C "$source_dir" remote add origin https://github.com/t4t5/owly.git
git -C "$source_dir" fetch --depth=1 origin "$upstream_commit"
git -C "$source_dir" checkout -q --detach FETCH_HEAD
test "$(git -C "$source_dir" rev-parse HEAD)" = "$upstream_commit"
git -C "$source_dir" apply --check "$project_root/patches/desktop-events.patch"
git -C "$source_dir" apply "$project_root/patches/desktop-events.patch"
cargo build --manifest-path "$source_dir/Cargo.toml" --release --locked \
    --target-dir "$project_root/build/target" -p owly-cli
install -m755 "$project_root/build/target/release/owly" "$project_root/owly-desktop-helper"
printf 'Built desktop helper from Owly %s\n' "$upstream_commit"
