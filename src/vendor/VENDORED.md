# Vendored third-party packages

The packages in this directory are copied from an upstream repository rather than
imported by `vcs`. They are vendored because `waver_bringup` and `waver_simulation`
depend on them at launch time, and because the upstream repository shares the name
`waver` with this one — importing it would put a second `waver_description` on the
`AMENT_PREFIX_PATH` and make which one wins depend on workspace ordering.

## Source

| | |
|---|---|
| Repository | <https://github.com/GGomezMorales/waver> |
| Commit | `9146ead456dc57f6b4bdaa1a8ca1c7b9fdb59465` |
| Upstream subject | `feat(nav): localization and amcl launchers added` |
| License | Apache-2.0 — full text in [`LICENSE.upstream`](LICENSE.upstream) |

## What was taken, and what was not

| Package | Vendored | Why |
|---|---|---|
| `waver_description` | yes | URDF/xacro and meshes. `waver.launch.xml` and `gazebo.launch.xml` resolve the robot model from `$(find-pkg-share waver_description)/urdf/waver.xacro`. |
| `waver_gazebo` | yes | `gazebo.launch.xml` uses `worlds/room.sdf` and `config/ros_gz_bridge.yaml`. |
| `waver_nav` | no | Nothing resolves it at runtime. `waver_navigation/config/slam_params.yaml` was *forked* from its `param/mapper_params_online_async.yaml` and is now owned here; the only surviving mentions are "forked from" comments. |
| `waver_viz` | no | Unreferenced. |

## Modifications

None. These trees are byte-identical to upstream at the commit above.

Keeping them unmodified is deliberate: `waver_simulation/launch/gazebo.launch.xml`
runs `robot_state_publisher` itself instead of including
`waver_description/description.launch.xml`, precisely so that the `frame_prefix`
parameter can be set without patching the vendored launch file. Preserve that
pattern — put local behaviour in the `waver_*` packages, not in here, so a future
re-sync with upstream stays a clean copy.

## Re-syncing

```bash
git clone https://github.com/GGomezMorales/waver /tmp/waver-upstream
git -C /tmp/waver-upstream checkout <new-ref>
rm -rf src/vendor/waver_description src/vendor/waver_gazebo
cp -r /tmp/waver-upstream/waver_description /tmp/waver-upstream/waver_gazebo src/vendor/
cp /tmp/waver-upstream/LICENSE src/vendor/LICENSE.upstream
```

Then update the commit in the table above. Check the URDF link and joint names
against `waver_localization/config/ekf*.yaml` and
`waver_navigation/config/nav2_params.yaml`, which reference frames defined here.
