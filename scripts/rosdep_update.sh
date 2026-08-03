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
# Resolve and install system dependencies for the packages we build.
#
#   ./scripts/rosdep_update.sh
#
# Idempotent: safe to re-run.

set -euo pipefail

WS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${WS}"

PORTAL_DIR="src/externals/ros-portal"
ROS_DISTRO="${ROS_DISTRO:-jazzy}"

# The ROS setup files read unset variables (AMENT_TRACE_SETUP_FILES), which is
# fatal under `set -u`. Drop -u across the source, then restore it.
set +u
# shellcheck disable=SC1090
source "/opt/ros/${ROS_DISTRO}/setup.bash"
set -u

# -------------------------------------------------------------------------
# System dependencies.
#
# Scoped to the packages we actually build rather than `--from-paths src`, so
# the portal's turtlesim tutorials and test fixtures do not drag their
# dependencies onto the robot.
# -------------------------------------------------------------------------
echo "==> Installing system dependencies"
rosdep update --rosdistro "${ROS_DISTRO}"
apt-get update
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
    "${PORTAL_DIR}/src/ros_portal" \
    "${PORTAL_DIR}/src/ros_portal_config" \
    "${PORTAL_DIR}/src/ros_portal_msgs" \
    "${PORTAL_DIR}/src/externals/ros2_medkit/src/ros2_medkit_cmake" \
    "${PORTAL_DIR}/src/externals/ros2_medkit/src/ros2_medkit_serialization"

#  rosdep install --from-paths src/ros_portal src/ros_portal_config \
# src/ros_portal_msgs src/externals/ros2_medkit/src/ros2_medkit_cmake \
# src/externals/ros2_medkit/src/ros2_medkit_serialization --ignore-src -r -y --rosdistro \"${ROS_DISTRO}\" --skip-keys ament_cmake_clang_tidy

echo "==> Done. Build with:"
echo "    bros    # inside the container: rosdep + colcon build + re-source"
