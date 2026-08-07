# waver_ros

> [!IMPORTANT]
> This repository is currently in Developer Preview mode and not ready for production use.
> There may be bugs, and APIs and configuration options are subject to change during this period.

ROS 2 stack for the [Waveshare WAVE ROVER](https://www.waveshare.com/wiki/WAVE_ROVER)
4WD rover, driven from a Raspberry Pi over serial and teleoperated / navigated
remotely over [LiveKit](https://livekit.io) via
[ROS Portal](https://github.com/livekit/ros-portal).

## SW Prerequisites
- python package `vcstool`, `pip install vcstool`, `pip install "setuptools<81.0.0"`


## Quick start

The supported deployment is Docker on the robot.

```bash
git clone git@github.com:livekit-examples/waver_ros.git
cd waver_ros

./scripts/setup_repos.sh           # host: clone dependencies

cat > .env <<'EOF'
LIVEKIT_URL=wss://<your-project>.livekit.cloud
LIVEKIT_API_KEY=<key>
LIVEKIT_API_SECRET=<secret>
EOF

docker compose build               # image: toolchain + system packages
docker compose run --rm waver bros # container: rosdep + colcon build (first time, and after src changes)
docker compose run --rm waver      # interactive shell
docker compose up                  # launch the full stack
```

The compose file bind-mounts the repo into `/waver_ws`, so `src/` and colcon
output (`build/`, `install/`, `log/`) live on the host and survive image
rebuilds. The image itself does not compile the workspace.

## Hardware

- [Waveshare WAVE ROVER](https://www.waveshare.com/wiki/WAVE_ROVER)
- Raspberry Pi 4 Model B.
- __optional:__ RPLidar C1 on USB, providing `/scan`.
- IMX219 CSI camera, captured directly by GStreamer (not through a ROS topic).

### Host setup

Done once on the Pi, outside the container:

```bash
./scripts/setup_repos.sh   # vcs import; needs SSH access to private repos

sudo raspi-config          # Interface Options -> Serial Port:
                           #   login shell over serial = No
                           #   serial hardware enabled  = Yes
sudo usermod -aG dialout $USER   # then re-login
```

The ESP32 board sits on the Pi's 40-pin UART, which is the mini-UART `/dev/ttyS0`
(`/dev/serial0` is the usual symlink to it). The RPLidar enumerates as
`/dev/ttyUSB0`.

Inside the container, `waver` launches the stack and `camcheck` smoke-tests the
camera; see [`setup-shell-env.sh`](setup-shell-env.sh) for the rest.

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

run with `--show-args` to see the default arguments:
```bash
ros2 launch waver_bringup waver.launch.xml sim:=true sim_gui:=true --show-args
```

## Connecting to LiveKit

`waver.launch.xml` brings up the robot but not the bridge. Start ROS Portal
alongside it, pointed at this robot's config:

```bash
LIVEKIT_URL=<url> LIVEKIT_TOKEN=<token> ros2 launch ros_portal ros_portal.launch.py \
  config_path:=$(ros2 pkg prefix waver_bringup)/share/waver_bringup/config/livekit_robot.yaml
```

[`livekit_robot.yaml`](src/waver_bringup/config/livekit_robot.yaml) is the robot
side: it forwards `/map`, `/plan`, `/scan`, `/pose`, `/tf`, `/tf_static`, and
`/imu/data_raw` out, accepts `/cmd_vel`, `/goal_pose`, `/initialpose`, and
`/clicked_point` in, and declares a `video_sources` entry (`mipi_camera`) that
captures the MIPI CSI camera directly over GStreamer — not via a ROS image
topic.
[`livekit_controller.yaml`](src/waver_bringup/config/livekit_controller.yaml) is
the mirror image, for the operator's machine.

Keep `identity:` aligned with the `robot_name` launch argument, so the
controller's `preserve_id` republishes this robot's topics under the matching
`/<robot_name>/*` namespace.


## Teleop Portal
To control from the LiveKit Teleop Portal, you must remap /<id>/cmd_vel to /cmd_vel:
```bash
ros2 run topic_tools relay /<lk_participant_id>/cmd_vel /cmd_vel
```

## Camera video

The `video_sources` entry (`track_name: mipi_camera`) in `livekit_robot.yaml`
captures the IMX219 MIPI camera directly with `libcamerasrc` and encodes VP8
in-process, independently of the ROS topic graph. View the stream in LiveKit or
Foxglove as the `mipi_camera` video track from the robot participant.

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

The middleware changes are required for autonomous navigation.

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

Workflow on the robot or in the dev container (workspace bind-mounted at
`/waver_ws`):

```bash
./scripts/setup_repos.sh                  # host: vcs import
docker compose build                      # image only — no colcon in Dockerfile
docker compose run --rm waver bros        # container: rosdep + colcon build
colcon test  --packages-select waver_driver   # after bros, same shell or `docker compose run --rm waver bash -lc '...'`
```

Or run the build steps explicitly instead of the `bros` alias:

```bash
docker compose run --rm waver bash -lc './scripts/rosdep_update.sh && colcon build --packages-up-to waver_bringup'
```

`bros` re-sources the overlay after building; run it again whenever `src/` or
`waver.repos` changes. Rebuild the image only when the Dockerfile or system
dependencies change.

`scripts/setup_repos.sh` also imports ROS Portal's *own* `external.repos`;
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
- This has only been tested on a PI 4, distribution:
```
(venv) rover@rover:~/workspaces/waver_ros $ lsb_release -a
No LSB modules are available.
Distributor ID: Debian
Description:    Debian GNU/Linux 13 (trixie)
Release:        13
Codename:       trixie
```

## Packages

This repository owns the robot. ROS Portal — the general-purpose ROS 2 ↔ LiveKit
bridge — is consumed as a pinned dependency (see [`waver.repos`](waver.repos)), not
forked, so robot-specific drivers, launch trees, and Raspberry Pi container
workarounds stay out of that repo.

| Package | Purpose |
| --- | --- |
| [`waver_driver`](src/waver_driver) | Serial JSON bridge to the ESP32 board: `cmd_vel` in; PWM motor commands out; `imu/data_raw` out. |
| [`waver_bringup`](src/waver_bringup) | Top-level physical/sim launch and LiveKit bridge config. |
| [`waver_localization`](src/waver_localization) | EKF launch/config and rf2o covariance relay. |
| [`waver_navigation`](src/waver_navigation) | SLAM Toolbox, Nav2, and launch/config. |
| [`waver_simulation`](src/waver_simulation) | Gazebo launch and sim frame-prefix relay. |
| [`src/vendor/`](src/vendor/VENDORED.md) | `waver_description` (URDF/meshes) and `waver_gazebo` (world), copied from [GGomezMorales/waver](https://github.com/GGomezMorales/waver). |
