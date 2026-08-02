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
# Populate src/externals/ and install system dependencies.
#
#   ./scripts/setup-workspace.sh          # both stages (what you want by hand)
#   ./scripts/setup-workspace.sh import   # clone dependencies only
#   ./scripts/setup-workspace.sh deps     # resolve rosdep only
#
# The two stages are separable so the Dockerfile can clone dependencies in a
# layer that does not depend on src/, and therefore does not re-clone every
# time a source file changes.
#
# Idempotent: safe to re-run.

set -euo pipefail

STAGE="${1:-all}"
case "${STAGE}" in
  all|import|deps) ;;
  *) echo "usage: $0 [all|import|deps]" >&2; exit 2 ;;
esac

WS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${WS}"

BRIDGE="src/externals/ros2-livekit-bridge"
ROS_DISTRO="${ROS_DISTRO:-jazzy}"

# shellcheck disable=SC1090
source "/opt/ros/${ROS_DISTRO}/setup.bash"

if [ "${STAGE}" = "all" ] || [ "${STAGE}" = "import" ]; then
  # -------------------------------------------------------------------------
  # Our own dependencies.
  # -------------------------------------------------------------------------
  echo "==> Importing waver.repos into src/externals/"
  mkdir -p src/externals
  vcs import --recursive --skip-existing src/externals < waver.repos

  # -------------------------------------------------------------------------
  # The bridge's dependencies.
  #
  # ros2-livekit-bridge is itself a colcon workspace with its own
  # external.repos (client-sdk-cpp pinned to the livekit-capture branch,
  # cpp-tools, ros2_medkit). `vcs import --recursive` recurses into git
  # submodules, NOT into nested .repos files, so the inner import has to be
  # run explicitly.
  # -------------------------------------------------------------------------
  echo "==> Importing ${BRIDGE}/external.repos"
  mkdir -p "${BRIDGE}/src/externals"
  vcs import --recursive --skip-existing "${BRIDGE}/src/externals" < "${BRIDGE}/external.repos"
  (cd "${BRIDGE}" && ./scripts/apply-external-patches.sh)

  # -------------------------------------------------------------------------
  # Hide packages we pull in transitively but never build.
  #
  # cobra_flex is a different robot that happens to live in the bridge's test
  # tree; map_merge does not build against current Nav2. Without these markers
  # colcon discovers them and rosdep tries to resolve their dependencies.
  # -------------------------------------------------------------------------
  for ignore in \
    "${BRIDGE}/src/test/cobra_flex" \
    "src/externals/m-explore-ros2/map_merge"
  do
    [ -d "${ignore}" ] && touch "${ignore}/COLCON_IGNORE"
  done
fi

if [ "${STAGE}" = "all" ] || [ "${STAGE}" = "deps" ]; then
  # -------------------------------------------------------------------------
  # System dependencies.
  #
  # Scoped to the packages we actually build rather than `--from-paths src`, so
  # the bridge's turtlesim tutorials and test fixtures do not drag their
  # dependencies onto the robot.
  # -------------------------------------------------------------------------
  echo "==> Installing system dependencies"
  rosdep update --rosdistro "${ROS_DISTRO}"
  rosdep install -y -r --ignore-src --rosdistro "${ROS_DISTRO}" \
    --skip-keys ament_cmake_clang_tidy \
    --from-paths \
      src/waver_bringup \
      src/waver_driver \
      src/waver_localization \
      src/waver_navigation \
      src/waver_simulation \
      src/vendor/waver_description \
      src/vendor/waver_gazebo \
      src/externals/rf2o_laser_odometry \
      src/externals/rplidar_ros \
      "${BRIDGE}/src/ros_portal" \
      "${BRIDGE}/src/ros_portal_config" \
      "${BRIDGE}/src/ros_portal_msgs" \
      "${BRIDGE}/src/externals/ros2_medkit/src/ros2_medkit_cmake" \
      "${BRIDGE}/src/externals/ros2_medkit/src/ros2_medkit_serialization"
fi

echo "==> Done. Build with:"
echo "    colcon build --packages-up-to waver_bringup"
