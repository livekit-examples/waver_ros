#!/bin/bash

# Copyright 2026 LiveKit
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Clone waver.repos and ROS Portal's external.repos into src/externals/.
#
# Run on the host before `docker compose build` so private repos can use the
# host's SSH agent rather than forwarding keys into the image build.
#
#   ./scripts/setup_repos.sh
#
# Idempotent: safe to re-run.

set -euo pipefail

WS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${WS}"

PORTAL_DIR="src/externals/ros-portal"

# -------------------------------------------------------------------------
# Our own dependencies.
# -------------------------------------------------------------------------
echo "==> Importing waver.repos into src/externals/"
mkdir -p src/externals
vcs import --recursive --skip-existing src/externals < waver.repos

# -------------------------------------------------------------------------
# The portal's dependencies.
#
# ros-portal is itself a colcon workspace with its own
# external.repos (client-sdk-cpp pinned to the livekit-capture branch,
# cpp-tools, ros2_medkit). `vcs import --recursive` recurses into git
# submodules, NOT into nested .repos files, so the inner import has to be
# run explicitly.
# -------------------------------------------------------------------------
echo "==> Importing ${PORTAL_DIR}/external.repos"
mkdir -p "${PORTAL_DIR}/src/externals"
vcs import --recursive --skip-existing "${PORTAL_DIR}/src/externals" < "${PORTAL_DIR}/external.repos"
(cd "${PORTAL_DIR}" && ./scripts/apply-external-patches.sh)

# -------------------------------------------------------------------------
# Hide packages we pull in transitively but never build.
#
# cobra_flex is a different robot that happens to live in the portal's test
# tree; map_merge does not build against current Nav2. Without these markers
# colcon discovers them and rosdep tries to resolve their dependencies.
# -------------------------------------------------------------------------
for ignore in \
  "${PORTAL_DIR}/src/test/cobra_flex" \
  "src/externals/m-explore-ros2/map_merge"
do
  [ -d "${ignore}" ] && touch "${ignore}/COLCON_IGNORE"
done

echo "==> Repos imported. Next:"
echo "    docker compose build"
echo "    docker compose run --rm waver bros"
