#!/usr/bin/env python

import os
import subprocess
import sys
import time
from collections import OrderedDict
from math import degrees

# Messages
from ff_msgs.msg import (
    AgentStateStamped,
    ArmStateStamped,
    CameraState,
    CameraStatesStamped,
    DataToDiskState,
    DiskStateStamped,
    EkfState,
    FaultState,
    GuestScienceConfig,
    GuestScienceData,
    GuestScienceState,
    JointSampleStamped,
    LocalizationState,
    MobilityState,
    OpState,
    SaveSettings,
    VisualLandmarks,
)
from rospy import Subscriber
from sensor_msgs.msg import BatteryState

## Custom imports
# filepath = os.path.dirname(os.path.realpath(__file__))
# sys.path.append(os.path.join(filepath, "../../common"))
# from utils import Queue, euler_from_quaternion
from util.utils import Queue, euler_from_quaternion

# from tf.transformations import euler_from_quaternion, quaternion_from_euler


class TelemetryFeedback(object):
    def __init__(self, summary="none", description="none", data=OrderedDict()):
        self.summary = summary
        self.description = description
        self.data = data
        self.rows = -1
        self.id = None
        self.success = True


class TelemetryHandler(object):
    OPERATING_STATE = {
        OpState.READY: "Ready",
        OpState.PLAN_EXECUTION: "Plan Execution",
        OpState.TELEOPERATION: "Teleoperation",
        OpState.AUTO_RETURN: "Auto Return",
        OpState.FAULT: "Fault",
    }

    MOBILITY_STATE = {
        MobilityState.DRIFTING: "Drifting",
        MobilityState.STOPPING: "Stopping",
        MobilityState.FLYING: "Flying",
        MobilityState.DOCKING: "Docking",
        MobilityState.PERCHING: "Perching",
    }

    def __init__(self, node):
        self.node = node
        self.feedback_telemetry = Queue()
        self.ekf_state = EkfState()
        self.loc_state = LocalizationState()
        self.agent_state = AgentStateStamped()
        self.bagger_state = DataToDiskState()
        self.arm_joint_sample = JointSampleStamped()
        self.arm_state = ArmStateStamped()
        self.arm_tilt_angle = -1
        self.arm_pan_angle = -1
        self.arm_gripper_angle = -1
        self.ml_features = VisualLandmarks()
        self.ar_features = VisualLandmarks()
        self.sys_monitor_state = FaultState()
        self.camera_states = CameraStatesStamped()
        self.nav_cam_state = None
        self.dock_cam_state = None
        self.perch_cam_state = None
        self.haz_cam_state = None
        self.sci_cam_state = None
        self.gs_config = GuestScienceConfig()
        self.gs_state = GuestScienceState()
        self.gs_data_queue = Queue()
        self.battery_tl_state = BatteryState()
        self.battery_tr_state = BatteryState()
        self.battery_bl_state = BatteryState()
        self.battery_br_state = BatteryState()
        self.llp_data_state = DiskStateStamped()
        self.mlp_data_state = DiskStateStamped()
        self._start_subscribers()

    def _start_subscribers(self):
        self.node.add_subscriber("ekf", "/gnc/ekf", self.ekf_callback, EkfState)
        self.node.add_subscriber(
            "loc_state",
            "/loc/manager/state",
            self.loc_state_callback,
            LocalizationState,
        )
        self.node.add_subscriber(
            "agent_state",
            "/mgt/executive/agent_state",
            self.agent_state_callback,
            AgentStateStamped,
        )
        self.node.add_subscriber(
            "bagger_state",
            "/mgt/data_bagger/state",
            self.bagger_state_callback,
            DataToDiskState,
        )
        self.node.add_subscriber(
            "arm_joint_sample",
            "beh/arm/joint_sample",
            self.arm_joint_sample_callback,
            JointSampleStamped,
        )
        self.node.add_subscriber(
            "arm_state", "/beh/arm/arm_state", self.arm_state_callback, ArmStateStamped
        )
        self.node.add_subscriber(
            "ml_features",
            "/loc/ml/features",
            self.ml_features_callback,
            VisualLandmarks,
        )
        self.node.add_subscriber(
            "ar_features",
            "/loc/ar/features",
            self.ar_features_callback,
            VisualLandmarks,
        )
        self.node.add_subscriber(
            "sys_monitor_state",
            "/mgt/sys_monitor/state",
            self.sys_monitor_state_callback,
            FaultState,
        )
        self.node.add_subscriber(
            "camera_states",
            "/mgt/camera_state",
            self.camera_state_callback,
            CameraStatesStamped,
        )
        self.node.add_subscriber(
            "gs_config",
            "/gs/gs_manager/config",
            self.gs_config_callback,
            GuestScienceConfig,
        )
        self.node.add_subscriber(
            "gs_state",
            "/gs/gs_manager/state",
            self.gs_state_callback,
            GuestScienceState,
        )
        self.node.add_subscriber(
            "gs_data", "/gs/data", self.gs_data_callback, GuestScienceData
        )
        self.node.add_subscriber(
            "battery_tl",
            "/hw/eps/battery/top_left/state",
            self.battery_tl_callback,
            BatteryState,
        )
        self.node.add_subscriber(
            "battery_tr",
            "/hw/eps/battery/top_right/state",
            self.battery_tr_callback,
            BatteryState,
        )
        self.node.add_subscriber(
            "battery_bl",
            "/hw/eps/battery/bottom_left/state",
            self.battery_bl_callback,
            BatteryState,
        )
        self.node.add_subscriber(
            "battery_br",
            "/hw/eps/battery/bottom_right/state",
            self.battery_br_callback,
            BatteryState,
        )
        self.node.add_subscriber(
            "disk_monitor",
            "/mgt/disk_monitor/state",
            self.disk_monitor_callback,
            DiskStateStamped,
        )

    def ekf_callback(self, data):
        self.ekf_state = data

    def loc_state_callback(self, data):
        self.loc_state = data

    def agent_state_callback(self, data):
        self.agent_state = data

    def bagger_state_callback(self, data):
        self.bagger_state = data

    def arm_joint_sample_callback(self, data):
        self.arm_joint_sample = data
        for joint in data.samples:
            if joint.name == "tilt":
                self.arm_tilt_angle = joint.angle_pos
            elif joint.name == "pan":
                self.arm_pan_angle = joint.angle_pos
            elif joint.name == "gripper":
                self.arm_gripper_angle = joint.angle_pos

    def arm_state_callback(self, data):
        self.arm_state = data

    def ml_features_callback(self, data):
        self.ml_features = data

    def ar_features_callback(self, data):
        self.ar_features = data

    def sys_monitor_state_callback(self, data):
        self.sys_monitor_state = data

    def camera_state_callback(self, data):
        self.camera_states = data
        for s in data.states:
            if s.camera_name == "nav_cam":
                self.nav_cam_state = s
            elif s.camera_name == "dock_cam":
                self.dock_cam_state = s
            elif s.camera_name == "perch_cam":
                self.perch_cam_state = s
            elif s.camera_name == "haz_cam":
                self.haz_cam_state = s
            elif s.camera_name == "sci_cam":
                self.sci_cam_state = s

    def gs_config_callback(self, data):
        self.gs_config = data

    def gs_state_callback(self, data):
        self.gs_state = data

    def gs_data_callback(self, data):
        self.gs_data_queue.enqueue(data)

    def battery_tl_callback(self, data):
        self.battery_tl_state = data

    def battery_tr_callback(self, data):
        self.battery_tr_state = data

    def battery_bl_callback(self, data):
        self.battery_bl_state = data

    def battery_br_callback(self, data):
        self.battery_br_state = data

    def disk_monitor_callback(self, data):
        if data.processor_name == "llp":
            self.llp_data_state = data
        if data.processor_name == "mlp":
            self.mlp_data_state = data

    """ Admin actions """

    def action_ekf(self, args):
        if args.get:
            tel = TelemetryFeedback("EKF State", "Robot pose")
            tel.data = self._get_pose()[0]
            tel.rows = 2
            self.feedback_telemetry.enqueue(tel)
        else:
            return False
        return True

    def action_loc(self, args):
        if args.get:
            state = TelemetryFeedback("Localization State", "Manager state")
            state.data = self._get_loc_pipeline()[0]
            self.feedback_telemetry.enqueue(state)
        else:
            return False
        return True

    """ Settings actions """

    def action_telemetry(self, args):
        if args.get:
            state = TelemetryFeedback("DDS Telemetry", "Show rates")
            state.data["info"] = "telemetry -get is not implemented yet"
            self.feedback_telemetry.enqueue(state)
        else:
            return False
        return True

    def action_obstacles(self, args):
        if args.get:
            state = TelemetryFeedback("Check obstacles", "")
            state.data = OrderedDict()
            state.data["enabled"] = self.agent_state.check_obstacles
            self.feedback_telemetry.enqueue(state)
        else:
            return False
        return True

    def action_zones(self, args):
        if args.get:
            state = TelemetryFeedback("Zones", "State")
            state.data["info"] = "zones -get is not implemented yet"
            self.feedback_telemetry.enqueue(state)
        else:
            return False
        return True

    def action_limits(self, args):
        if args.get:
            state = TelemetryFeedback("Operating limits", "")
            state.data = OrderedDict()
            state.data["profile_name"] = self.agent_state.profile_name
            state.data["flight_mode"] = self.agent_state.flight_mode
            state.data["linear_velocity"] = self.agent_state.target_linear_velocity
            state.data["linear_accel"] = self.agent_state.target_linear_accel
            state.data["angular_velocity"] = self.agent_state.target_angular_velocity
            state.data["angular_accel"] = self.agent_state.target_angular_accel
            state.data["collision_distance"] = self.agent_state.collision_distance
            self.feedback_telemetry.enqueue(state)
        else:
            return False
        return True

    def action_ff(self, args):
        if args.get:
            state = TelemetryFeedback("Face Forward", "")
            state.data = OrderedDict()
            state.data["enabled"] = not self.agent_state.holonomic_enabled
            self.feedback_telemetry.enqueue(state)
        else:
            return False
        return True

    def action_camera(self, args):
        if args.get:
            options = [True] * 5
            arg_options = [args.nav, args.dock, args.perch, args.haz, args.sci]
            # Check arguments, if any was given then select data to show
            # Otherwise just show it all
            for opt in arg_options:
                if opt != False:
                    options = arg_options
                    break
            state = TelemetryFeedback("Camera", "State")
            self._action_camera_fill_state(state, options)
            self.feedback_telemetry.enqueue(state)

    def _action_camera_fill_state(self, state, options):
        names = ["nav", "dock", "perch", "haz", "sci"]
        state.data = OrderedDict()
        for i, opt in enumerate(options):
            cam_state = getattr(self, names[i] + "_cam_state")
            if opt is not False:
                if cam_state is None:
                    state.data[names[i] + "_cam"] = "Not available"
                    continue
                state.data[names[i] + "_streaming"] = cam_state.streaming
                state.data[names[i] + "_stream_width"] = cam_state.stream_width
                state.data[names[i] + "_stream_height"] = cam_state.stream_height
                state.data[names[i] + "_stream_rate"] = cam_state.stream_rate
                state.data[names[i] + "_recording"] = cam_state.recording
                state.data[names[i] + "_record_width"] = cam_state.record_width
                state.data[names[i] + "_record_height"] = cam_state.record_height
                state.data[names[i] + "_record_rate"] = cam_state.record_rate
                state.data[names[i] + "_bandwidth"] = cam_state.bandwidth

    def action_planner(self, args):
        if args.get:
            state = TelemetryFeedback("Planner", "")
            state.data = OrderedDict()
            state.data["name"] = self.agent_state.planner
            self.feedback_telemetry.enqueue(state)
        else:
            return False
        return True

    def action_bagger(self, args):
        state = TelemetryFeedback("Bagger", "State")
        state.data = OrderedDict()
        if args.get:
            state.data["profile_name"] = self.bagger_state.name
            state.data["recording"] = self.bagger_state.recording
            state.data["topic_count"] = len(self.bagger_state.topic_save_settings)
        elif args.list:
            state.description = "State and Topics"
            state.data["profile_name"] = self.bagger_state.name
            state.data["recording"] = self.bagger_state.recording
            topics = []
            for t in self.bagger_state.topic_save_settings:
                download = "unknown"
                if t.downlinkOption == SaveSettings.IMMEDIATE:
                    download = "inmmediate"
                elif t.downlinkOption == SaveSettings.DELAYED:
                    download = "delayed"
                topics.append(
                    {
                        "name": t.topic_name,
                        "frequency": t.frequency,
                        "download": download,
                    }
                )
            state.data["topics"] = topics
        else:
            return False
        self.feedback_telemetry.enqueue(state)
        return True

    """ Mobility commands """

    def action_dock(self, args):
        if args.get:
            state = TelemetryFeedback("Astrobee dock state", "Show dock state")
            state.data["info"] = "dock -get pending implementation"
            self.feedback_telemetry.enqueue(state)
        else:
            return False
        return True

    """ Arm commands """

    def action_arm(self, args):
        state = TelemetryFeedback("Arm", "State")
        if args.get:
            state.data = OrderedDict()
            state.data["name"] = "Pending implementation"
            self.feedback_telemetry.enqueue(state)
        else:
            return False
        return True

    """ Hardware commands """

    def action_light(self, args):
        if args.get:
            state = TelemetryFeedback("Lights", "State")
            state.data = OrderedDict()
            state.data["info"] = "lights -get is not implemented yet"
            self.feedback_telemetry.enqueue(state)
        else:
            return False
        return True

    def action_power(self, args):
        if args.get:
            state = TelemetryFeedback("DDS Telemetry", "Show power states")
            state.data = OrderedDict()
            state.data["info"] = "power -get is not implemented yet"
            self.feedback_telemetry.enqueue(state)
        else:
            return False
        return True

    def action_gs(self, args):
        state = TelemetryFeedback("GS", "")
        if args.list:
            state.description = "Available APKs"
            state.data = OrderedDict()
            for idx, apk in enumerate(self.gs_config.apks):
                apk_state = "Running" if self.gs_state.runningApks[idx] else "Idle"
                state.data[apk.short_name] = apk_state
            self.feedback_telemetry.enqueue(state)
        elif args.get != None:
            state.description = "APK info"
            state.data = OrderedDict()
            for idx, apk in enumerate(self.gs_config.apks):
                if apk.short_name == args.get or apk.apk_name == args.get:
                    apk_state = "Running" if self.gs_state.runningApks[idx] else "Idle"
                    state.data["name"] = apk.apk_name
                    state.data["short_name"] = apk.short_name
                    state.data["state"] = apk_state
                    state.data["primary"] = apk.primary
                    state.data["commands"] = "++"
                    for cmd in apk.commands:
                        state.data[cmd.name] = cmd.command
                    self.feedback_telemetry.enqueue(state)
                    return True
            if len(state.data) == 0:
                state.data["ERROR"] = "APK not found"
                self.feedback_telemetry.enqueue(state)
        else:
            return False
        return True

    """ Plan commands """

    def action_plan(self, args):
        if args.get:
            state = TelemetryFeedback("DDS Telemetry", "Show current plan info")
            state.data = OrderedDict()
            state.data["info"] = "plan -get is not implemented yet"
            self.feedback_telemetry.enqueue(state)
        else:
            return False
        return True

    """ Shell commands """

    def action_shell(self, args):
        state = TelemetryFeedback("SHELL", "")
        cmd = " ".join(args.command)
        state.description = cmd
        state.data = OrderedDict()
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True
            )
            out, err = proc.communicate()
            state.data["retcode"] = proc.returncode
            state.success = proc.returncode == 0
            if out:
                state.data["stdout"] = "\n\n" + out.decode("utf-8")
            if err:
                state.data["stderr"] = "\n\n" + err.decode("utf-8")
        except Exception as e:
            state.data["exception"] = "\n\n" + str(e)
            state.success = False
        self.feedback_telemetry.enqueue(state)
        return True

    def action_eval(self, args):
        state = TelemetryFeedback("EVAL", "")
        state.data = OrderedDict()
        state.data["result"] = eval(args.expression)
        state.success = True
        self.feedback_telemetry.enqueue(state)
        return True

    """ Execute built-in functions """

    def action_function(self, args):
        func_name = "_" + args.function_name
        func = getattr(self, func_name, lambda x: False)
        return func(args)

    """ Built-in functions """

    def _get_ml_count(self, args):
        state = TelemetryFeedback("MLP_COUNT", "")
        state.description = "Feature count with timeout of %d seconds" % args.timeout
        state.data = OrderedDict()
        state.data["observations"] = self._get_ml_observations(args.timeout)
        self.feedback_telemetry.enqueue(state)
        return True

    def _assert_ml_count(self, args):
        state = TelemetryFeedback("CHECKING ML", "")
        observations = self._get_ml_observations(args.timeout)
        state.description = "Feature count. Timeout of %d seconds" % args.timeout
        state.success = False
        positives = 0
        for n in observations:
            if n > 0:
                positives += 1
            if positives == args.min_positives:
                state.success = True
                break
        state.data["observations"] = observations
        self.feedback_telemetry.enqueue(state)
        return True

    def _assert_pose(self, args):
        state = TelemetryFeedback("ASSERT POSE", "")
        state.data, pose = self._get_pose()
        non_zero_pose = not (
            pose.position.x == 0
            and pose.position.y == 0
            and pose.position.z == 0
            and pose.orientation.x == 0
            and pose.orientation.y == 0
            and pose.orientation.z == 0
            and pose.orientation.w == 0
        )
        state.success = non_zero_pose
        self.feedback_telemetry.enqueue(state)
        return True

    def _assert_ml_pipeline(self, args):
        state = TelemetryFeedback("ASSERT ML PIPELINE", "")
        state.data, loc_state = self._get_loc_pipeline()
        state.success = (
            # TODO Change this to constants from FSW
            loc_state.fsm_state == "LOCALIZING"
            and loc_state.pipeline.name == "Sparse map"
        )
        self.feedback_telemetry.enqueue(state)
        return True

    def _assert_docked_state(self, args):
        state = TelemetryFeedback("ASSERT DOCKED STATE", "")
        mob_state = self.agent_state.mobility_state
        state.success = (
            mob_state.state == MobilityState.DOCKING and mob_state.sub_state == 0
        )
        state.data = OrderedDict()
        state.data["state"] = mob_state.state
        state.data["sub_state"] = mob_state.sub_state
        state.description = "DOCKED" if state.success else "NOT DOCKED"
        self.feedback_telemetry.enqueue(state)
        return True

    def _assert_no_faults(self, args):
        state = TelemetryFeedback("ASSERT_NO_FAULTS", "")
        faults = self.sys_monitor_state.faults
        state.success = len(faults) == 0
        state.data = OrderedDict()
        for f in faults:
            state.data[f.id] = f.msg
        self.feedback_telemetry.enqueue(state)
        return True

    def _no_op(self, args):
        state = TelemetryFeedback("NOOP", "")
        state.success = True
        self.feedback_telemetry.enqueue(state)
        return True

    """ Helper functions """

    def _get_loc_pipeline(self):
        data = OrderedDict()
        state = self.loc_state
        data["event"] = state.fsm_event
        data["state"] = state.fsm_state
        data["pipeline"] = state.pipeline.name
        return (data, state)

    def _get_ml_observations(self, timeout=0):
        timeout = time.time() + timeout
        seq = -1
        observations = []
        while True:
            msg = self.ml_features
            if seq != msg.header.seq:
                seq = msg.header.seq
                observations.append(len(msg.landmarks))
            if time.time() > timeout:
                break
        return observations

    def _get_pose(self):
        pose = self.ekf_state.pose
        rot = euler_from_quaternion(
            pose.orientation.x,
            pose.orientation.y,
            pose.orientation.z,
            pose.orientation.w,
        )
        data = OrderedDict()
        data["pos_x"] = pose.position.x
        data["pos_y"] = pose.position.y
        data["pos_z"] = pose.position.z
        data["rot_x"] = degrees(rot[0])
        data["rot_y"] = degrees(rot[1])
        data["rot_z"] = degrees(rot[2])
        return (data, pose)

    # TODO
    def _enqueue_feedback(self, summary, description, data):
        state = TelemetryFeedback(summary, description, data)
        self.feedback_telemetry.enqueue(state)
