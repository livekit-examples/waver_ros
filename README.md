# waver_ros

> [!IMPORTANT]
> This repository is currently in Developer Preview mode and not ready for production use.
> There may be bugs, and APIs and configuration options are subject to change during this period.

ROS 2 stack for the [Waveshare WAVE ROVER](https://www.waveshare.com/wiki/WAVE_ROVER)
4WD rover, driven from a Raspberry Pi over serial and teleoperated / navigated
remotely over [LiveKit](https://livekit.io) via
[ROS Portal](https://github.com/livekit/ros-portal).

## SW Prerequisites

- [Docker](https://docs.docker.com/engine/install/) with Compose v2

## Quick start

The supported deployment is Docker on the robot. The image imports
[`waver.repos`](waver.repos), runs `rosdep`, and `colcon build`s
`waver_bringup` during `docker compose build`. Compose then runs the robot
workspace container alongside the prebuilt ROS Portal image.

```bash
git clone git@github.com:livekit-examples/waver_ros.git
cd waver_ros

cat > .env <<'EOF'
LIVEKIT_URL=wss://<your-project>.livekit.cloud
LIVEKIT_TOKEN=<token>
EOF

docker compose build   # image: vcs import + rosdep + colcon
docker compose up      # waver_ros + ros_portal
docker exec -it waver bash
```

Compose bind-mounts the repo over `/waver_ros`, which shadows the build baked
into the image. For day-to-day source changes, rebuild inside the running
container (`colcon build --packages-up-to waver_bringup`) or rebuild the image.
Use the image without the bind mount when you want the self-contained build.

## Hardware

- [Waveshare WAVE ROVER](https://www.waveshare.com/wiki/WAVE_ROVER)
- Raspberry Pi 4 Model B.
- __optional:__ RPLidar C1 on USB, providing `/scan`.
- IMX219 CSI camera, captured directly by GStreamer (not through a ROS topic).

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

Inside the container, launch the stack with `ros2 launch waver_bringup …`
(see [Running](#running)).

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

`docker compose up` starts the `ros_portal` service with
[`livekit_robot.yaml`](src/waver_bringup/config/livekit_robot.yaml) and the
`LIVEKIT_URL` / `LIVEKIT_TOKEN` from `.env` (or the environment). Override the
config path with `LIVEKIT_CONFIG` if needed.

`waver.launch.xml` brings up the robot graph only; the bridge is the separate
`ros_portal` container. To launch the portal by hand instead of compose:

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
captures the IMX219 MIPI camera directly with GStreamer and encodes VP8
in-process, independently of the ROS topic graph. View the stream in LiveKit or
Foxglove as the `mipi_camera` video track from the robot participant.

The `ros_portal` compose service runs privileged with `/dev` mounted so camera
devices are visible to the portal container.

## Middleware

On the CPU-bound Pi 4, Fast DDS has starved the slam_toolbox (`map->odom`) and
rf2o (`odom->base`) TF publishers and produced continuous TF extrapolation
errors. Prefer Cyclone DDS for autonomous navigation:

```bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
```

Discovery restricted to localhost is useful because cross-machine transport goes
over LiveKit, not raw DDS. The trade-off is that the ROS graph is not reachable
with `ros2` CLI or RViz from another machine — inspect it on the Pi, or over
LiveKit/Foxglove. To allow remote DDS access, set
`ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET`.

## Development

```bash
# credentials required so compose can interpolate the ros_portal service
LIVEKIT_URL=<url> LIVEKIT_TOKEN=<token> docker compose build
LIVEKIT_URL=<url> LIVEKIT_TOKEN=<token> docker compose up -d
docker exec -it waver bash
```

After editing `src/` on the bind-mounted workspace, rebuild in the container:

```bash
colcon build --packages-up-to waver_bringup
source install/setup.bash
```

Rebuild the image when the [`Dockerfile`](Dockerfile) or [`waver.repos`](waver.repos)
change.

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
bridge — runs as the `ros_portal` compose service from a prebuilt image, not as
a workspace package, so robot-specific drivers, launch trees, and Raspberry Pi
container workarounds stay out of that repo. Workspace third-party deps are
pinned in [`waver.repos`](waver.repos).

| Package | Purpose |
| --- | --- |
| [`waver_driver`](src/waver_driver) | Serial JSON bridge to the ESP32 board: `cmd_vel` in; PWM motor commands out; `imu/data_raw` out. |
| [`waver_bringup`](src/waver_bringup) | Top-level physical/sim launch and LiveKit bridge config. |
| [`waver_localization`](src/waver_localization) | EKF launch/config and rf2o covariance relay. |
| [`waver_navigation`](src/waver_navigation) | SLAM Toolbox, Nav2, and launch/config. |
| [`waver_simulation`](src/waver_simulation) | Gazebo launch and sim frame-prefix relay. |
| [`src/vendor/`](src/vendor/VENDORED.md) | `waver_description` (URDF/meshes) and `waver_gazebo` (world), copied from [GGomezMorales/waver](https://github.com/GGomezMorales/waver). |
