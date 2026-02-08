#!/usr/bin/env bash
set -euo pipefail

# generateVersion.sh - Generate version metadata using GitVersion (via Docker or local install)
# Usage: ./scripts/generateVersion.sh
# Requirements: docker OR gitversion, and jq

# Optional: set GITVERSION_IMAGE to use a different GitVersion Docker image
GITVERSION_IMAGE="gittools/gitversion:6.3.0"

clean_up() {
  [[ -n "${TMP_FILE:-}" && -f "$TMP_FILE" ]] && rm -f "$TMP_FILE"
}
trap clean_up EXIT

echo "Fetching tags..."
git fetch --tags

# Prepare temp file for json output
TMP_FILE=$(mktemp)

if command -v docker >/dev/null 2>&1; then
  echo "Running GitVersion (Docker): $GITVERSION_IMAGE"
  docker run --rm -v "$(pwd):/repo" "$GITVERSION_IMAGE" /repo /output json > "$TMP_FILE"
elif command -v gitversion >/dev/null 2>&1; then
  echo "Running GitVersion (local)"
  gitversion /output json > "$TMP_FILE"
else
  echo "Error: Docker or gitversion binary is required to run GitVersion." >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "Error: jq is required to parse GitVersion JSON output. Install it (e.g., 'brew install jq')." >&2
  exit 1
fi

# Parse values with jq
SEMVER=$(jq -r '.SemVer // empty' "$TMP_FILE")
FULL_SEMVER=$(jq -r '.FullSemVer // empty' "$TMP_FILE")
MAJOR_MINOR_PATCH=$(jq -r '.MajorMinorPatch // empty' "$TMP_FILE")
GIT_HASH=$(jq -r '.Sha // empty' "$TMP_FILE")
GIT_TAG=$(jq -r '.PreReleaseTag // empty' "$TMP_FILE")
GIT_BRANCH=$(jq -r '.BranchName // empty' "$TMP_FILE")
COMMIT_COUNT=$(jq -r '.CommitsSinceVersionSource // 0' "$TMP_FILE")

# Fallbacks
SEMVER=${SEMVER:-"0.0.0"}
FULL_SEMVER=${FULL_SEMVER:-"0.0.0+0"}
MAJOR_MINOR_PATCH=${MAJOR_MINOR_PATCH:-"0.0.0"}

# Replace 'PullRequest' with 'Patch' in SemVer (per original script behaviour)
VERSION=${SEMVER//PullRequest/Patch}

BUILD_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Remove any existing version-*.txt files in current dir
rm -f version-*.txt || true

VERSION_FILE="version-$VERSION.txt"
cat > "$VERSION_FILE" <<EOF
version=$VERSION
major_minor_patch=$MAJOR_MINOR_PATCH
full_semver=$FULL_SEMVER
git_hash=$GIT_HASH
git_tag=$GIT_TAG
git_branch=$GIT_BRANCH
commit_count=$COMMIT_COUNT
build_date=$BUILD_DATE
EOF

# Output to console
echo "Generated version: $VERSION"
echo "Major minor patch: $MAJOR_MINOR_PATCH"
echo "Full semver: $FULL_SEMVER"
echo "Git hash: $GIT_HASH"
echo "Git tag: $GIT_TAG"
echo "Git branch: $GIT_BRANCH"
echo "Commit count: $COMMIT_COUNT"
echo "Build date: $BUILD_DATE"
echo "\n$VERSION_FILE content:"
cat "$VERSION_FILE"

echo "Done."
