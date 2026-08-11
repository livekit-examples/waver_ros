#!/usr/bin/env python3

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

"""Top-level bringup for the WAVE ROVER: robot description, hardware, odometry, mapping.

Two mutually exclusive worlds: the real robot (driver + RPLidar + rf2o/EKF) and
Gazebo (``sim:=true``, which brings up its own description and DiffDrive plugin).
``teleop_only:=true`` cuts everything but the driver and the description.

Frames are prefixed per robot (see the ``robot_name`` argument); topics stay flat.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.actions import GroupAction
from launch.actions import IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.conditions import UnlessCondition
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import Command
from launch.substitutions import LaunchConfiguration
from launch.substitutions import NotEqualsSubstitution
from launch.substitutions import PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def _declare_arguments():
    return [
        # ======================= Multi-robot identity =======================
        # Single knob for putting this robot in its own TF world. Every frame_id
        # this robot emits is prefixed with "<robot_name>/" (base_link ->
        # robot_1/base_link, odom -> robot_1/odom, map -> robot_1/map), so several
        # robots can be merged onto one viewer's /tf without frame collisions.
        # Keep this aligned with the bridge's LiveKit participant identity
        # (identity:=robot_1) so the controller's preserve_id republishes this
        # robot's topics under the same /robot_1/* namespace.
        # Topics stay flat (/scan, /map, /tf) on the robot's own graph -- only
        # frames are prefixed. Separation of topics happens at the controller.
        DeclareLaunchArgument(
            'robot_name', default_value='robot_1',
            description='Per-robot TF frame prefix and bridge identity.'),
        # LiveKit Teleop Portal publishes Twist on /<participant_id>/cmd_vel. When set,
        # relay that topic onto the flat /cmd_vel the driver (and Gazebo DiffDrive) consume.
        DeclareLaunchArgument(
            'id', default_value='default',
            description='LiveKit teleop participant id; when set, relay '
                        '/<id>/cmd_vel -> /cmd_vel.'),

        DeclareLaunchArgument(
            'sim', default_value='false',
            description='Launch Gazebo and use simulation settings.'),
        DeclareLaunchArgument(
            'sim_gui', default_value='false',
            description='Launch the Gazebo GUI client when sim is enabled.'),
        DeclareLaunchArgument(
            'teleop_only', default_value='false',
            description='Teleop-only mode: skip lidar, laser odometry, EKF, and mapping; '
                        'driver + description only.'),

        # Odometry mode (two knobs, giving three A/B configurations):
        #   ekf:=true  (default) -> a robot_localization EKF owns /odom and the
        #     odom->base_footprint TF. rf2o feeds it on /odom_rf2o (publish_tf:=false).
        #     - ekf_fuse_imu:=false (default): rf2o-only EKF, a pure 30 Hz TF
        #       republisher (ekf_rf2o_only.yaml). Fixes the "extrapolation into the
        #       future" TF failures that rf2o's slow, scan-time-stamped 10 Hz TF causes
        #       for consumers looking up transforms at "now".
        #     - ekf_fuse_imu:=true: also fuse the gyro yaw rate (ekf.yaml) for
        #       drift-resistant heading during fast rotations.
        #   ekf:=false -> no EKF; rf2o_laser_odometry alone publishes /odom and owns the
        #     odom->base_footprint TF at ~10 Hz. Simplest, but too stale for high-rate
        #     TF lookups (fine for teleop/mapping only).
        DeclareLaunchArgument(
            'ekf', default_value='true',
            description='Run a robot_localization EKF as the owner of /odom and the '
                        'odom->base_footprint TF. false -> rf2o publishes /odom and the '
                        'TF directly (~10 Hz, too stale for high-rate consumers).'),
        DeclareLaunchArgument(
            'ekf_fuse_imu', default_value='false',
            description='Only with ekf:=true. true -> fuse the gyro yaw rate (full '
                        'fusion, ekf.yaml). false -> rf2o-only high-rate TF republisher '
                        '(ekf_rf2o_only.yaml).'),

        # Robot description source (real-robot path; sim brings up its own via gazebo).
        DeclareLaunchArgument(
            'model',
            default_value=PathJoinSubstitution(
                [FindPackageShare('waver_description'), 'urdf', 'waver.xacro']),
            description='Xacro robot model.'),
        DeclareLaunchArgument(
            'camera_type', default_value='raspi',
            description='Xacro camera variant (raspi/depth).'),

        # Real-robot hardware settings (ignored when sim:=true).
        DeclareLaunchArgument(
            'lidar_serial_port', default_value='/dev/ttyUSB0',
            description='RPLidar C1 serial device.'),
        DeclareLaunchArgument(
            'rover_serial_port', default_value='/dev/serial0',
            description='ESP32 driver board UART (40-pin GPIO).'),
        DeclareLaunchArgument(
            'rover_baud', default_value='115200',
            description='ESP32 driver board baud rate.'),
        # Commanded->actual velocity calibration gains (bench-fit 2026-07-16 against
        # rf2o/gyro; see wave_rover_driver.py). These normalize the twist BEFORE the
        # axis dead-zone lift, so they set the low-band slope a velocity controller
        # operates in, not the physical top speed. Raise a value if the robot moves
        # faster than commanded; lower it if slower.
        DeclareLaunchArgument(
            'max_linear_speed', default_value='2.4',
            description='Linear calibration gain (m/s at full throttle, low-band fit); '
                        'tune so commanded ~ actual speed.'),
        DeclareLaunchArgument(
            'max_angular_speed', default_value='2.5',
            description='Angular calibration gain (rad/s at full throttle, low-band fit); '
                        'tune so commanded ~ actual rate.'),
        # RPLidar mount relative to base_link: ~0.205 m above, ~0.04 m behind (negative X = rear).
        # Empirically the scan's angle-0 ray points toward the robot's REAR (an object placed
        # in front of the robot returns at laser angle ~pi), so base_link->laser needs yaw = pi
        # to put front-of-robot at base_link +x. This is a property of the sensor's zero-angle
        # reference, not of which way the unit visually faces. With yaw = pi the scan, the map,
        # and rf2o odometry all agree that +x is the robot's physical front.
        DeclareLaunchArgument(
            'lidar_x', default_value='-0.04',
            description='Lidar X offset from base_link (m, +forward).'),
        DeclareLaunchArgument(
            'lidar_z', default_value='0.205',
            description='Lidar Z offset from base_link (m, +up).'),
        DeclareLaunchArgument(
            'lidar_yaw', default_value='3.14159265',
            description='Lidar yaw offset from base_link (rad); pi = scan angle-0 points '
                        'to robot rear.'),
    ]


def generate_launch_description():
    robot_name = LaunchConfiguration('robot_name')
    participant_id = LaunchConfiguration('id')
    sim = LaunchConfiguration('sim')
    sim_gui = LaunchConfiguration('sim_gui')
    teleop_only = LaunchConfiguration('teleop_only')
    ekf = LaunchConfiguration('ekf')
    ekf_fuse_imu = LaunchConfiguration('ekf_fuse_imu')
    model = LaunchConfiguration('model')
    camera_type = LaunchConfiguration('camera_type')
    lidar_serial_port = LaunchConfiguration('lidar_serial_port')
    rover_serial_port = LaunchConfiguration('rover_serial_port')
    rover_baud = LaunchConfiguration('rover_baud')
    max_linear_speed = LaunchConfiguration('max_linear_speed')
    max_angular_speed = LaunchConfiguration('max_angular_speed')
    lidar_x = LaunchConfiguration('lidar_x')
    lidar_z = LaunchConfiguration('lidar_z')
    lidar_yaw = LaunchConfiguration('lidar_yaw')

    use_sim_time = ParameterValue(sim, value_type=bool)
    frame_prefix = [robot_name, '/']

    # ============================ Robot description ============================
    # In sim, gazebo.launch.xml brings up the description with sim_control:=gazebo
    # (the DiffDrive plugin that consumes /cmd_vel and publishes odom + the
    # odom->base_footprint TF).
    #
    # On the real robot we run robot_state_publisher directly (rather than
    # including waver_description/description.launch.xml) so we can set
    # frame_prefix -- the vendored launch does not expose it, and src/vendor is
    # kept byte-identical to upstream so it can be re-synced. frame_prefix
    # prepends "<robot_name>/" to every frame_id derived from the URDF.
    description = GroupAction(
        condition=UnlessCondition(sim),
        actions=[
            Node(
                package='joint_state_publisher',
                executable='joint_state_publisher',
                name='joint_state_publisher',
                parameters=[{'use_sim_time': use_sim_time}],
            ),
            Node(
                package='robot_state_publisher',
                executable='robot_state_publisher',
                name='robot_state_publisher',
                output='screen',
                parameters=[{
                    'use_sim_time': use_sim_time,
                    'frame_prefix': frame_prefix,
                    'robot_description': ParameterValue(
                        Command(['xacro ', model,
                                 ' sim_control:=ros2 camera_type:=', camera_type]),
                        value_type=str),
                }],
            ),
        ],
    )

    # ===================== Real-robot hardware (unless sim) =====================
    hardware = GroupAction(
        condition=UnlessCondition(sim),
        actions=[
            # cmd_vel -> ESP32 serial JSON motion driver.
            Node(
                package='waver_driver',
                executable='wave_rover_driver',
                name='wave_rover_driver',
                output='screen',
                parameters=[{
                    'serial_port': rover_serial_port,
                    'baud': ParameterValue(rover_baud, value_type=int),
                    'max_linear_speed': ParameterValue(max_linear_speed, value_type=float),
                    'max_angular_speed': ParameterValue(max_angular_speed, value_type=float),
                    'output_max': 0.5,
                    'cmd_type': 1,
                    'cmd_timeout': 0.5,
                    # IMU published on /imu/data_raw in the robot's own TF frame.
                    'imu_frame_id': [robot_name, '/imu_link'],
                }],
            ),
            GroupAction(
                condition=UnlessCondition(teleop_only),
                actions=[
                    # RPLidar C1 -> /scan (frame_id: <robot_name>/laser).
                    IncludeLaunchDescription(
                        PythonLaunchDescriptionSource(PathJoinSubstitution(
                            [FindPackageShare('rplidar_ros'),
                             'launch', 'rplidar_c1_launch.py'])),
                        launch_arguments={
                            'serial_port': lidar_serial_port,
                            'frame_id': [robot_name, '/laser'],
                        }.items(),
                    ),

                    # Physical lidar pose. The vendored URDF's lidar_link models the sim
                    # LD19 mount and is left as an unused visual frame; the real scan is
                    # published in `<robot_name>/laser`.
                    Node(
                        package='tf2_ros',
                        executable='static_transform_publisher',
                        name='base_link_to_laser',
                        arguments=[
                            '--x', lidar_x, '--y', '0.0', '--z', lidar_z,
                            '--yaw', lidar_yaw, '--pitch', '0.0', '--roll', '0.0',
                            '--frame-id', [robot_name, '/base_link'],
                            '--child-frame-id', [robot_name, '/laser'],
                        ],
                    ),

                    # Laser-scan-matching odometry (no wheel encoders). The `ekf` flag
                    # selects rf2o's role, so it's a clean A/B switch between
                    # "rf2o + EKF" and "rf2o alone":
                    #
                    #   ekf:=true (default) -> rf2o feeds the EKF. It publishes raw
                    #     odometry on /odom_rf2o with publish_tf:=false so the EKF is the
                    #     sole owner of the odom->base_footprint TF and /odom; the two
                    #     must never both publish that TF.
                    #
                    #   ekf:=false -> rf2o IS the odometry source. It publishes /odom
                    #     directly and owns the odom->base_footprint TF (publish_tf:=true).
                    #     slam_toolbox and the bridge consume rf2o's raw estimate
                    #     unfiltered.
                    #
                    # ros_arguments log-level WARN: rf2o logs 3 INFO lines per scan
                    # (30 msgs/s), measurable CPU + log I/O on the Pi for zero
                    # diagnostic value.
                    Node(
                        condition=UnlessCondition(ekf),
                        package='rf2o_laser_odometry',
                        executable='rf2o_laser_odometry_node',
                        name='rf2o_laser_odometry',
                        output='screen',
                        ros_arguments=['--log-level', 'rf2o_laser_odometry:=warn'],
                        parameters=[{
                            'laser_scan_topic': '/scan',
                            'odom_topic': '/odom',
                            'publish_tf': True,
                            'base_frame_id': [robot_name, '/base_footprint'],
                            'odom_frame_id': [robot_name, '/odom'],
                            'init_pose_from_topic': '',
                            'freq': 10.0,
                        }],
                    ),
                    Node(
                        condition=IfCondition(ekf),
                        package='rf2o_laser_odometry',
                        executable='rf2o_laser_odometry_node',
                        name='rf2o_laser_odometry',
                        output='screen',
                        ros_arguments=['--log-level', 'rf2o_laser_odometry:=warn'],
                        parameters=[{
                            'laser_scan_topic': '/scan',
                            'odom_topic': '/odom_rf2o',
                            'publish_tf': False,
                            'base_frame_id': [robot_name, '/base_footprint'],
                            'odom_frame_id': [robot_name, '/odom'],
                            'init_pose_from_topic': '',
                            'freq': 10.0,
                        }],
                    ),

                    # EKF (behind the `ekf` flag, default ON). Owns /odom and the
                    # odom->base_footprint TF that slam_toolbox and the bridge consume.
                    # ekf_fuse_imu picks the params file: rf2o-only high-rate TF
                    # republisher (default) vs. full rf2o + gyro fusion. See the arg
                    # block up top.
                    IncludeLaunchDescription(
                        PythonLaunchDescriptionSource(PathJoinSubstitution(
                            [FindPackageShare('waver_localization'),
                             'launch', 'ekf.launch.py'])),
                        condition=IfCondition(ekf),
                        launch_arguments={
                            'robot_name': robot_name,
                            'use_sim_time': sim,
                            'fuse_imu': ekf_fuse_imu,
                            'lidar_yaw': lidar_yaw,
                        }.items(),
                    ),
                ],
            ),
        ],
    )

    # =========================== Mapping ================================
    # slam_toolbox's map/odom/base frames live in a params yaml (not launch args),
    # so a small Python helper rewrites them to the <robot_name>/ prefix before
    # handing off to slam_toolbox's online_async launch. Publishes
    # <robot_name>/map -> <robot_name>/odom, giving this robot its own map world.
    mapping = GroupAction(
        condition=UnlessCondition(teleop_only),
        actions=[
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(PathJoinSubstitution(
                    [FindPackageShare('waver_navigation'), 'launch', 'slam.launch.py'])),
                launch_arguments={
                    'robot_name': robot_name,
                    'use_sim_time': sim,
                }.items(),
            ),
        ],
    )

    gazebo = IncludeLaunchDescription(
        AnyLaunchDescriptionSource(PathJoinSubstitution(
            [FindPackageShare('waver_simulation'), 'launch', 'gazebo.launch.xml'])),
        condition=IfCondition(sim),
        launch_arguments={
            'use_sim_time': 'true',
            'gui': sim_gui,
            'robot_name': robot_name,
            'model': model,
            'camera_type': camera_type,
        }.items(),
    )

    # Teleop Portal: /<id>/cmd_vel -> /cmd_vel (skipped when id is left at 'default').
    cmd_vel_relay = Node(
        condition=IfCondition(NotEqualsSubstitution(participant_id, 'default')),
        package='topic_tools',
        executable='relay',
        name='cmd_vel_relay',
        output='screen',
        arguments=[['/', participant_id, '/cmd_vel'], '/cmd_vel'],
    )

    return LaunchDescription([
        *_declare_arguments(),
        description,
        hardware,
        mapping,
        gazebo,
        cmd_vel_relay,
    ])
