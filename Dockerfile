# Jazzy (LTS, EOL May 2029), not a newer distro: nav2_bringup and slam_toolbox
# are unreleased on lyrical/resolute -- only nav2's leaf libraries are published
# there, so rosdep resolves the keys and apt then finds no debs. Jazzy also
# matches the ros_portal image in docker-compose.yml.
FROM ros:jazzy

WORKDIR /waver_ros

# Workspace sources. src/externals/ is gitignored, so fetch it with vcs.
COPY waver.repos .
COPY src src
RUN mkdir -p src/externals && vcs import src/externals < waver.repos --recursive --skip-existing

# Install every dependency the package manifests declare (python3-serial &c).
RUN apt-get update \
    && rosdep update --rosdistro "${ROS_DISTRO}" \
    && rosdep install --from-paths src --ignore-src -y -r --rosdistro "${ROS_DISTRO}" \
        --skip-keys cmake_modules \
    && rm -rf /var/lib/apt/lists/*

RUN . "/opt/ros/${ROS_DISTRO}/setup.sh" && colcon build --packages-up-to waver_bringup

# Pre-source the overlay for interactive shells (docker exec -it cobra bash).
# NOTE: the dev compose service bind-mounts the host workspace over
# /waver_ros, shadowing the build baked in here; run the image without
# that volume to use the self-contained build.
RUN echo 'source /waver_ros/install/setup.bash' >> /root/.bashrc
