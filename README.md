# waver_ros

ROS 2 stack for the [Waveshare WAVE ROVER](https://www.waveshare.com/wiki/WAVE_ROVER)
4WD rover, driven from a Raspberry Pi over serial and teleoperated / navigated
remotely over [LiveKit](https://livekit.io) via
[ROS Portal](https://github.com/livekit/ros2-livekit-bridge).

This repository owns the robot. ROS Portal — the general-purpose ROS 2 ↔ LiveKit
bridge — is consumed as a pinned dependency (see [`waver.repos`](waver.repos)), not
forked, so robot-specific drivers, launch trees, and Raspberry Pi container
workarounds stay out of that repo.

## Packages

| Package | Purpose |
| --- | --- |
| [`waver_driver`](src/waver_driver) | Serial JSON bridge to the ESP32 board: `cmd_vel` in; PWM motor commands out; `imu/data_raw` out. |
| [`waver_bringup`](src/waver_bringup) | Top-level physical/sim launch and LiveKit bridge config. |
| [`waver_localization`](src/waver_localization) | EKF launch/config and rf2o covariance relay. |
| [`waver_navigation`](src/waver_navigation) | SLAM Toolbox, Nav2, and launch/config. |
| [`waver_simulation`](src/waver_simulation) | Gazebo launch and sim frame-prefix relay. |
| [`src/vendor/`](src/vendor/VENDORED.md) | `waver_description` (URDF/meshes) and `waver_gazebo` (world), copied from [GGomezMorales/waver](https://github.com/GGomezMorales/waver). |

## Hardware

- Raspberry Pi 4 Model B.
- ESP32 "General Driver for Robots" board on the Pi's 40-pin UART.
- Four DC gear motors with **no wheel encoders**. Motor commands are signed PWM
  fractions, not true wheel velocities — which is why laser odometry, not wheel
  odometry, closes the loop.
- Onboard IMU, polled by the driver and published as `sensor_msgs/Imu` on
  `imu/data_raw`.
- RPLidar C1 on USB, providing `/scan`.
- IMX219 CSI camera, captured directly by GStreamer (not through a ROS topic).

## Quick start

The supported deployment is Docker on the robot.

```bash
git clone git@github.com:livekit-examples/waver_ros.git
cd waver_ros

cat > .env <<'EOF'
LIVEKIT_URL=wss://<your-project>.livekit.cloud
LIVEKIT_API_KEY=<key>
LIVEKIT_API_SECRET=<secret>
EOF

docker compose build
docker compose run --rm waver      # interactive shell
```

Inside the container, `waver` launches the stack and `camcheck` smoke-tests the
camera; see [`setup-shell-env.sh`](setup-shell-env.sh) for the rest.

> **Build time.** The image compiles the LiveKit C++ SDK (including its Rust
> components) and libcamera from source. Natively on a Pi 4 that is measured in
> hours. Cross-building on an x86 machine is much faster:
> `docker buildx build --platform linux/arm64 -t waver_ros:latest .`

### Host setup

Done once on the Pi, outside the container:

```bash
sudo raspi-config          # Interface Options -> Serial Port:
                           #   login shell over serial = No
                           #   serial hardware enabled  = Yes
sudo usermod -aG dialout $USER   # then re-login
```

The ESP32 board sits on the Pi's 40-pin UART, which is the mini-UART `/dev/ttyS0`
(`/dev/serial0` is the usual symlink to it). The RPLidar enumerates as
`/dev/ttyUSB0`.

## Running

### Bench test before the full graph

Verify the serial link, motors, and IMU with the standalone WASD tool — no ROS
graph involved:

```bash
ros2 run waver_driver wave_rover_serial_teleop.py --port /dev/ttyS0
```

Press `b` to measure the gyro zero-rate bias, and feed the result back as the
driver's `gyro_bias` parameter.

### Physical robot

```bash
ros2 launch waver_bringup waver.launch.xml \
  rover_serial_port:=/dev/ttyS0 \
  lidar_serial_port:=/dev/ttyUSB0
```

Teleop only — skips the lidar, laser odometry, EKF, and Nav2:

```bash
ros2 launch waver_bringup waver.launch.xml \
  rover_serial_port:=/dev/ttyS0 \
  teleop_only:=true
```

Drive it from a second terminal:

```bash
ros2 run teleop_twist_keyboard teleop_twist_keyboard
```

### Simulation

Gazebo, on a workstation rather than the Pi:

```bash
ros2 launch waver_bringup waver.launch.xml sim:=true sim_gui:=true
```

### Key launch arguments

| Argument | Default | Meaning |
| --- | --- | --- |
| `robot_name` | `robot_1` | TF frame prefix and LiveKit participant identity. |
| `sim` | `false` | Run against Gazebo instead of hardware. |
| `sim_gui` | `false` | Launch the Gazebo GUI client when `sim` is enabled. |
| `teleop_only` | `false` | Driver + description only; no lidar, odometry, EKF, or Nav2. |
| `nav2` | `true` | Launch the full Nav2 navigation stack. |
| `ekf` | `true` | Run a robot_localization EKF as the owner of `/odom` and the `odom->base_footprint` TF. |
| `ekf_fuse_imu` | `false` | With `ekf:=true`, also fuse the gyro yaw rate. |
| `rover_serial_port` | `/dev/serial0` | ESP32 board UART. |
| `rover_baud` | `115200` | ESP32 board baud rate. |
| `lidar_serial_port` | `/dev/ttyUSB0` | RPLidar C1 device. |
| `max_linear_speed`, `max_angular_speed` | `2.4`, `2.5` | Calibration gains for the open-loop PWM mixer. |
| `lidar_x`, `lidar_z`, `lidar_yaw` | `-0.04`, `0.205`, `pi` | Physical lidar pose relative to `base_link`. |

## Connecting to LiveKit

`waver.launch.xml` brings up the robot but not the bridge. Start ROS Portal
alongside it, pointed at this robot's config:

```bash
ros2 launch ros_portal ros_portal_local.launch.py \
  config:=$(ros2 pkg prefix waver_bringup)/share/waver_bringup/config/livekit_robot.yaml \
  identity:=waver
```

[`livekit_robot.yaml`](src/waver_bringup/config/livekit_robot.yaml) is the robot
side: it forwards `/map`, `/plan`, `/scan`, `/pose`, `/tf`, `/tf_static`, and
`/imu/data_raw` out, accepts `/cmd_vel`, `/goal_pose`, `/initialpose`, and
`/clicked_point` in, and declares the camera video source.
[`livekit_controller.yaml`](src/waver_bringup/config/livekit_controller.yaml) is
the mirror image, for the operator's machine.

Keep `identity:` aligned with the `robot_name` launch argument, so the
controller's `preserve_id` republishes this robot's topics under the matching
`/<robot_name>/*` namespace.

## Camera video

The `video_sources` entry in `livekit_robot.yaml` captures the IMX219 directly
with `libcamerasrc` and encodes VP8 in-process, independently of the ROS topic
graph. VP8 software encode is used rather than the Pi's hardware H.264 encoder so
that WebRTC can drive adaptive bitrate: the capture layer writes the encoder's
`target-bitrate` property at runtime, and `v4l2h264enc` exposes bitrate only
through a V4L2 `extra-controls` structure that the capture layer cannot set as a
plain integer property.

Two things have to be true for that pipeline to work, and both are already wired
into [`docker-compose.yml`](docker-compose.yml) and
[`.devcontainer/devcontainer.json`](.devcontainer/devcontainer.json):

- **libcamera is built from source in the image.** Ubuntu Noble packages
  libcamera 0.2.0, which finds the camera but then aborts inside its Raspberry Pi
  IPA (`assertion "it != buffers_.end()" failed in prepareIsp()`) against current
  Pi kernels. Stage 1 of the [`Dockerfile`](Dockerfile) builds Raspberry Pi's fork
  instead. Keep `LIBCAMERA_VERSION` at the version the host has installed —
  check with `dpkg -l | grep libcamera`.
- **The host's `/run/udev` is bind-mounted in.** libcamera enumerates through
  udev; without it `libcamerasrc` reports `Could not find any supported camera on
  this system` even though `/dev/media*` is present.

Verify inside the container before launching:

```bash
camcheck    # cam --list, then 30 frames through libcamerasrc
```

An empty `cam --list` means `/run/udev` is missing. `no element "libcamerasrc"`
means the image was built without the libcamera stage.

### Why not just use a distro package?

Neither going backwards nor forwards in Ubuntu release solves this today:

| Base | libcamera available | Nav2 released |
| --- | --- | --- |
| Jammy 22.04 (Humble) | `0~git20200629` — a 2020 snapshot, no usable Pi IPA | yes |
| **Noble 24.04 (Jazzy)** — current | 0.2.0 — broken against current Pi kernels | yes |
| Noble 24.04 (Kilted) | 0.2.0 — same | yes, but EOL Nov 2026 |
| Resolute 26.04 (Lyrical) | **0.7.0 with `ipa_rpi_vc4.so`** — exactly what a Pi 4 needs | **no** |

Resolute would remove the source build entirely. Revisit when Nav2 ships for
Lyrical.

## Middleware

The image runs Cyclone DDS rather than the ROS 2 default (Fast DDS): on the
CPU-bound Pi 4, Fast DDS starved the slam_toolbox (`map->odom`) and rf2o
(`odom->base`) TF publishers and produced continuous TF extrapolation errors.

```dockerfile
ENV RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
ENV ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
```

Discovery is restricted to localhost because cross-machine transport goes over
LiveKit, not raw DDS. The trade-off is that the ROS graph is not reachable with
`ros2` CLI or RViz from another machine — inspect it on the Pi, or over
LiveKit/Foxglove. To allow remote DDS access, override at runtime with
`-e ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET`.

## Development

```bash
./scripts/setup-workspace.sh              # vcs import + rosdep
colcon build --packages-up-to waver_bringup
colcon test  --packages-select waver_driver
```

`scripts/setup-workspace.sh` also imports ROS Portal's *own* `external.repos`;
`vcs import --recursive` follows git submodules but not nested `.repos` files, so
that second import has to be explicit.

## Notes

- `waver_driver` sends `{"T":1,"L":l,"R":r}` frames where `l,r` are signed PWM
  fractions.
- The vendored URDF's `lidar_link` models the simulator's LD19 and is left as an
  unused visual frame on the real robot; the physical scan is published in
  `laser`.
- Foxglove may render the robot model pitched 90° until the 3D panel's mesh up
  axis is set to `Z-up`; the URDF and TF tree are already Z-up.

## License

Apache-2.0. See [LICENSE](LICENSE), and
[`src/vendor/VENDORED.md`](src/vendor/VENDORED.md) for third-party attribution.

