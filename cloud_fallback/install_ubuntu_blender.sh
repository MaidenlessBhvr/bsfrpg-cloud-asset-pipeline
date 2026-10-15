#!/usr/bin/env bash
# Remote-only authenticated Ubuntu packages. No host/PPA sources or binary URLs.
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" == true && "${AURELIA_REMOTE_EXPERIMENT:-}" == approved_v4_pilot ]]
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 24.04 && "$VERSION_CODENAME" == noble ]]
[[ "$(dpkg --print-architecture)" == amd64 ]]
test -s /usr/share/keyrings/ubuntu-archive-keyring.gpg
dpkg-query -W -f='${Status}\n' ubuntu-keyring | grep -Fx 'install ok installed'
test -z "$(dpkg --verify ubuntu-keyring)"
apt_root="$RUNNER_TEMP/aurelia-ubuntu-apt"
audit="$GITHUB_WORKSPACE/outputs/ubuntu_provenance"
mkdir -p "$apt_root/lists/partial" "$apt_root/archives/partial" "$apt_root/empty" "$audit"
cat > "$apt_root/ubuntu.sources" <<'SOURCES'
Types: deb
URIs: https://archive.ubuntu.com/ubuntu
Suites: noble noble-updates
Components: main universe
Architectures: amd64
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg

Types: deb
URIs: https://security.ubuntu.com/ubuntu
Suites: noble-security
Components: main universe
Architectures: amd64
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
SOURCES
# APT_CONFIG is read first. Ignore machine/PPA config, lists and trusted keyrings.
cat > "$apt_root/apt.conf" <<CONFIG
Dir::Etc::main "/dev/null";
Dir::Etc::parts "$apt_root/empty";
Dir::Etc::sourcelist "$apt_root/ubuntu.sources";
Dir::Etc::sourceparts "$apt_root/empty";
Dir::Etc::trusted "$apt_root/empty/no-global-keyring";
Dir::Etc::trustedparts "$apt_root/empty";
Dir::Etc::preferences "/dev/null";
Dir::Etc::preferencesparts "$apt_root/empty";
Dir::State::lists "$apt_root/lists";
Dir::Cache::archives "$apt_root/archives";
Dir::Cache::pkgcache "";
Dir::Cache::srcpkgcache "";
Acquire::Retries "0";
Acquire::http::Timeout "30";
Acquire::https::Timeout "30";
Acquire::https::Verify-Peer "true";
Acquire::https::Verify-Host "true";
Acquire::AllowInsecureRepositories "false";
Acquire::AllowWeakRepositories "false";
Acquire::AllowDowngradeToInsecureRepositories "false";
Acquire::Check-Valid-Until "true";
Acquire::Check-Date "true";
APT::Get::AllowUnauthenticated "false";
APT::Update::Error-Mode "any";
Debug::Acquire::gpgv "true";
CONFIG
export APT_CONFIG="$apt_root/apt.conf"
cp "$APT_CONFIG" "$audit/apt.conf"
cp "$apt_root/ubuntu.sources" "$audit/ubuntu.sources"
/usr/bin/python3 cloud_fallback/verify_ubuntu_package.py --stage sources --audit-dir "$audit"
sudo env APT_CONFIG="$APT_CONFIG" apt-get update 2>&1 | tee "$audit/apt_update.log"
# Candidate drift is a hard stop, not a silent version change.
/usr/bin/python3 cloud_fallback/verify_ubuntu_package.py --stage candidate --audit-dir "$audit"
sudo env APT_CONFIG="$APT_CONFIG" apt-get --download-only --reinstall --no-install-recommends -y install \
  blender=4.0.2+dfsg-1ubuntu8 python3-pil 2>&1 | tee "$audit/apt_download.log"
/usr/bin/python3 cloud_fallback/verify_ubuntu_package.py --stage download --audit-dir "$audit" --archives "$apt_root/archives"
sudo env APT_CONFIG="$APT_CONFIG" apt-get --no-download --reinstall --no-install-recommends -y install \
  blender=4.0.2+dfsg-1ubuntu8 python3-pil 2>&1 | tee "$audit/apt_install.log"
/usr/bin/python3 cloud_fallback/verify_ubuntu_package.py --stage installed --audit-dir "$audit"
# Retain signed repository evidence, never the large .deb archives.
find "$apt_root/lists" -maxdepth 1 -name '*InRelease' -exec cp -- {} "$audit/" \;
