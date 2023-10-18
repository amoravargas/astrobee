#!/usr/bin/env python
import json
import math
import os
import sys
import time

from ff_msgs.msg import (
    AckStamped,
    ArmGoal,
    CommandArg,
    CommandConstants,
    CommandStamped,
    CompressedFile,
    CompressedFileAck,
)
from rospy import Time, get_rostime
from std_msgs.msg import Header

# from tf.transformations import quaternion_from_euler, quaternion_multiply
# Custom imports
filepath = os.path.dirname(os.path.realpath(__file__))
# sys.path.append(os.path.join(filepath, "../../common"))
# from utils import Queue, quaternion_from_euler
from util.utils import Queue, quaternion_from_euler


class Command(object):
    def __init__(self, id=None, seq=None, name=None):
        self.id = id
        self.seq = seq
        self.name = name


class CommandFeedback(object):
    STATUS_VALUES = {
        0: "QUEUED",  # Command is in a queue and waiting to be executed
        1: "EXECUTING",  # Command is being executed
        2: "REQUEUED",  # Command is paused and waiting to be restarted
        3: "COMPLETED",  # Command is finished
    }

    COMPLETED_STATUS_VALUES = {
        0: "NOT",  # Command not completed
        1: "OK",  # Command completed successfully
        2: "BAD_SYNTAX",  # Command not recognized, bad parameters, etc.
        3: "EXEC_FAILED",  # Command failed to execute
        4: "CANCELED",  # Command was canceled by operator
    }

    def __init__(self):
        self.id = self.status = self.completed_status = self.message = None
        self.str_status = self.str_completed_status = None

    def translate_status(self):
        self.str_status = CommandFeedback.STATUS_VALUES.get(self.status, "INVALID")
        self.str_completed_status = CommandFeedback.COMPLETED_STATUS_VALUES.get(
            self.completed_status, "INVALID"
        )

    def get_not_none_values(self):
        self.translate_status()
        inst_variables = vars(self)
        return {k: v for k, v in inst_variables.items() if v is not None}


class CommandHandler(object):
    LOC_CHOICES = {
        "ml": CommandConstants.PARAM_NAME_LOCALIZATION_MODE_MAPPED_LANDMARKS,
        "ar": CommandConstants.PARAM_NAME_LOCALIZATION_MODE_ARTAGS,
        "handrail": CommandConstants.PARAM_NAME_LOCALIZATION_MODE_HANDRAIL,
        "perch": CommandConstants.PARAM_NAME_LOCALIZATION_MODE_HANDRAIL,
        "truth": CommandConstants.PARAM_NAME_LOCALIZATION_MODE_TRUTH,
        "none": CommandConstants.PARAM_NAME_LOCALIZATION_MODE_NONE,
    }

    GRIPPER_CHOICES = {"open": True, "close": False}

    ENABLE_CHOICES = {"on": True, "off": False}

    CAMERA_MODES = {
        "both": CommandConstants.PARAM_NAME_CAMERA_MODE_BOTH,
        "record": CommandConstants.PARAM_NAME_CAMERA_MODE_RECORDING,
        "stream": CommandConstants.PARAM_NAME_CAMERA_MODE_STREAMING,
    }

    CAMERA_NAMES = {
        "sci": CommandConstants.PARAM_NAME_CAMERA_NAME_SCI,
        "nav": CommandConstants.PARAM_NAME_CAMERA_NAME_NAV,
        "haz": CommandConstants.PARAM_NAME_CAMERA_NAME_HAZ,
        "dock": CommandConstants.PARAM_NAME_CAMERA_NAME_DOCK,
        "perch": CommandConstants.PARAM_NAME_CAMERA_NAME_PERCH,
    }

    CAMERA_RESOLUTIONS = [
        "224x171",
        "320x240",
        "480x270",
        "640x480",
        "960x540",
        "1024x768",
        "1280x720",
        "1280x960",
        "1920x1080",
    ]

    PLANNERS = {
        "trapezoidal": CommandConstants.PARAM_NAME_PLANNER_TYPE_TRAPEZOIDAL,
        "qp": CommandConstants.PARAM_NAME_PLANNER_TYPE_QUADRATIC_PROGRAM,
    }

    FLIGHT_MODES = {
        "off": CommandConstants.PARAM_NAME_FLIGHT_MODE_OFF,
        "quiet": CommandConstants.PARAM_NAME_FLIGHT_MODE_QUIET,
        "nominal": CommandConstants.PARAM_NAME_FLIGHT_MODE_NOMINAL,
        "difficult": CommandConstants.PARAM_NAME_FLIGHT_MODE_DIFFICULT,
        "precision": CommandConstants.PARAM_NAME_FLIGHT_MODE_PRECISION,
    }

    TELEMETRY_TIPES = [
        CommandConstants.PARAM_NAME_TELEMETRY_TYPE_COMM_STATUS,
        CommandConstants.PARAM_NAME_TELEMETRY_TYPE_CPU_STATE,
        CommandConstants.PARAM_NAME_TELEMETRY_TYPE_DISK_STATE,
        CommandConstants.PARAM_NAME_TELEMETRY_TYPE_EKF_STATE,
        CommandConstants.PARAM_NAME_TELEMETRY_TYPE_GNC_STATE,
        CommandConstants.PARAM_NAME_TELEMETRY_TYPE_PMC_CMD_STATE,
        CommandConstants.PARAM_NAME_TELEMETRY_TYPE_POSITION,
        CommandConstants.PARAM_NAME_TELEMETRY_TYPE_SPARSE_MAPPING_POSE,
    ]

    CF_TYPE_PLAN = "plan"
    CF_TYPE_RECORD = "record"
    CF_TYPE_ZONES = "zones"

    def __init__(self, node):
        self.node = node
        self.sent_cmds = {}
        self.feedback_cmds = Queue()
        self.last_cmd_id = None
        self.last_cf_id = None
        self.last_cf_type = None
        self.base_id = "LocalParticipant"
        self.cmd_count = 0
        self.op_limits = {}
        self._start_subscribers()
        self._start_publishers()
        self._load_operating_limits()

    def _start_publishers(self):
        self.node.add_publisher("cmd_pub", "/command", CommandStamped)
        self.node.add_publisher("plan_pub", "/comm/dds/plan", CompressedFile)
        self.node.add_publisher("data_pub", "/comm/dds/data", CompressedFile)
        self.node.add_publisher("zones_pub", "/comm/dds/zones", CompressedFile)

    def _start_subscribers(self):
        self.node.add_subscriber("ack", "/mgt/ack", self.ack_callback, AckStamped)
        self.node.add_subscriber(
            "cf_ack", "/mgt/executive/cf_ack", self.cfack_callback, CompressedFileAck
        )

    def _load_operating_limits(self):
        try:
            f = open(os.path.join(filepath, "../config/AllOperatingLimitsConfig.json"))
            self.op_limits = json.loads(f.read())
        except (OSError, json.JSONDecodeError):
            self.op_limits = {}

    """ Commanding helpers """

    def send_command(self, name, subsys="", args=[]):
        cmd = CommandStamped()
        # Build header
        cmd.header = Header()
        cmd.header.stamp = Time.now()
        cmd.header.frame_id = "world"
        # This makes the command work:
        cmd.cmd_name = name
        cmd.args = args

        # Create a unique ID
        self.last_cmd_id = str(self.cmd_count) + self.base_id + str(get_rostime().secs)
        cmd.cmd_id = self.last_cmd_id

        # Extra info to better identify the source of the command
        # cmd.cmd_src = user
        cmd.cmd_origin = "ground"
        cmd.subsys_name = subsys

        # Save command and publish
        self.cmd_count += 1
        saved_cmd = Command(cmd.cmd_id, self.cmd_count, name)
        self.sent_cmds[cmd.cmd_id] = saved_cmd
        self.node.get_publisher("cmd_pub").publish(cmd)

    def send_cf(self, file_data, type):
        header = Header(stamp=Time.now())
        cmd = CompressedFile(
            header=header, id=header.stamp.secs, type=0, file=file_data
        )
        self.last_cf_id = cmd.id
        self.last_cf_type = type
        if type == CommandHandler.CF_TYPE_PLAN:
            self.node.get_publisher("plan_pub").publish(cmd)
        elif type == CommandHandler.CF_TYPE_RECORD:
            self.node.get_publisher("data_pub").publish(cmd)
        elif type == CommandHandler.CF_TYPE_ZONES:
            self.node.get_publisher("zones_pub").publish(cmd)
        else:
            return False
        return True

    """ Callbacks """

    def ack_callback(self, data):
        if data.cmd_id in self.sent_cmds.keys():
            cmd_fback = CommandFeedback()
            cmd_fback.id = data.cmd_id
            cmd_fback.status = data.status.status
            cmd_fback.completed_status = data.completed_status.status
            cmd_fback.message = data.message
            self.feedback_cmds.enqueue(cmd_fback)

    def cfack_callback(self, data):
        # Published file was received, send setData/setPlan command
        if data.id == self.last_cf_id:
            if self.last_cf_type == CommandHandler.CF_TYPE_RECORD:
                self.send_command(CommandConstants.CMD_NAME_SET_DATA_TO_DISK, "Data")
            elif self.last_cf_type == CommandHandler.CF_TYPE_PLAN:
                self.send_command(CommandConstants.CMD_NAME_SET_PLAN, "Plan")
            elif self.last_cf_type == CommandHandler.CF_TYPE_ZONES:
                self.send_command(CommandConstants.CMD_NAME_SET_ZONES, "Settings")

    """ Admin commands """

    def action_init_bias(self, args):
        self.send_command(CommandConstants.CMD_NAME_INITIALIZE_BIAS, "Admin")
        return True

    def action_ekf(self, args):
        if args.reset:
            self.send_command(CommandConstants.CMD_NAME_RESET_EKF, "Admin")
        else:
            return False
        return True

    def action_loc(self, args):
        if args.reset:
            self.send_command(CommandConstants.CMD_NAME_REACQUIRE_POSITION, "Admin")
        elif args.set:
            pipeline = CommandHandler.LOC_CHOICES.get(args.set, None)
            if pipeline is not None:
                arg = CommandArg()
                arg.data_type = 5
                arg.s = pipeline
                self.send_command(
                    CommandConstants.CMD_NAME_SWITCH_LOCALIZATION, "Admin", [arg]
                )
        else:
            return False
        return True

    def action_unterminate(self, args):
        self.send_command(CommandConstants.CMD_NAME_UNTERMINATE, "Admin")
        return True

    """ Settings commands """

    def action_telemetry(self, args):
        if args.set:
            options = [
                args.comm,
                args.cpu,
                args.disk,
                args.ekf,
                args.gnc,
                args.pmc,
                args.position,
                args.sparse_map_pose,
            ]
            for i, opt in enumerate(options):
                if opt != None:
                    self.send_command(
                        CommandConstants.CMD_NAME_SET_TELEMETRY_RATE,
                        "Settings",
                        [
                            CommandArg(
                                data_type=CommandArg.DATA_TYPE_STRING,
                                s=CommandHandler.TELEMETRY_TIPES[i],
                            ),
                            CommandArg(data_type=CommandArg.DATA_TYPE_FLOAT, f=opt),
                        ],
                    )
        else:
            return False
        return True

    def action_obstacles(self, args):
        if args.enable is not None:
            self.send_command(
                CommandConstants.CMD_NAME_SET_CHECK_OBSTACLES,
                "Settings",
                [CommandArg(data_type=0, b=args.enable)],
            )
        else:
            return False
        return True

    def action_zones(self, args):
        if args.enable is not None:
            self.send_command(
                CommandConstants.CMD_NAME_SET_CHECK_ZONES,
                "Settings",
                [CommandArg(data_type=0, b=args.enable)],
            )
        elif args.set is not None:
            # TODO Check how to publish the zones
            self._publish_files(args.set, CommandHandler.CF_TYPE_ZONES)
            # SetZones will be sent in cfack_callback
        else:
            return False
        return True

    def action_limits(self, args):
        if args.set is not None:
            self.send_command(
                CommandConstants.CMD_NAME_SET_OPERATING_LIMITS,
                "Settings",
                [
                    CommandArg(data_type=CommandArg.DATA_TYPE_STRING, s=args.set[0]),
                    CommandArg(data_type=CommandArg.DATA_TYPE_STRING, s=args.set[1]),
                    CommandArg(data_type=CommandArg.DATA_TYPE_FLOAT, f=args.set[2]),
                    CommandArg(data_type=CommandArg.DATA_TYPE_FLOAT, f=args.set[3]),
                    CommandArg(data_type=CommandArg.DATA_TYPE_FLOAT, f=args.set[4]),
                    CommandArg(data_type=CommandArg.DATA_TYPE_FLOAT, f=args.set[5]),
                    CommandArg(data_type=CommandArg.DATA_TYPE_FLOAT, f=args.set[6]),
                ],
            )
        elif args.config:
            try:
                for p in self.op_limits["operatingLimitsConfigs"]:
                    if p["profileName"] != args.config:
                        continue

                    self.send_command(
                        CommandConstants.CMD_NAME_SET_OPERATING_LIMITS,
                        "Settings",
                        [
                            CommandArg(
                                data_type=CommandArg.DATA_TYPE_STRING,
                                s=p["profileName"],
                            ),
                            CommandArg(
                                data_type=CommandArg.DATA_TYPE_STRING, s=p["flightMode"]
                            ),
                            CommandArg(
                                data_type=CommandArg.DATA_TYPE_FLOAT,
                                f=p["targetLinearVelocity"],
                            ),
                            CommandArg(
                                data_type=CommandArg.DATA_TYPE_FLOAT,
                                f=p["targetLinearAccel"],
                            ),
                            CommandArg(
                                data_type=CommandArg.DATA_TYPE_FLOAT,
                                f=p["targetAngularVelocity"],
                            ),
                            CommandArg(
                                data_type=CommandArg.DATA_TYPE_FLOAT,
                                f=p["targetAngularAccel"],
                            ),
                            CommandArg(
                                data_type=CommandArg.DATA_TYPE_FLOAT,
                                f=p["collisionDistance"],
                            ),
                        ],
                    )
            except KeyError:
                # No profiles found, or wrong format
                return False
        else:
            return False
        return True

    def action_ff(self, args):
        if args.enable is not None:
            self.send_command(
                CommandConstants.CMD_NAME_SET_HOLONOMIC_MODE,
                "Settings",
                [CommandArg(data_type=0, b=not args.enable)],
            )
        else:
            return False
        return True

    def action_camera(self, args):
        cameras = {
            "nav": args.nav,
            "dock": args.dock,
            "sci": args.sci,
            "haz": args.haz,
            "perch": args.perch,
        }
        if args.record:
            for name, cam in cameras.items():
                self._enable_camera(
                    CommandConstants.CMD_NAME_SET_CAMERA_RECORDING, name, cam
                )
        elif args.stream:
            for name, cam in cameras.items():
                self._enable_camera(
                    CommandConstants.CMD_NAME_SET_CAMERA_STREAMING, name, cam
                )
        elif args.config:
            for name, cam in cameras.items():
                if cam is not False:
                    cam_name = CommandHandler.CAMERA_NAMES.get(name)
                    mode = CommandHandler.CAMERA_MODES.get(cam[0])
                    self.send_command(
                        CommandConstants.CMD_NAME_SET_CAMERA,
                        "Settings",
                        [
                            CommandArg(
                                data_type=CommandArg.DATA_TYPE_STRING, s=cam_name
                            ),
                            CommandArg(data_type=CommandArg.DATA_TYPE_STRING, s=mode),
                            CommandArg(data_type=CommandArg.DATA_TYPE_STRING, s=cam[1]),
                            CommandArg(data_type=CommandArg.DATA_TYPE_FLOAT, f=cam[2]),
                            CommandArg(data_type=CommandArg.DATA_TYPE_FLOAT, f=cam[3]),
                        ],
                    )
        else:
            return False
        return True

    def action_planner(self, args):
        if args.set != None:
            planner = CommandHandler.PLANNERS.get(args.set)
            self.send_command(
                CommandConstants.CMD_NAME_SET_PLANNER,
                "Settings",
                [CommandArg(data_type=CommandArg.DATA_TYPE_STRING, s=planner)],
            )
        else:
            return False
        return True

    def action_enable_intercomms(self, args):
        self.send_command(
            CommandConstants.CMD_NAME_ENABLE_ASTROBEE_INTERCOMMS, "Settings"
        )
        return True

    """ Bagger commands """

    def action_bagger(self, args):
        if args.config is not None:
            self._publish_file(args.config, CommandHandler.CF_TYPE_RECORD)
            # SetDataToDisk will be sent in cfack_callback
        elif args.start is not False:
            self.send_command(
                CommandConstants.CMD_NAME_START_RECORDING,
                "Data",
                [CommandArg(data_type=5, s=args.start)],
            )
        elif args.stop:
            self.send_command(CommandConstants.CMD_NAME_STOP_RECORDING, "Data")
        else:
            return False
        return True

    """ Mobility commands """

    def action_dock(self, args):
        if args.berth is not None:
            self.send_command(
                CommandConstants.CMD_NAME_DOCK,
                "Mobility",
                [CommandArg(data_type=CommandArg.DATA_TYPE_INT, i=args.berth)],
            )
        else:
            return False
        return True

    def action_undock(self, args):
        if args.undock:
            self.send_command(CommandConstants.CMD_NAME_UNDOCK, "Mobility")
        else:
            return False
        return True

    def action_idle(self, args):
        if args.idle:
            self.send_command(CommandConstants.CMD_NAME_IDLE_PROPULSION, "Mobility")
        else:
            return False
        return True

    def action_stop(self, args):
        if args.stop:
            self.send_command(CommandConstants.CMD_NAME_STOP_ALL_MOTION, "Mobility")
        else:
            return False
        return True

    def action_move(self, args):
        def resolve_pose(args, pos, q):
            if args.pos is not None:
                pos = [float(x) for x in args.pos]
            if args.att is not None:
                att = [float(math.radians(x)) for x in args.att]
                q = quaternion_from_euler(att[0], att[1], att[2])
            return (pos, q)

        if args.relative:
            pos, q = resolve_pose(args, [0, 0, 0], [0, 0, 0, 1])
            frame_str = "body"
        else:
            pose = self.node.telh.ekf_state.pose
            pos = [pose.position.x, pose.position.y, pose.position.z]
            q = [
                pose.orientation.x,
                pose.orientation.y,
                pose.orientation.z,
                pose.orientation.w,
            ]
            pos, q = resolve_pose(args, pos, q)
            frame_str = "ISS"

        # Build arguments
        frame = CommandArg(data_type=CommandArg.DATA_TYPE_STRING, s=frame_str)
        position = CommandArg(
            data_type=CommandArg.DATA_TYPE_VEC3d, vec3d=[pos[0], pos[1], pos[2]]
        )
        extra = CommandArg(data_type=CommandArg.DATA_TYPE_VEC3d, vec3d=[0.0, 0.0, 0.0])
        orientation = CommandArg(
            data_type=CommandArg.DATA_TYPE_MAT33f,
            mat33f=[q[0], q[1], q[2], q[3], 0.0, 0.0, 0.0, 0.0, 0.0],
        )
        # Send command
        self.send_command(
            CommandConstants.CMD_NAME_SIMPLE_MOVE6DOF,
            "Mobility",
            [frame, position, extra, orientation],
        )

    """ Arm commands """

    def action_arm(self, args):
        do_pan = args.pan != None
        do_tilt = args.tilt != None
        if args.stow:
            self.send_command(CommandConstants.CMD_NAME_STOW_ARM, "Arm")
        elif args.deploy:
            self.send_command(
                CommandConstants.CMD_NAME_ARM_PAN_AND_TILT,
                "Arm",
                [
                    CommandArg(data_type=CommandArg.DATA_TYPE_FLOAT, f=0.0),
                    CommandArg(data_type=CommandArg.DATA_TYPE_FLOAT, f=0.0),
                    CommandArg(
                        data_type=CommandArg.DATA_TYPE_STRING,
                        s=CommandConstants.PARAM_NAME_ACTION_TYPE_BOTH,
                    ),
                ],
            )
        elif args.stop:
            self.send_command(CommandConstants.CMD_NAME_STOP_ARM, "Arm")
        elif args.gripper is not None:
            self.send_command(
                CommandConstants.CMD_NAME_GRIPPER_CONTROL,
                "Arm",
                [
                    CommandArg(
                        data_type=CommandArg.DATA_TYPE_BOOL,
                        b=CommandHandler.GRIPPER_CHOICES.get(args.gripper, None),
                    )
                ],
            )
        elif do_pan or do_tilt:
            pan = CommandArg(data_type=CommandArg.DATA_TYPE_FLOAT, f=0.0)
            tilt = CommandArg(data_type=CommandArg.DATA_TYPE_FLOAT, f=0.0)
            action = CommandArg(data_type=CommandArg.DATA_TYPE_STRING)

            if do_pan:
                action.s = CommandConstants.PARAM_NAME_ACTION_TYPE_PAN
                pan.f = args.pan

            if do_tilt:
                action.s = CommandConstants.PARAM_NAME_ACTION_TYPE_TILT
                tilt.f = args.tilt

            if do_pan and do_tilt:
                action.s = CommandConstants.PARAM_NAME_ACTION_TYPE_BOTH

            self.send_command(
                CommandConstants.CMD_NAME_ARM_PAN_AND_TILT, "Arm", [pan, tilt, action]
            )
        else:
            return False
        return True

    def action_perch(self, args):
        if args.perch:
            self.send_command(CommandConstants.CMD_NAME_PERCH, "Mobility")
        else:
            return False
        return True

    def action_unperch(self, args):
        if args.unperch:
            self.send_command(CommandConstants.CMD_NAME_UNPERCH, "Mobility")
        else:
            return False
        return True

    """ Hardware commands """

    def action_light(self, args):
        if args.set:
            if args.front is not None:
                self.send_command(
                    CommandConstants.CMD_NAME_SET_FLASHLIGHT_BRIGHTNESS,
                    "Hardware",
                    [
                        CommandArg(
                            data_type=CommandArg.DATA_TYPE_STRING,
                            s=CommandConstants.PARAM_NAME_FLASHLIGHT_LOCATION_FRONT,
                        ),
                        CommandArg(
                            data_type=CommandArg.DATA_TYPE_FLOAT, f=args.front / 100.0
                        ),
                    ],
                )
            if args.back is not None:
                self.send_command(
                    CommandConstants.CMD_NAME_SET_FLASHLIGHT_BRIGHTNESS,
                    "Hardware",
                    [
                        CommandArg(
                            data_type=CommandArg.DATA_TYPE_STRING,
                            s=CommandConstants.PARAM_NAME_FLASHLIGHT_LOCATION_BACK,
                        ),
                        CommandArg(
                            data_type=CommandArg.DATA_TYPE_FLOAT, f=args.back / 100.0
                        ),
                    ],
                )
        else:
            return False
        return True

    def action_power(self, args):
        if args.set:
            options = [
                args.laser,
                args.pmc_signals,
                args.pay_ta,
                args.pay_ba,
                args.pay_bf,
            ]
            commands = [
                CommandConstants.PARAM_NAME_POWERED_COMPONENT_LASER_POINTER,
                CommandConstants.PARAM_NAME_POWERED_COMPONENT_PMCS_AND_SIGNAL_LIGHTS,
                CommandConstants.PARAM_NAME_POWERED_COMPONENT_PAYLOAD_TOP_AFT,
                CommandConstants.PARAM_NAME_POWERED_COMPONENT_PAYLOAD_BOTTOM_AFT,
                CommandConstants.PARAM_NAME_POWERED_COMPONENT_PAYLOAD_BOTTOM_FRONT,
            ]
            for i, opt in enumerate(options):
                if opt:
                    self.send_command(
                        self._choose_power_onoff(opt, "on"),
                        "Hardware",
                        [
                            CommandArg(
                                data_type=CommandArg.DATA_TYPE_STRING, s=commands[i]
                            )
                        ],
                    )
        else:
            return False
        return True

    def action_laser(self, args):
        self.send_command(
            self._choose_power_onoff(args.request, "on"),
            "Hardware",
            [
                CommandArg(
                    data_type=CommandArg.DATA_TYPE_STRING,
                    s=CommandConstants.PARAM_NAME_POWERED_COMPONENT_LASER_POINTER,
                )
            ],
        )

    """ Plan commands """

    def action_plan(self, args):
        if args.pause:
            self.send_command(CommandConstants.CMD_NAME_PAUSE_PLAN, "Plan")
        elif args.skip:
            self.send_command(CommandConstants.CMD_NAME_SKIP_PLAN_STEP, "Plan")
        elif args.load is not None:
            self._publish_file(args.load, CommandHandler.CF_TYPE_PLAN)
            # SetDataToDisk will be sent in cfack_callback
        elif args.run:
            self.send_command(CommandConstants.CMD_NAME_RUN_PLAN, "Plan")
        else:
            return False
        return True

    """ Guest Science Commands """

    def action_gs(self, args):
        if args.start != None:
            full_name = self._get_apk_name(args.start, args.start)
            self.send_command(
                CommandConstants.CMD_NAME_START_GUEST_SCIENCE,
                "GuestScience",
                [CommandArg(data_type=CommandArg.DATA_TYPE_STRING, s=full_name)],
            )
        elif args.stop != None:
            full_name = self._get_apk_name(args.stop, args.stop)
            self.send_command(
                CommandConstants.CMD_NAME_STOP_GUEST_SCIENCE,
                "GuestScience",
                [CommandArg(data_type=CommandArg.DATA_TYPE_STRING, s=full_name)],
            )
        elif args.command != None:
            full_name = self._get_apk_name(args.command[0], args.command[0])
            full_cmd = self._get_apk_command(
                args.command[0], args.command[1], args.command[1]
            )
            self.send_command(
                CommandConstants.CMD_NAME_CUSTOM_GUEST_SCIENCE,
                "GuestScience",
                [
                    CommandArg(data_type=CommandArg.DATA_TYPE_STRING, s=full_name),
                    CommandArg(data_type=CommandArg.DATA_TYPE_STRING, s=full_cmd),
                ],
            )
        else:
            return False
        return True

    def _get_apk_name(self, short_name, default):
        apks = self.node.telh.gs_config.apks
        for apk in apks:
            if apk.short_name == short_name:
                return apk.apk_name
        return default

    def _get_apk_short_name(self, apk_name, default):
        apks = self.node.telh.gs_config.apks
        for apk in apks:
            if apk.apk_name == apk_name:
                return apk.short_name
        return default

    def _get_apk_command(self, apk_short_name, cmd_name, default_cmd):
        apks = self.node.telh.gs_config.apks
        for apk in apks:
            if apk.short_name == apk_short_name:
                for cmd in apk.commands:
                    if cmd.name == cmd_name:
                        return cmd.command
        return default_cmd

    """ Load/Unload nodelet """

    def action_load(self, args):
        self.send_command(
            CommandConstants.CMD_NAME_LOAD_NODELET,
            "Admin",
            [CommandArg(data_type=CommandArg.DATA_TYPE_STRING, s=args.nodelet_name)],
        )

    def action_unload(self, args):
        self.send_command(
            CommandConstants.CMD_NAME_UNLOAD_NODELET,
            "Admin",
            [CommandArg(data_type=CommandArg.DATA_TYPE_STRING, s=args.nodelet_name)],
        )

    """ Helper functions """

    def _enable_camera(self, cmd_name, name, cam):
        if cam is not False:
            enable = CommandHandler.ENABLE_CHOICES.get(cam[0])
            cam_name = CommandHandler.CAMERA_NAMES.get(name)
            self.send_command(
                cmd_name,
                "Settings",
                [
                    CommandArg(data_type=CommandArg.DATA_TYPE_STRING, s=cam_name),
                    CommandArg(data_type=CommandArg.DATA_TYPE_BOOL, b=enable),
                ],
            )

    def _choose_power_onoff(self, argument, on_value):
        enable = (
            CommandConstants.CMD_NAME_POWER_ON_ITEM
            if argument == on_value
            else CommandConstants.CMD_NAME_POWER_OFF_ITEM
        )
        return enable

    def _publish_file(self, file, type):
        file_data = [ord(c) for c in file.read()]
        return self.send_cf(file_data, type)

    def _publish_files(self, files, type):
        for f in files:
            self._publish_file(f, type)
