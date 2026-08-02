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
# Installs a login-shell profile so every shell in the container has ROS and the
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

# Re-source after a rebuild.
alias sros='_source_ros_env && _source_ws_overlay'

# Build the robot stack.
alias bros='cd "\${WS}" && colcon build --packages-up-to waver_bringup && sros'

# Re-resolve system dependencies after editing a package.xml.
alias dros='cd "\${WS}" && ./scripts/setup-workspace.sh deps'

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
