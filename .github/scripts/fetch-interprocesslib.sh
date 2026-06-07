#!/usr/bin/env bash
# Provision InterprocessLib.FrooxEngine.dll for CI mod builds.
#
# The engine-side Camera v2 receiver (mod/src/ResoniteIO/Bridge/
# RendererFrameInterprocessReceiver.cs) compiles against the `InterprocessLib`
# namespace (Nytra-InterprocessLib). Locally this DLL is supplied by the Gale
# profile; ResoniteIO.csproj references it conditionally from
#   $(GalePath)BepInEx/plugins/Nytra-InterprocessLib/InterprocessLib.BepisLoader/
# with GalePath defaulting to the repo-root ./gale/ directory.
#
# CI has no Gale profile and there is no NuGet fallback for InterprocessLib
# (unlike FrooxEngine/Elements/SkyFrost, which Resonite.GameLibs supplies), so
# the Thunderstore PackTS build fails to compile without this step. We fetch the
# pinned package straight from Thunderstore and drop the DLL where the csproj
# condition expects it. The version is read from mod/thunderstore.toml so the
# build dependency and the published dependency stay in lockstep.
set -euo pipefail

IPL_VERSION="$(grep -oP 'Nytra-InterprocessLib = "\K[^"]+' mod/thunderstore.toml)"
if [ -z "${IPL_VERSION}" ]; then
  echo "::error::Could not read Nytra-InterprocessLib version from mod/thunderstore.toml"
  exit 1
fi

DEST="gale/BepInEx/plugins/Nytra-InterprocessLib/InterprocessLib.BepisLoader"
ZIP="$(mktemp --suffix=.zip)"

echo "Fetching Nytra-InterprocessLib ${IPL_VERSION} from Thunderstore"
curl -fsSL -o "${ZIP}" \
  "https://thunderstore.io/package/download/Nytra/InterprocessLib/${IPL_VERSION}/"

mkdir -p "${DEST}"
unzip -o -j "${ZIP}" \
  "plugins/InterprocessLib.BepisLoader/InterprocessLib.FrooxEngine.dll" -d "${DEST}"

echo "Placed InterprocessLib.FrooxEngine.dll at ${DEST}/"
