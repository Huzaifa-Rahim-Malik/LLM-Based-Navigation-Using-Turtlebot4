# TurtleBot 4 command cheat-sheet

Commands used during development (ROS 2 Jazzy, TurtleBot 4 + Nav2).
Paths are relative to the repository root.

## Environment

```bash
source scripts/setup.bash        # ROS 2 Jazzy, ROS_DOMAIN_ID=23, Fast DDS profile
```

Or launch the whole stack (localization or SLAM) with the helper script:

```bash
./scripts/robot_launch.sh 1 1 90                    # localize at x=1, y=1, facing North
./scripts/robot_launch.sh 0 0 0 --mode slam         # build a new map
```

## SLAM (mapping)

Synchronous SLAM on a remote PC gives a higher-resolution map.

```bash
ros2 launch turtlebot4_navigation slam.launch.py
ros2 launch turtlebot4_viz view_navigation.launch.py     # RViz2

# Save the map
ros2 service call /slam_toolbox/save_map slam_toolbox/srv/SaveMap "name:
  data: 'map_area'"
```

## Localization + navigation on a saved map

```bash
ros2 launch turtlebot4_navigation localization.launch.py map:=maps/map_1.yaml
ros2 launch turtlebot4_navigation nav2.launch.py
ros2 launch turtlebot4_viz view_navigation.launch.py
```

Send a goal from the CLI:

```bash
ros2 action send_goal /navigate_to_pose nav2_msgs/action/NavigateToPose \
"{pose: {header: {frame_id: 'map'}, pose: {position: {x: 1.0, y: 1.0, z: 0.0}, orientation: {w: 1.0}}}}"
```

## Docking

```bash
ros2 action send_goal /dock irobot_create_msgs/action/Dock "{}"
```

## Enable reverse motion (run on the TurtleBot's Raspberry Pi)

```bash
ros2 param get /_do_not_use/motion_control safety_override      # check
ros2 param set /_do_not_use/motion_control safety_override backup_only
```
