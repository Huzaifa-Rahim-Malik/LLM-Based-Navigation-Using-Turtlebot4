#!/usr/bin/env python3
"""
Automated robot trials: types the commands for you, drives the robot, times it, counts bumps and
appends one row per trial to eval/results/navigation_trials.csv (same columns as the template, so
`summarize.py nav` works unchanged).

It uses the SAME code path as the assistant:
    IntentDetector -> LocationExtractor (rules + LLM fallback) -> RobotNavigator.navigate_to_location

Needs: robot stack running (./scripts/robot_launch.sh), ROS 2 sourced (source scripts/setup.bash),
       and `ollama serve` running. Run from the repository root:

    # 1. Check what the assistant understands WITHOUT moving the robot (no ROS needed)
    python3 eval/auto_nav_trials.py --routes "Home>Lawn" "Lawn>Home" --dry-run

    # 2. Real run: 2 routes x 5 runs + 3 unknown places
    python3 eval/auto_nav_trials.py --routes "Home>Lawn" "Lawn>Home" --runs 5

    # robot has a namespace / different hazard topic:
    python3 eval/auto_nav_trials.py --routes "Home>Lawn" --hazard-topic /robot1/hazard_detection

Between runs the robot is sent back to the start location through Nav2 (not timed), or, with
--manual-reset, you put it back by hand and press Enter. Keep a hand on the robot / e-stop.
"""
import argparse
import csv
import math
import os
import re
import sys
import time

from common import RESULTS, SRC, QuietLogger   # common.py puts src/ on sys.path

COLUMNS = ["type", "command", "start", "expected_target", "understood", "reached",
           "start_to_goal_s", "collisions", "failure_note"]
DEFAULT_INVALID = ["go to the moon", "go to mars", "take me to narnia"]


# ── command resolution (same logic as eval_nlu.py) ────────────────────────────────────────────

def to_key(res):
    if res is None or res == []:
        return "NONE"
    if isinstance(res, tuple):
        return "AMBIGUOUS"
    if isinstance(res, dict):
        return f"{res['x']:g},{res['y']:g}"
    if isinstance(res, list):
        return "AMBIGUOUS"
    return str(res)


def build_nlu(model, gpu):
    from intent_detector import IntentDetector
    from location_extractor import LocationExtractor
    from location_manager import LocationManager
    from response_generator import InferenceConfig

    logger = QuietLogger()
    lm = LocationManager(logger, os.path.join(SRC, "locations.yaml"))
    cfg = InferenceConfig()
    cfg.set_model(model)
    cfg.set_gpu(gpu)
    ex = LocationExtractor(logger, lm, model=model, inference_config=cfg)
    ex.disambiguate_location = lambda matches: ("AMBIGUOUS", list(matches))   # no user to ask
    return ex, IntentDetector(logger), lm


def resolve(ex, idet, command):
    """Returns (target_object, key). target_object is what navigate_to_location() needs."""
    if idet.detect_intent(command) != "navigate":
        return None, "NONE"
    res = ex.extract_location(command)
    key = to_key(res)
    return (res if key not in ("NONE", "AMBIGUOUS") else None), key


def norm_expected(s):
    m = re.fullmatch(r"\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*", s or "")
    return f"{float(m.group(1)):g},{float(m.group(2)):g}" if m else (s or "").strip()


# ── ROS side (imported lazily so --dry-run works on any PC) ───────────────────────────────────

class HazardCounter:
    """Counts bump events of the TurtleBot 4 base (/hazard_detection). Bumps closer than 1 s count once."""
    def __init__(self, node, topic):
        self.count, self.armed, self._last, self.available = 0, False, 0.0, False
        try:
            from irobot_create_msgs.msg import HazardDetection, HazardDetectionVector
            from rclpy.qos import qos_profile_sensor_data
        except ImportError:
            print("[warn] irobot_create_msgs not found - collisions will be left empty")
            return
        self._bump = HazardDetection.BUMP
        node.create_subscription(HazardDetectionVector, topic, self._cb, qos_profile_sensor_data)
        self.available = True

    def _cb(self, msg):
        if self.armed and any(d.type == self._bump for d in msg.detections):
            now = time.monotonic()
            if now - self._last > 1.0:
                self.count += 1
                self._last = now

    def start(self):
        self.count, self.armed = 0, True

    def stop(self):
        self.armed = False
        return self.count if self.available else ""


class PoseTracker:
    """Own /amcl_pose subscription with the QoS AMCL publishes with (transient-local), so the last
    pose is received even if it was published before this script started."""
    def __init__(self, node, topic):
        from geometry_msgs.msg import PoseWithCovarianceStamped
        from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
        qos = QoSProfile(history=HistoryPolicy.KEEP_LAST, depth=1,
                         durability=DurabilityPolicy.TRANSIENT_LOCAL,
                         reliability=ReliabilityPolicy.RELIABLE)
        self.pos = None
        node.create_subscription(PoseWithCovarianceStamped, topic, self._cb, qos)

    def _cb(self, msg):
        p = msg.pose.pose.position
        self.pos = {"x": p.x, "y": p.y}


def publish_initial_pose(node, x, y, yaw, topic="/initialpose", repeats=3):
    """Same message RViz '2D Pose Estimate' sends. Needs the robot to really be at (x, y, yaw)."""
    from geometry_msgs.msg import PoseWithCovarianceStamped
    pub = node.create_publisher(PoseWithCovarianceStamped, topic, 10)
    msg = PoseWithCovarianceStamped()
    msg.header.frame_id = "map"
    msg.pose.pose.position.x, msg.pose.pose.position.y = x, y
    msg.pose.pose.orientation.z, msg.pose.pose.orientation.w = math.sin(yaw / 2), math.cos(yaw / 2)
    cov = [0.0] * 36
    cov[0] = cov[7] = 0.25          # x, y variance (RViz default)
    cov[35] = 0.0685                # yaw variance (RViz default)
    msg.pose.covariance = cov
    time.sleep(2.0)                 # let AMCL's subscriber be discovered
    for _ in range(repeats):
        msg.header.stamp = node.get_clock().now().to_msg()
        pub.publish(msg)
        time.sleep(1.0)
    print(f"Published initial pose x={x} y={y} yaw={yaw} on {topic}")


def goal_xy(lm, target):
    if isinstance(target, dict):
        return target["x"], target["y"]
    loc = lm.get_location(target)
    return loc["x"], loc["y"]


# ── one trial ─────────────────────────────────────────────────────────────────────────────────

def go_to_start(nav, lm, start, tol, manual, trust_nav2=False):
    if manual:
        input(f"  Put the robot on '{start}' and press Enter... ")
        return True
    if not nav.navigate_to_location(start):
        return False
    pos = nav.get_current_position()
    if pos is None:
        return trust_nav2                       # Nav2 said it arrived; no pose to double-check
    x, y = goal_xy(lm, start)
    return math.hypot(pos["x"] - x, pos["y"] - y) <= tol


def run_trial(nav, hz, ex, idet, lm, trial, args):
    ttype, command, start, expected = trial
    row = dict(type=ttype, command=command, start=start, expected_target=expected,
               understood="", reached="", start_to_goal_s="", collisions="", failure_note="")

    if start and not go_to_start(nav, lm, start, args.tolerance, args.manual_reset,
                                   args.no_pose_check):
        row["failure_note"] = f"SETUP FAILED: could not reach start '{start}' - row not valid"
        return row, False
    time.sleep(args.settle)

    target, key = resolve(ex, idet, command)

    if expected == "NONE":                                   # must be refused
        row["understood"] = int(key == "NONE")
        if key != "NONE":
            row["failure_note"] = f"did not refuse: resolved to {key} (robot NOT moved by this script)"
        return row, True

    row["understood"] = int(key.lower() == norm_expected(expected).lower())
    if not row["understood"]:
        row["reached"] = 0
        row["failure_note"] = f"resolved to {key} (robot NOT moved by this script)"
        return row, True

    gx, gy = goal_xy(lm, target)
    hz.start()
    t0 = time.perf_counter()
    ok = nav.navigate_to_location(target)
    elapsed = time.perf_counter() - t0
    row["collisions"] = hz.stop()
    time.sleep(1.0)                                          # let AMCL settle before reading the pose
    pos = nav.get_current_position()
    err = math.hypot(pos["x"] - gx, pos["y"] - gy) if pos else float("inf")

    row["reached"] = int(ok and (err <= args.tolerance or (pos is None and args.no_pose_check)))
    if row["reached"]:
        row["start_to_goal_s"] = round(elapsed, 1)
        if elapsed < 2.0:
            row["failure_note"] = "suspiciously short - robot may already have been at the goal"
    else:
        row["failure_note"] = ("Nav2 reported failure/timeout" if not ok
                               else "no /amcl_pose to verify the position" if pos is None
                               else f"stopped {err:.2f} m from goal (tolerance {args.tolerance} m)")
    return row, True


# ── CSV + plan ────────────────────────────────────────────────────────────────────────────────

def append_row(path, row):
    new = not os.path.exists(path)
    if not new:
        with open(path, encoding="utf-8") as f:
            header = next((l for l in f if not l.lstrip().startswith("#")), "").strip()
        if header != ",".join(COLUMNS):
            raise SystemExit(f"{path} has the old column layout.\n"
                             f"Copy the new template first:  cp eval/navigation_trials_template.csv {path}")
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        if new:
            w.writeheader()
        w.writerow(row)


def build_plan(args):
    plan = []
    for route in args.routes:
        if ">" not in route:
            raise SystemExit(f"route '{route}' must look like  Start>Goal  (names as in locations.yaml)")
        start, goal = [s.strip() for s in route.split(">", 1)]
        for _ in range(args.runs):
            plan.append(("named", args.template.format(goal=goal), start, goal))
    for cmd in args.invalid:
        plan.append(("invalid", cmd, "", "NONE"))
    return plan


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--routes", nargs="+", required=True, metavar="START>GOAL")
    ap.add_argument("--runs", type=int, default=5, help="runs per route (default 5)")
    ap.add_argument("--invalid", nargs="*", default=DEFAULT_INVALID, help="commands that must be refused")
    ap.add_argument("--template", default="go to {goal}", help='command wording, e.g. "take me to {goal}"')
    ap.add_argument("--out", default=os.path.join(RESULTS, "navigation_trials.csv"))
    ap.add_argument("--tolerance", type=float, default=0.35, help="max metres from the goal to count as reached")
    ap.add_argument("--settle", type=float, default=2.0, help="seconds to wait after returning to the start")
    ap.add_argument("--hazard-topic", default="/hazard_detection")
    ap.add_argument("--pose-topic", default="/amcl_pose", help="add your namespace here if the robot has one")
    ap.add_argument("--init-pose", nargs=3, type=float, metavar=("X", "Y", "YAW"),
                    help="publish this initial pose (map frame, yaw in radians) to /initialpose before starting; "
                         "must match where the robot REALLY is, e.g. --init-pose 1.0 0.0 1.57 for Lawn")
    ap.add_argument("--no-pose-check", action="store_true",
                    help="continue without /amcl_pose; 'reached' then means only 'Nav2 said SUCCEEDED' (say so in the README)")
    ap.add_argument("--model", default="llama3.2:3b")
    ap.add_argument("--gpu", action="store_true")
    ap.add_argument("--manual-reset", action="store_true", help="you place the robot on the start spot each time")
    ap.add_argument("--dry-run", action="store_true", help="only show how each command is understood; no ROS, no motion")
    ap.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    args = ap.parse_args()

    ex, idet, lm = build_nlu(args.model, args.gpu)
    plan = build_plan(args)
    for _, _, start, goal in plan:
        for name in (start, goal):
            if name and name != "NONE" and not lm.location_exists(name):
                raise SystemExit(f"'{name}' is not in src/locations.yaml")

    if args.dry_run:
        print(f"{'command':<40} {'expected':<16} understood-as")
        for ttype, cmd, _, expected in plan:
            _, key = resolve(ex, idet, cmd)
            ok = key.lower() == norm_expected(expected).lower()
            print(f"{cmd:<40} {expected:<16} {key}  {'OK' if ok else '<-- MISMATCH'}")
        return

    print(f"{len(plan)} trials -> {args.out}")
    print("The robot will drive by itself. Clear the area, keep a hand on the e-stop. Ctrl+C cancels.")
    if not args.yes and input("Type 'yes' to start: ").strip().lower() != "yes":
        return

    os.environ["RMW_IMPLEMENTATION"] = "rmw_fastrtps_cpp"        # same as main.py
    import rclpy
    from robot_navigator import RobotNavigator
    rclpy.init()
    node = rclpy.create_node("auto_nav_trials")
    hz = HazardCounter(node, args.hazard_topic)                  # before RobotNavigator starts spinning the node
    tracker = PoseTracker(node, args.pose_topic)
    if args.init_pose:
        publish_initial_pose(node, *args.init_pose)
    nav = RobotNavigator(node.get_logger(), lm, node)
    nav.navigator.waitUntilNav2Active()
    # Nav2 is confirmed active; stop navigate_to_location() re-waiting (~4 s) inside every timed drive
    nav.navigator.waitUntilNav2Active = lambda *a, **k: None
    _own_pose = nav.get_current_position
    nav.get_current_position = lambda: tracker.pos or _own_pose()

    pos = nav.get_current_position()
    if pos is None and not args.no_pose_check:
        print(f"\nNo pose received on {args.pose_topic} - localization is not publishing, so the script cannot "
              "verify that the robot is on the start spot / at the goal.\n"
              "  1. In RViz set '2D Pose Estimate' (or re-run robot_launch.sh with the real x y yaw) and rotate "
              "the robot a little.\n"
              f"  2. Check:  ros2 topic info {args.pose_topic} -v     (wrong name/namespace? use --pose-topic)\n"
              "  3. Or continue unverified with --no-pose-check.")
        nav.shutdown()
        rclpy.shutdown()
        sys.exit(1)
    print(f"Robot pose at start: x={pos['x']:.2f} y={pos['y']:.2f}" if pos else "Robot pose unknown (--no-pose-check)")

    done = 0
    try:
        for i, trial in enumerate(plan, 1):
            print(f"[{i}/{len(plan)}] {trial[2] or '-'} : {trial[1]!r}  (expect {trial[3]})")
            row, valid = run_trial(nav, hz, ex, idet, lm, trial, args)
            print("   ->", {k: v for k, v in row.items() if v != ""})
            if not valid:
                print("   Setup failed; stopping so the CSV is not polluted. Fix the pose and re-run the rest.")
                break
            append_row(args.out, row)
            done += 1
    except KeyboardInterrupt:
        print("\nInterrupted - cancelling the current goal")
        try:
            nav.navigator.cancelTask()
        except Exception:
            pass
    finally:
        nav.shutdown()
        rclpy.shutdown()
    print(f"{done} rows written to {args.out}\nNext: python3 eval/summarize.py nav {args.out}")


if __name__ == "__main__":
    main()
