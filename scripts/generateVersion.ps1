# Ensure GitVersion is installed (you can install via Chocolatey or manually)
# choco install gitversion.portable -y

# Navigate to your repository root
# Set-Location "C:\Path\To\Your\Repository"

# Run GitVersion and output JSON
# $gitVersionOutput = gitversion /output json

# Display the JSON output
# $gitVersionOutput | ConvertFrom-Json | Format-List

# Fetch all tags to ensure GitVersion has the latest tag information
git fetch --tags
# Alternatively, using Docker to run GitVersion without installing it locally
# Run GitVersion via Docker and capture JSON output
$gitVersionJson = docker run --rm -v "${PWD}:/repo" gittools/gitversion:6.3.0 /repo /output json

# Parse JSON
$versionData = $gitVersionJson | ConvertFrom-Json

# Remove any existing version-*.txt files in the current directory
Get-ChildItem -Path . -Filter "version-*.txt" | Remove-Item -Force

# Replace 'PullRequest' with 'Patch' in SemVer
$VERSION = $versionData.SemVer -replace 'PullRequest', 'Patch'
$FULL_SEMVER = $versionData.FullSemVer
$MAJOR_MINOR_PATCH = $versionData.MajorMinorPatch
$GIT_HASH = $versionData.Sha
$GIT_TAG = $versionData.PreReleaseTag
$GIT_BRANCH = $versionData.BranchName
$COMMIT_COUNT = $versionData.CommitsSinceVersionSource
$BUILD_DATE = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")

# Write to version-$VERSION.txt
$versionFile = "version-$VERSION.txt"
@"
version=$VERSION
major_minor_patch=$MAJOR_MINOR_PATCH
full_semver=$FULL_SEMVER
git_hash=$GIT_HASH
git_tag=$GIT_TAG
git_branch=$GIT_BRANCH
commit_count=$COMMIT_COUNT
build_date=$BUILD_DATE
"@ | Set-Content $versionFile

# Output to console
Write-Host "Generated version: $VERSION"
Write-Host "Major minor patch: $MAJOR_MINOR_PATCH"
Write-Host "Full semver: $FULL_SEMVER"
Write-Host "Git hash: $GIT_HASH"
Write-Host "Git branch: $GIT_BRANCH"
Write-Host "Commit count: $COMMIT_COUNT"
Write-Host "Build date: $BUILD_DATE"
Write-Host "version.txt content:"
Get-Content $versionFile
