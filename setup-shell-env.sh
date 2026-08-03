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
# Installs a shell profile so every shell in the container has ROS and the
# workspace overlay sourced. Run once at image build time.

set -euo pipefail

cat <<EOF >/etc/profile.d/waver.sh
export ROS_DISTRO=${ROS_DISTRO}
export WS="${WS}"

_source_ros_env() {
    source /opt/ros/${ROS_DISTRO}/setup.bash
}

_source_ws_overlay() {
    if [ -f "\${WS}/install/setup.bash" ]; then
        source "\${WS}/install/setup.bash"
    fi
}

_source_ros_env
_source_ws_overlay

# Functions, not aliases: bash only expands aliases in interactive shells, so an
# alias is invisible to \`bash -lc bros\` and to anything docker execs directly.

# Re-source after a rebuild.
sros() {
    _source_ros_env
    _source_ws_overlay
}

# Build the robot stack (rosdep + colcon).
bros() {
    cd "\${WS}" &&
        ./scripts/rosdep_update.sh &&
        colcon build --packages-up-to waver_bringup &&
        sros
}

# Re-resolve system dependencies after editing a package.xml.
dros() {
    cd "\${WS}" && ./scripts/rosdep_update.sh
}

# Bring the robot up. Pass launch args through, e.g. \`waver teleop_only:=true\`.
waver() {
    ros2 launch waver_bringup waver.launch.xml "\$@"
}

# Camera smoke test: enumerate, then pull 30 frames through libcamerasrc.
# An empty listing means /run/udev is not mounted; "no element libcamerasrc"
# means the image was built without the libcamera stage.
camcheck() {
    cam --list
    gst-launch-1.0 libcamerasrc \
      ! video/x-raw,width=640,height=480,format=NV12,framerate=30/1 \
      ! identity eos-after=30 ! fakesink
}
EOF

chmod 0644 /etc/profile.d/waver.sh

# `docker compose run --rm waver bros` hands its command straight to the image
# entrypoint, which execs it — no shell is involved, so the functions above are
# not in scope. These wrappers give those two commands a PATH entry that starts a
# login shell (sourcing the profile) and then calls the function of the same
# name; a function shadows the PATH entry, so this does not recurse. `sros` gets
# no wrapper: re-sourcing the environment of a subprocess would do nothing.
for _cmd in bros dros; do
    printf '#!/bin/bash -l\n%s "$@"\n' "${_cmd}" >"/usr/local/bin/${_cmd}"
    chmod 0755 "/usr/local/bin/${_cmd}"
done

# /etc/profile.d is only read by login shells, so `docker exec -it waver bash`
# would otherwise land in a shell with no ROS on CMAKE_PREFIX_PATH and colcon
# failing to find ament_cmake. Pull the same profile into interactive
# non-login shells.
cat <<'EOF' >>/root/.bashrc

# Sourced for interactive non-login shells (e.g. `docker exec -it waver bash`);
# login shells get this via /etc/profile.d.
if [ -f /etc/profile.d/waver.sh ]; then
    source /etc/profile.d/waver.sh
fi
EOF
