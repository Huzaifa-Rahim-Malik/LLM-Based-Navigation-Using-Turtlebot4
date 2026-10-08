#!/bin/bash

################################################################################
# TurtleBot4 Complete Setup Script
# File: turtlebot4_setup.sh
#
# Modes:
#   --mode localization  → Launch localization against an existing map (default)
#   --mode slam          → Launch SLAM (builds a new map live)
#
# Initial Pose — TWO syntaxes supported:
#
#   POSITIONAL (simplest):
#     ./turtlebot4_setup.sh <x> <y> <yaw_deg>
#     ./turtlebot4_setup.sh 1 1 0          # x=1 y=1, facing East  (0°)
#     ./turtlebot4_setup.sh 1 1 90         # x=1 y=1, facing North (90°)
#     ./turtlebot4_setup.sh 1 1 180        # x=1 y=1, facing West  (180°)
#     ./turtlebot4_setup.sh 1 1 270        # x=1 y=1, facing South (270°)
#
#   NAMED FLAGS:
#     ./turtlebot4_setup.sh --x 1.5 --y -0.3 --yaw-deg 90
#     ./turtlebot4_setup.sh --x 0.0 --y 0.0 --yaw 1.57   (raw radians)
#
#   MIX positional pose with other flags:
#     ./turtlebot4_setup.sh 1 1 90 --mode localization /path/to/map.yaml
#     ./turtlebot4_setup.sh 0 0 0  --mode slam
#
# Press Ctrl+C to stop all services
################################################################################

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# ── Defaults ──────────────────────────────────────────────────────────────────
MODE="localization"
MAP_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/maps/robotic_arena.yaml"
CYCLONEDDS_CONFIG="${CYCLONEDDS_CONFIG:-$HOME/turtlebot4/cyclonedds_pc.xml}"
ROS_DISTRO="jazzy"

# Initial pose defaults (origin, facing East = 0°)
INIT_X=0.0
INIT_Y=0.0
INIT_YAW_DEG=0.0   # always supply degrees; converted to radians below
INIT_YAW_RAD=""    # set only if --yaw (radians) is passed directly

declare -a PIDS=()

# ── Argument Parsing ──────────────────────────────────────────────────────────
#
# Positional syntax:  ./ro.sh X Y YAW_DEG [extra flags]
#   - Leading numeric args are consumed as x, y, yaw_deg in order
# Named-flag syntax:  --x X --y Y --yaw-deg DEG  (or --yaw RAD for radians)
# Both can be mixed:  ./ro.sh 1 1 90 --mode slam

POSITIONAL_COUNT=0
TEMP_ARGS=("$@")

# Count how many of the first arguments look like numbers (the pose triple)
for arg in "${TEMP_ARGS[@]}"; do
    if [[ "$arg" =~ ^-?[0-9]+(\.[0-9]+)?$ ]] && [[ $POSITIONAL_COUNT -lt 3 ]]; then
        POSITIONAL_COUNT=$((POSITIONAL_COUNT + 1))
    else
        break
    fi
done

# Consume positional pose args first
if [[ $POSITIONAL_COUNT -ge 2 ]]; then
    INIT_X="$1";  shift
    INIT_Y="$1";  shift
    if [[ $POSITIONAL_COUNT -ge 3 ]]; then
        INIT_YAW_DEG="$1"; shift
    fi
fi

# Parse remaining named flags
while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode)
            MODE="$2"; shift 2 ;;
        --x)
            INIT_X="$2"; shift 2 ;;
        --y)
            INIT_Y="$2"; shift 2 ;;
        --yaw-deg)
            INIT_YAW_DEG="$2"; shift 2 ;;
        --yaw)
            # Accept raw radians for backward-compatibility
            INIT_YAW_RAD="$2"; shift 2 ;;
        *.yaml|*.yml)
            MAP_FILE="$1"; shift ;;
        *)
            echo -e "${RED}✗${NC} Unknown argument: $1"
            echo ""
            echo "Usage (positional):  $0 <x> <y> <yaw_deg> [--mode slam|localization] [map.yaml]"
            echo "Usage (named flags): $0 --x X --y Y --yaw-deg DEG [--mode slam|localization]"
            echo ""
            echo "Examples:"
            echo "  $0 1 1 0          # x=1  y=1  facing East  (0°)"
            echo "  $0 1 1 90         # x=1  y=1  facing North (90°)"
            echo "  $0 1 1 180        # x=1  y=1  facing West  (180°)"
            echo "  $0 1 1 270        # x=1  y=1  facing South (270°)"
            echo "  $0 1.5 -0.3 90 --mode localization /path/to/map.yaml"
            echo "  $0 --mode slam"
            exit 1
            ;;
    esac
done

# Validate mode
if [[ "$MODE" != "slam" && "$MODE" != "localization" ]]; then
    echo -e "${RED}✗${NC} Invalid mode: '$MODE'. Use 'slam' or 'localization'."
    exit 1
fi

# Resolve final yaw in radians
# --yaw (radians) takes priority; otherwise convert degrees → radians
if [[ -z "$INIT_YAW_RAD" ]]; then
    INIT_YAW_RAD=$(python3 -c "import math; print(math.radians(float($INIT_YAW_DEG)))")
fi
INIT_YAW="$INIT_YAW_RAD"

################################################################################
# Helper Functions
################################################################################

print_header() {
    echo ""
    echo -e "${CYAN}==========================================${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}==========================================${NC}"
    echo ""
}
print_success() { echo -e "${GREEN}✓${NC} $1"; }
print_error()   { echo -e "${RED}✗${NC} $1"; }
print_warning() { echo -e "${YELLOW}⚠${NC} $1"; }
print_info()    { echo -e "${BLUE}ℹ${NC} $1"; }

# ── Yaw → Quaternion (pure Z rotation) ───────────────────────────────────────
# q_z = sin(yaw/2),  q_w = cos(yaw/2)
yaw_to_quat() {
    python3 -c "
import math
yaw = $1
qz = math.sin(yaw / 2.0)
qw = math.cos(yaw / 2.0)
print(qz, qw)
"
}

# ── Cleanup ───────────────────────────────────────────────────────────────────
cleanup() {
    echo ""
    print_header "Shutting Down All Services"
    for pid in "${PIDS[@]}"; do
        if ps -p "$pid" > /dev/null 2>&1; then
            echo "Stopping process $pid..."
            kill -SIGINT "$pid" 2>/dev/null
        fi
    done
    sleep 2
    for pid in "${PIDS[@]}"; do
        if ps -p "$pid" > /dev/null 2>&1; then
            echo "Force killing process $pid..."
            kill -9 "$pid" 2>/dev/null
        fi
    done
    print_success "All services stopped"
    echo ""
    exit 0
}

trap cleanup SIGINT SIGTERM

################################################################################
# Main Script
################################################################################

print_header "TurtleBot4 ROS2 Setup  [mode: $MODE]"

# ── Step 1: Verify ROS2 ───────────────────────────────────────────────────────
print_info "Checking ROS2 installation..."
if [ ! -f "/opt/ros/$ROS_DISTRO/setup.bash" ]; then
    print_error "ROS2 $ROS_DISTRO not found at /opt/ros/$ROS_DISTRO/"
    exit 1
fi
print_success "ROS2 $ROS_DISTRO found"

# ── Step 2: Verify map file (localization only) ───────────────────────────────
if [[ "$MODE" == "localization" ]]; then
    print_info "Checking map file..."
    if [ ! -f "$MAP_FILE" ]; then
        print_error "Map file not found: $MAP_FILE"
        print_warning "Tip: run with --mode slam to build a new map first."
        exit 1
    fi
    print_success "Map file found: $MAP_FILE"
else
    print_info "SLAM mode — no pre-built map required."
fi

# ── Step 3: Source ROS2 ───────────────────────────────────────────────────────
echo ""
print_info "Sourcing ROS2 $ROS_DISTRO setup..."
source "/opt/ros/$ROS_DISTRO/setup.bash"
print_success "ROS2 environment sourced"

# ── Step 4: Environment Variables ─────────────────────────────────────────────
echo ""
print_info "Setting environment variables..."

export ROS_DOMAIN_ID=23
print_success "ROS_DOMAIN_ID        = $ROS_DOMAIN_ID"

export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
print_success "RMW_IMPLEMENTATION   = $RMW_IMPLEMENTATION"

if [ -f "$CYCLONEDDS_CONFIG" ]; then
    export CYCLONEDDS_URI="$CYCLONEDDS_CONFIG"
    print_success "CYCLONEDDS_URI       = $CYCLONEDDS_URI"
else
    print_warning "CycloneDDS config not found (optional): $CYCLONEDDS_CONFIG"
fi

# ── Step 5: Launch SLAM or Localization ───────────────────────────────────────
echo ""
print_header "Launching Services"

if [[ "$MODE" == "slam" ]]; then

    print_info "Starting SLAM (live map building)..."
    ros2 launch turtlebot4_navigation slam.launch.py \
        > /tmp/slam.log 2>&1 &
    SLAM_PID=$!
    PIDS+=("$SLAM_PID")

    if ps -p "$SLAM_PID" > /dev/null 2>&1; then
        print_success "SLAM launched (PID: $SLAM_PID)"
    else
        print_error "Failed to launch SLAM"
        cat /tmp/slam.log
        exit 1
    fi

    print_info "Waiting for SLAM to initialize (5 seconds)..."
    sleep 5

else

    print_info "Starting Localization with map: $MAP_FILE"
    ros2 launch turtlebot4_navigation localization.launch.py \
        map:="$MAP_FILE" \
        > /tmp/localization.log 2>&1 &
    LOCALIZATION_PID=$!
    PIDS+=("$LOCALIZATION_PID")

    if ps -p "$LOCALIZATION_PID" > /dev/null 2>&1; then
        print_success "Localization launched (PID: $LOCALIZATION_PID)"
    else
        print_error "Failed to launch Localization"
        cat /tmp/localization.log
        exit 1
    fi

    # Give AMCL enough time to come up before publishing pose
    print_info "Waiting for AMCL to initialize (5 seconds)..."
    sleep 5

    # ── Step 5b: Publish Initial Pose ─────────────────────────────────────────
    #
    # AMCL needs an initial pose estimate to begin localizing.
    # Without this the robot appears unlocalized in RViz (no particle cloud,
    # no pose arrow). This is the scripted equivalent of clicking
    # "2D Pose Estimate" in RViz.
    #
    echo ""
    print_info "Publishing initial pose  (x=$INIT_X  y=$INIT_Y  yaw=${INIT_YAW_DEG}° = ${INIT_YAW} rad)..."

    # Convert yaw → quaternion z and w
    read -r QZ QW <<< "$(yaw_to_quat "$INIT_YAW")"

    INITIAL_POSE_MSG="{
      header: {
        stamp: {sec: 0, nanosec: 0},
        frame_id: 'map'
      },
      pose: {
        pose: {
          position:    {x: $INIT_X, y: $INIT_Y, z: 0.0},
          orientation: {x: 0.0, y: 0.0, z: $QZ, w: $QW}
        },
        covariance: [
          0.25, 0.0,  0.0, 0.0, 0.0, 0.0,
          0.0,  0.25, 0.0, 0.0, 0.0, 0.0,
          0.0,  0.0,  0.0, 0.0, 0.0, 0.0,
          0.0,  0.0,  0.0, 0.0, 0.0, 0.0,
          0.0,  0.0,  0.0, 0.0, 0.0, 0.0,
          0.0,  0.0,  0.0, 0.0, 0.0, 0.06853891945200942
        ]
      }
    }"

    # Retry — /initialpose subscriber inside AMCL may not be ready yet
    POSE_SET=false
    for attempt in 1 2 3 4 5; do
        if ros2 topic pub --once /initialpose \
               geometry_msgs/msg/PoseWithCovarianceStamped \
               "$INITIAL_POSE_MSG" > /dev/null 2>&1; then
            print_success "Initial pose published  (attempt $attempt)"
            POSE_SET=true
            break
        else
            print_warning "Attempt $attempt/5 — /initialpose not ready, retrying in 2s..."
            sleep 2
        fi
    done

    if [ "$POSE_SET" = false ]; then
        print_warning "Could not auto-publish initial pose."
        print_warning "Use RViz '2D Pose Estimate' button to set it manually, or"
        print_warning "re-run with the correct x y yaw values."
    fi

fi

# ── Step 6: Launch Nav2 ───────────────────────────────────────────────────────
echo ""
print_info "Starting Nav2 navigation stack..."

ros2 launch turtlebot4_navigation nav2.launch.py \
    > /tmp/nav2.log 2>&1 &
NAV2_PID=$!
PIDS+=("$NAV2_PID")

if ps -p "$NAV2_PID" > /dev/null 2>&1; then
    print_success "Nav2 launched (PID: $NAV2_PID)"
else
    print_error "Failed to launch Nav2"
    cat /tmp/nav2.log
    cleanup
    exit 1
fi

print_info "Waiting for Nav2 to initialize (3 seconds)..."
sleep 3

# ── Step 7: Launch RViz ───────────────────────────────────────────────────────
echo ""
print_info "Starting RViz visualization..."

nice -n 10 ros2 launch turtlebot4_viz view_navigation.launch.py \
    > /tmp/rviz.log 2>&1 &
RVIZ_PID=$!
PIDS+=("$RVIZ_PID")

if ps -p "$RVIZ_PID" > /dev/null 2>&1; then
    print_success "RViz launched (PID: $RVIZ_PID)"
else
    print_error "Failed to launch RViz"
    cat /tmp/rviz.log
    cleanup
    exit 1
fi

print_info "Waiting for RViz to initialize (3 seconds)..."
sleep 3

# ── Step 8: Safety Override ───────────────────────────────────────────────────
# Commented out — motion control node is not reliably available at launch time.
# To enable reverse motion manually run:
#   ros2 param set /_do_not_use/motion_control safety_override backup_only

# ── Step 9: SLAM map-save hint ────────────────────────────────────────────────
if [[ "$MODE" == "slam" ]]; then
    echo ""
    print_info "When finished mapping, save with:"
    echo "  ros2 run nav2_map_server map_saver_cli -f ~/turtlebot4/Maps/<map_name>"
fi

# ── Step 11: Summary ──────────────────────────────────────────────────────────
echo ""
print_header "Setup Complete — All Services Running"

echo "Mode: $MODE"
echo ""
echo "Active Services:"
if [[ "$MODE" == "slam" ]]; then
    echo "  • SLAM          (PID: $SLAM_PID)"
else
    echo "  • Localization  (PID: $LOCALIZATION_PID)"
    echo "  • Initial Pose  x=$INIT_X  y=$INIT_Y  yaw=${INIT_YAW_DEG}° (${INIT_YAW} rad)"
fi
echo "  • Nav2          (PID: $NAV2_PID)"
echo "  • RViz          (PID: $RVIZ_PID)"
echo ""
echo "Environment:"
echo "  • ROS_DOMAIN_ID:      $ROS_DOMAIN_ID"
echo "  • RMW_IMPLEMENTATION: $RMW_IMPLEMENTATION"
[[ "$MODE" == "localization" ]] && echo "  • Map:                $MAP_FILE"
echo ""
echo "Logs:"
[[ "$MODE" == "slam" ]] && echo "  • /tmp/slam.log"
[[ "$MODE" == "localization" ]] && echo "  • /tmp/localization.log"
echo "  • /tmp/nav2.log"
echo "  • /tmp/rviz.log"
echo ""
print_success "Ready for navigation!"
echo ""
echo "To stop all services: Ctrl+C"
echo "To run the navigation assistant in another terminal:"
echo "  cd ~/turtlebot4/turtlebot4_ws"
echo "  source /opt/ros/$ROS_DISTRO/setup.bash"
echo "  export ROS_DOMAIN_ID=$ROS_DOMAIN_ID"
echo "  export RMW_IMPLEMENTATION=$RMW_IMPLEMENTATION"
echo "  python3 main.py --no-launch"
echo ""
print_header "Monitoring Services (Ctrl+C to stop)"

# ── Monitor loop ──────────────────────────────────────────────────────────────
while true; do
    sleep 5
    for pid in "${PIDS[@]}"; do
        if ! ps -p "$pid" > /dev/null 2>&1; then
            echo ""
            print_error "Process $pid has terminated unexpectedly!"
            print_info "Check logs in /tmp/ for details."
            cleanup
            exit 1
        fi
    done
done



