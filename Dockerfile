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

ARG ROS_IMAGE_DIGEST=31daab66eef9139933379fb67159449944f4e2dcf2e22c2d12cc715f29873e0f
ARG ROS_IMAGE_REPOSITORY=ros
ARG ROS_IMAGE_TAG=jazzy-ros-base-noble
ARG ROS_DISTRO=jazzy

# =============================================================================
# Stage 1: libcamera
#
# Raspberry Pi CSI camera capture for the GStreamer video source (libcamerasrc).
#
# Ubuntu Noble packages libcamera 0.2.0, whose Raspberry Pi IPA aborts
# ("assertion \"it != buffers_.end()\" failed in prepareIsp()") against current
# Raspberry Pi kernels, so build Raspberry Pi's fork instead. Only the vc4
# pipeline (Pi 4 and earlier, bcm2835-unicam) plus the generic simple/uvcvideo
# handlers are enabled; add rpi/pisp for Pi 5.
#
# This is a separate stage so meson, ninja, and the source tree never reach the
# runtime image, and so editing anything else in this repo does not rebuild it.
#
# Going *backwards* in Ubuntu release does not help: Jammy (Humble) ships a 2020
# libcamera git snapshot with no usable Pi IPA at all. Ubuntu 26.04 Resolute does
# package libcamera 0.7.0 with ipa_rpi_vc4.so, which would make this stage
# unnecessary — but Nav2 has no Lyrical release yet. Revisit when it does.
#
# Keep LIBCAMERA_VERSION at the libcamera the robot's host OS has installed:
#   dpkg -l | grep libcamera
# A container/host mismatch is tolerated by the kernel ABI but not guaranteed to
# be; matching is the tested configuration.
# =============================================================================
FROM ${ROS_IMAGE_REPOSITORY}:${ROS_IMAGE_TAG}@sha256:${ROS_IMAGE_DIGEST} AS libcamera-build

ARG LIBCAMERA_VERSION=v0.7.1+rpt20260429
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      git \
      libevent-dev \
      libgnutls28-dev \
      libgstreamer-plugins-base1.0-dev \
      libgstreamer1.0-dev \
      libtiff-dev \
      libudev-dev \
      libyaml-dev \
      meson \
      ninja-build \
      openssl \
      pkg-config \
      python3-jinja2 \
      python3-ply \
      python3-yaml && \
    rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 --branch "${LIBCAMERA_VERSION}" \
      https://github.com/raspberrypi/libcamera.git /tmp/libcamera && \
    meson setup /tmp/libcamera/build /tmp/libcamera \
      --prefix=/usr/local --libdir=lib --buildtype=release \
      -Dpipelines=rpi/vc4,simple,uvcvideo \
      -Dipas=rpi/vc4 \
      -Dgstreamer=enabled \
      -Dcam=enabled \
      -Dv4l2=false \
      -Dtest=false \
      -Dlc-compliance=disabled \
      -Dqcam=disabled \
      -Ddocumentation=disabled \
      -Dpycamera=disabled \
      -Dtracing=disabled && \
    DESTDIR=/out ninja -C /tmp/libcamera/build install

# =============================================================================
# Stage 2: runtime
# =============================================================================
FROM ${ROS_IMAGE_REPOSITORY}:${ROS_IMAGE_TAG}@sha256:${ROS_IMAGE_DIGEST}

ARG ROS_DISTRO=jazzy
ARG WS_ROS=waver_ws
ENV DEBIAN_FRONTEND=noninteractive
ENV ROS_DISTRO=${ROS_DISTRO}
ENV USER=root
ENV WS=/${WS_ROS}
WORKDIR ${WS}

# --- Base toolchain ----------------------------------------------------------
RUN apt-get update && apt-get install -y \
      build-essential \
      ca-certificates \
      cmake \
      curl \
      file \
      git \
      gnupg \
      iputils-ping \
      jq \
      nano \
      net-tools \
      ninja-build \
      pkg-config \
      python3-colcon-common-extensions \
      python3-jinja2 \
      python3-pip \
      python3-rosdep \
      wget && \
    rm -rf /var/lib/apt/lists/*

# --- LiveKit SDK build toolchain ---------------------------------------------
# ROS Portal's capture support is only on the pinned client-sdk-cpp source
# checkout (the ladvoc/livekit-capture branch), not in the v1.5.0 release
# tarball, so the SDK is always built from source here. That needs Rust and the
# GStreamer development headers.
ENV BUILD_LIVEKIT_SDK_FROM_SOURCE=true
RUN apt-get update && apt-get install -y \
      clang \
      libabsl-dev \
      libasound2-dev \
      libclang-dev \
      libcurl4-openssl-dev \
      libdecor-0-dev \
      libdrm-dev \
      libglib2.0-dev \
      libgstreamer-plugins-base1.0-dev \
      libgstreamer1.0-dev \
      libprotobuf-dev \
      libssl-dev \
      libunwind-dev \
      libusb-1.0-0-dev \
      libva-dev \
      libwayland-dev \
      lld \
      llvm-dev \
      protobuf-compiler \
      gstreamer1.0-libav \
      gstreamer1.0-plugins-bad \
      gstreamer1.0-plugins-base \
      gstreamer1.0-plugins-good \
      gstreamer1.0-plugins-ugly \
      gstreamer1.0-tools \
      xz-utils && \
    python3 -m pip install --no-cache-dir --break-system-packages cmake==3.31.10 && \
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
      | sh -s -- -y --profile minimal --default-toolchain stable && \
    rm -rf /var/lib/apt/lists/*
ENV PATH="/root/.cargo/bin:${PATH}"

# --- Robot stack dependencies -------------------------------------------------
# Installed explicitly rather than left to rosdep so they land in a cacheable
# layer; scripts/rosdep_update.sh covers anything missing when building on the
# bind-mounted workspace.
RUN apt-get update && apt-get install -y \
      ros-${ROS_DISTRO}-foxglove-bridge \
      ros-${ROS_DISTRO}-joint-state-publisher \
      ros-${ROS_DISTRO}-nav2-bringup \
      ros-${ROS_DISTRO}-navigation2 \
      ros-${ROS_DISTRO}-robot-localization \
      ros-${ROS_DISTRO}-robot-state-publisher \
      ros-${ROS_DISTRO}-ros-gz-* \
      ros-${ROS_DISTRO}-ros2-control* \
      ros-${ROS_DISTRO}-slam-toolbox \
      ros-${ROS_DISTRO}-teleop-twist-keyboard \
      ros-${ROS_DISTRO}-test-msgs \
      ros-${ROS_DISTRO}-tf2-ros \
      ros-${ROS_DISTRO}-xacro \
      python3-serial && \
    rm -rf /var/lib/apt/lists/*

# --- Middleware ---------------------------------------------------------------
# CycloneDDS rather than the ROS 2 default (Fast DDS): on the CPU-bound Pi 4,
# Fast DDS starved the slam_toolbox (map->odom) and rf2o (odom->base) TF
# publishers and produced continuous TF extrapolation errors. Cyclone is lighter
# and Nav2 is most reliable with it.
RUN apt-get update && apt-get install -y \
      ros-${ROS_DISTRO}-rmw-cyclonedds-cpp && \
    rm -rf /var/lib/apt/lists/*

# Baked into the image so every shell and process inherits it. DDS discovery is
# restricted to localhost because cross-machine transport goes over the LiveKit
# bridge, not raw DDS — this saves CPU and stops two robots on the same LAN and
# ROS_DOMAIN_ID from cross-discovering each other's graphs. Trade-off: the graph
# is no longer reachable via ros2 CLI / RViz from another machine (inspect on the
# Pi, or via LiveKit/Foxglove). To allow remote DDS access, override at runtime:
#   -e ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
ENV RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
ENV ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST

# --- libcamera from stage 1 ---------------------------------------------------
COPY --from=libcamera-build /out/usr/local /usr/local
RUN ldconfig
# libcamera installs its GStreamer plugin outside the distribution plugin dir.
ENV GST_PLUGIN_PATH="/usr/local/lib/gstreamer-1.0"

# --- LiveKit CLI --------------------------------------------------------------
RUN curl -sSL https://get.livekit.io/cli | bash

# --- Workspace shell ----------------------------------------------------------
# Source, scripts, and colcon output live on the host and are bind-mounted at
# runtime (see docker-compose.yml). The image only provides the toolchain and
# system packages; build with `bros` inside the container.
COPY setup-shell-env.sh /tmp/setup-shell-env.sh
RUN chmod +x /tmp/setup-shell-env.sh && /tmp/setup-shell-env.sh && rm /tmp/setup-shell-env.sh

CMD ["/bin/bash", "-l"]
