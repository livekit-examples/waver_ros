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

"""Expand waver.launch.py in each supported configuration and assert what it brings up.

The launch file is the robot's wiring diagram: which nodes run, which frames they
publish, and which node owns /odom and the odom->base_footprint TF. A flipped
condition or a dropped frame prefix yields a graph that starts cleanly and then
silently fails to localize, so these tests resolve the launch description offline --
conditions evaluated, substitutions performed, parameter files written and read
back -- and assert on the result. No process is ever spawned, and includes are
recorded rather than expanded (their contents are the included package's business).
"""

import os
import pathlib

from launch import LaunchContext
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import get_launch_description_from_any_launch_file
from launch.substitutions import LocalSubstitution
from launch.utilities import perform_substitutions
from launch_ros.actions import Node

import pytest

import yaml

LAUNCH_FILE = str(pathlib.Path(__file__).resolve().parents[1] / 'launch' / 'waver.launch.py')

DESCRIPTION_NODES = {'joint_state_publisher', 'robot_state_publisher'}
HARDWARE_NODES = {'wave_rover_driver', 'base_link_to_laser', 'rf2o_laser_odometry'}


class Graph:
    """The nodes and includes a single argument set resolves to."""

    def __init__(self, nodes, includes):
        self.nodes = nodes
        self.includes = includes


def _resolved_node(node, context):
    # No public API expands a Node's parameters and remaps; _perform_substitutions is
    # what Node.execute() itself calls before handing the command line to the OS.
    node._perform_substitutions(context)
    # cmd[0] is the executable path; the LocalSubstitution entries are the __node/__ns
    # ros args that only Node.execute() can fill in, and they carry nothing to assert on.
    argv = [perform_substitutions(context, part) for part in node.cmd[1:]
            if not any(isinstance(sub, LocalSubstitution) for sub in part)]

    params = {}
    for index, arg in enumerate(argv):
        if arg != '--params-file':
            continue
        path = argv[index + 1]
        for entry in yaml.safe_load(pathlib.Path(path).read_text()).values():
            params.update(entry['ros__parameters'])
        os.unlink(path)

    return {
        'package': perform_substitutions(context, node.node_package),
        'executable': perform_substitutions(context, node.node_executable),
        'argv': argv,
        'params': params,
    }


def _walk(entities, context, nodes, includes):
    for entity in entities:
        enabled = entity.condition is None or entity.condition.evaluate(context)
        if isinstance(entity, Node):
            if enabled:
                nodes[entity.node_name] = _resolved_node(entity, context)
        elif isinstance(entity, IncludeLaunchDescription):
            if enabled:
                location = perform_substitutions(
                    context, entity.launch_description_source.location)
                includes[pathlib.Path(location).name] = {
                    perform_substitutions(context, key): perform_substitutions(context, value)
                    for key, value in entity.launch_arguments
                }
        else:
            # Everything else (argument declarations, groups, scope push/pop) is safe to
            # run: visit() honours the condition and returns the sub-entities to expand.
            _walk(entity.visit(context) or [], context, nodes, includes)


def resolve(**arguments):
    """Expand the launch file with the given arguments, as `ros2 launch` would."""
    context = LaunchContext()
    context.launch_configurations.update(arguments)

    nodes = {}
    includes = {}
    _walk(get_launch_description_from_any_launch_file(LAUNCH_FILE).entities,
          context, nodes, includes)
    return Graph(nodes, includes)


def test_every_argument_is_documented():
    # `--show-args` is the documented way to discover the knobs (see the README), so an
    # argument without a description or a default is a hole in the interface.
    arguments = get_launch_description_from_any_launch_file(LAUNCH_FILE).get_launch_arguments()
    assert arguments
    for argument in arguments:
        assert argument.description, f'{argument.name} has no description'
        assert argument.default_value is not None, f'{argument.name} has no default'


def test_defaults_bring_up_the_real_robot():
    graph = resolve()

    assert set(graph.nodes) == DESCRIPTION_NODES | HARDWARE_NODES
    assert set(graph.includes) == {'rplidar_c1_launch.py', 'ekf.launch.py', 'slam.launch.py'}
    assert graph.nodes['wave_rover_driver']['package'] == 'waver_driver'
    # rf2o logs three INFO lines per scan; the graph must keep it quiet.
    assert 'rf2o_laser_odometry:=warn' in graph.nodes['rf2o_laser_odometry']['argv']


def test_ekf_owns_odom_by_default():
    graph = resolve()
    rf2o = graph.nodes['rf2o_laser_odometry']['params']

    # Exactly one publisher of odom->base_footprint: rf2o feeds the EKF and stays off TF.
    assert rf2o['odom_topic'] == '/odom_rf2o'
    assert rf2o['publish_tf'] is False
    assert graph.includes['ekf.launch.py']['fuse_imu'] == 'false'


def test_without_the_ekf_rf2o_is_the_odometry_source():
    graph = resolve(ekf='false')
    rf2o = graph.nodes['rf2o_laser_odometry']['params']

    assert rf2o['odom_topic'] == '/odom'
    assert rf2o['publish_tf'] is True
    assert 'ekf.launch.py' not in graph.includes


def test_teleop_only_drops_sensing_localization_and_mapping():
    graph = resolve(teleop_only='true')

    assert set(graph.nodes) == DESCRIPTION_NODES | {'wave_rover_driver'}
    assert graph.includes == {}


def test_sim_replaces_the_hardware_graph():
    graph = resolve(sim='true', sim_gui='true')

    # Gazebo owns the description and the wheels; nothing that talks to real hardware runs.
    assert graph.nodes == {}
    assert set(graph.includes) == {'gazebo.launch.xml', 'slam.launch.py'}
    assert graph.includes['gazebo.launch.xml']['gui'] == 'true'
    assert graph.includes['gazebo.launch.xml']['use_sim_time'] == 'true'
    assert graph.includes['slam.launch.py']['use_sim_time'] == 'true'


def test_every_frame_carries_the_robot_prefix():
    graph = resolve(robot_name='robot_9')

    assert graph.nodes['robot_state_publisher']['params']['frame_prefix'] == 'robot_9/'
    assert graph.nodes['wave_rover_driver']['params']['imu_frame_id'] == 'robot_9/imu_link'

    rf2o = graph.nodes['rf2o_laser_odometry']['params']
    assert rf2o['base_frame_id'] == 'robot_9/base_footprint'
    assert rf2o['odom_frame_id'] == 'robot_9/odom'

    # The lidar's static transform and the scan it explains must name the same frames.
    laser_tf = graph.nodes['base_link_to_laser']['argv']
    assert laser_tf[laser_tf.index('--frame-id') + 1] == 'robot_9/base_link'
    assert laser_tf[laser_tf.index('--child-frame-id') + 1] == 'robot_9/laser'
    assert graph.includes['rplidar_c1_launch.py']['frame_id'] == 'robot_9/laser'

    for include in graph.includes.values():
        assert include.get('robot_name', 'robot_9') == 'robot_9'


def test_teleop_portal_relay_is_opt_in():
    assert 'cmd_vel_relay' not in resolve().nodes

    relay = resolve(id='rover_7').nodes['cmd_vel_relay']
    assert relay['package'] == 'topic_tools'
    assert relay['argv'][:2] == ['/rover_7/cmd_vel', '/cmd_vel']


def test_driver_parameters_keep_their_types():
    # Launch arguments are strings; the driver declares ints and floats, and a string
    # where an int is declared is a hard parameter-type rejection at startup.
    params = resolve(rover_baud='9600', max_linear_speed='1.5').nodes['wave_rover_driver']['params']

    assert params['baud'] == 9600
    assert isinstance(params['baud'], int)
    assert params['max_linear_speed'] == pytest.approx(1.5)
    assert params['cmd_type'] == 1
    assert params['output_max'] == pytest.approx(0.5)
    assert params['serial_port'] == '/dev/serial0'


def test_use_sim_time_is_a_bool_not_the_string_false():
    params = resolve().nodes['robot_state_publisher']['params']

    assert params['use_sim_time'] is False
    # The URDF is expanded by xacro at launch time; an unresolvable model breaks here.
    assert params['robot_description'].lstrip().startswith('<?xml')


def test_nav2_is_not_part_of_bringup():
    # Navigation is layered on a running robot (ros2 launch waver_navigation nav2.launch.py),
    # deliberately not bundled here.
    declared = get_launch_description_from_any_launch_file(LAUNCH_FILE).get_launch_arguments()
    assert 'nav2' not in {argument.name for argument in declared}

    for arguments in ({}, {'sim': 'true'}, {'ekf': 'false'}):
        graph = resolve(**arguments)
        assert not [name for name in graph.includes if 'nav2' in name]
