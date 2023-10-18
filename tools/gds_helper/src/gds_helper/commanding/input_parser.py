#!/usr/bin/env python
import json
import os
import re
import shlex
import sys
from argparse import Action, ArgumentParser, ArgumentTypeError, FileType

# from command_handler import CommandHandler
from commanding.command_handler import CommandHandler
from util.argparse_redirect import ArgumentParserRedirect
from util.utils import str_to_float

## Change to gds_helper root dir
# os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/..")
## Add common scripts dir to path and import stuff
# sys.path.append(os.path.join(os.getcwd(), "../common"))
# from argparse_redirect import ArgumentParserRedirect
# from utils import str_to_float


class InputParser(ArgumentParserRedirect):
    LAYOUT_OPTIONS = ["ack", "menu", "tel", "data"]

    def __init__(self, handler_function, description):
        ArgumentParserRedirect.__init__(self, description)
        self.handler_fun = handler_function
        self.op_limits = []
        self._load_operating_limits_names()

    def _load_operating_limits_names(self):
        try:
            f = open("AllOperatingLimitsConfig.json")
            data = json.loads(f.read())
            for profile in data["operatingLimitsConfigs"]:
                self.op_limits.append(profile["profileName"])
        except (OSError, KeyError):
            self.op_limits = []

    def build_parser(self, curses_interface=False):
        # Python 3 requires we set required=True, that is not the case for Python2
        if sys.version_info > (3, 0):
            subparsers = self.add_subparsers(
                help="Available actions",
                dest="subparser_name",
                parser_class=ArgumentParser,
                required=True,
            )
        else:
            subparsers = self.add_subparsers(
                help="Available actions",
                dest="subparser_name",
                parser_class=ArgumentParser,
            )

        # Action bias
        parser_bias = subparsers.add_parser("init_bias", help="Reset the bias")
        parser_bias.set_defaults(reset_bias=True, func=self.handler_fun)

        # Action EKF
        parser_ekf = subparsers.add_parser(
            "ekf", help="Read or reset the pose estimation"
        )
        parser_ekf.set_defaults(func=self.handler_fun)
        group_ekf = parser_ekf.add_mutually_exclusive_group(required=True)
        group_ekf.add_argument("-reset", default=False, action="store_true")
        group_ekf.add_argument("-get", default=False, action="store_true")

        # Action localization
        parser_loc = subparsers.add_parser(
            "loc", help="Reset localization and control pipelines"
        )
        parser_loc.set_defaults(func=self.handler_fun)
        group_loc = parser_loc.add_mutually_exclusive_group(required=True)
        group_loc.add_argument("-reset", default=False, action="store_true")
        group_loc.add_argument("-get", default=False, action="store_true")
        group_loc.add_argument(
            "-set", default=False, choices=CommandHandler.LOC_CHOICES.keys()
        )

        # Action unterminate
        parser_unter = subparsers.add_parser(
            "unterminate", help="Clear terminated state"
        )
        parser_unter.set_defaults(unterminate=True, func=self.handler_fun)

        # Action telemetry
        p_tel, g_tel = self._add_action_exclusive_group(
            subparsers, "telemetry", self.handler_fun, "Set/Get Astrobee telemetry"
        )
        g_tel.add_argument("-get", default=False, action="store_true")
        g_tel.add_argument("-set", default=False, action="store_true")
        p_tel.add_argument("-comm", default=None, const=-1, nargs="?", type=float)
        p_tel.add_argument("-cpu", default=None, const=-1, nargs="?", type=float)
        p_tel.add_argument("-disk", default=None, const=-1, nargs="?", type=float)
        p_tel.add_argument("-gnc", default=None, const=-1, nargs="?", type=float)
        p_tel.add_argument("-ekf", default=None, const=-1, nargs="?", type=float)
        p_tel.add_argument("-pmc", default=None, const=-1, nargs="?", type=float)
        p_tel.add_argument("-position", default=None, const=-1, nargs="?", type=float)
        p_tel.add_argument(
            "-sparse_map_pose", default=None, const=-1, nargs="?", type=float
        )

        # Action check obstacles
        parser_obstacles = subparsers.add_parser(
            "obstacles", help="Enable/disable/query check obstacles"
        )
        parser_obstacles.set_defaults(func=self.handler_fun)
        g_obstacles = parser_obstacles.add_mutually_exclusive_group(required=True)

        # Action zones
        parser_zones = subparsers.add_parser(
            "zones", help="Enable/disable/query check zones"
        )
        parser_zones.set_defaults(func=self.handler_fun)
        g_zones = parser_zones.add_mutually_exclusive_group(required=True)
        g_zones.add_argument("-set", default=None, nargs="+", type=FileType("r"))

        # Action Face Forward
        parser_ff = subparsers.add_parser("ff", help="Enable/disable/query check ff")
        parser_ff.set_defaults(func=self.handler_fun)
        g_ff = parser_ff.add_mutually_exclusive_group(required=True)

        # Common arguments for obstacles, zones and ff
        for g in [g_obstacles, g_zones, g_ff]:
            g.add_argument("-get", default=False, action="store_true")
            g.add_argument("-enable", "-e", default=None, type=int, choices=[0, 1])

        # Action dock
        p_dock, g_dock = self._add_action_exclusive_group(
            subparsers, "dock", self.handler_fun, "Attempt to dock Astrobee"
        )
        g_dock.add_argument(
            "-berth", "-b", default=None, action="store", choices=[1, 2], type=int
        )
        # TODO
        g_dock.add_argument("-get", default=False, action="store_true")

        # Action undock
        p_undock = subparsers.add_parser(
            "undock", help="Undocks Astrobee and moves to approach point"
        )
        p_undock.set_defaults(undock=True, func=self.handler_fun)

        # Action IDLE
        p_idle = subparsers.add_parser("idle", help="IDLE Astrobee propulsion")
        p_idle.set_defaults(idle=True, func=self.handler_fun)

        # Action stop
        p_stop = subparsers.add_parser("stop", help="Stop all motion")
        p_stop.set_defaults(stop=True, func=self.handler_fun)

        # Action move
        p_move = subparsers.add_parser("move")
        p_move.set_defaults(func=self.handler_fun)
        p_move.add_argument("-pos", "-p", default=None, nargs=3, type=float)
        p_move.add_argument("-att", "-a", default=None, nargs=3, type=float)
        p_move.add_argument("-relative", "-r", default=False, action="store_true")

        # Action arm
        p_arm, g_arm = self._add_action_exclusive_group(
            subparsers,
            "arm",
            self.handler_fun,
            "Control and get state of Astrobee arm",
            False,
        )
        g_arm_move = p_arm.add_argument_group()
        g_arm_move.add_argument("-tilt", "-t", default=None, type=float)
        g_arm_move.add_argument("-pan", "-p", default=None, type=float)
        g_arm.add_argument("-deploy", default=False, action="store_true")
        g_arm.add_argument("-stop", default=False, action="store_true")
        g_arm.add_argument(
            "-gripper", default=None, choices=CommandHandler.GRIPPER_CHOICES.keys()
        )
        g_arm.add_argument("-get", default=False, action="store_true")
        g_arm.add_argument("-stow", default=False, action="store_true")

        # Action bagger
        parser_bagger = subparsers.add_parser(
            "bagger", help="Control the ROS bag recorder"
        )
        parser_bagger.set_defaults(func=self.handler_fun)
        group_bagger = parser_bagger.add_mutually_exclusive_group(required=True)
        group_bagger.add_argument("-get", default=False, action="store_true")
        group_bagger.add_argument("-list", default=False, action="store_true")
        group_bagger.add_argument("-config", default=None, type=FileType("r"))
        group_bagger.add_argument("-start", nargs="?", const="", default=False)
        group_bagger.add_argument("-stop", default=False, action="store_true")

        # Actions perch/unperch
        p_perch = subparsers.add_parser("perch", help="Attempt to perch to a handrail")
        p_perch.set_defaults(perch=True, func=self.handler_fun)

        p_unperch = subparsers.add_parser(
            "unperch", help="Attempt to unperch from a handrail"
        )
        p_unperch.set_defaults(unperch=True, func=self.handler_fun)

        # Action light
        p_light, g_light = self._add_action_exclusive_group(
            subparsers, "light", self.handler_fun, "Control Astrobee flashlights"
        )
        g_light.add_argument("-get", default=False, action="store_true")
        g_light.add_argument("-set", default=False, action="store_true")
        p_light.add_argument(
            "-front", "-f", default=None, const=-1.0, nargs="?", type=int
        )
        p_light.add_argument(
            "-back", "-b", default=None, const=-1.0, nargs="?", type=int
        )

        # Action power
        p_power, g_power = self._add_action_exclusive_group(
            subparsers, "power", self.handler_fun, "Enable power to Astrobee components"
        )
        g_power.add_argument("-get", default=False, action="store_true")
        g_power.add_argument("-set", default=False, action="store_true")
        p_power.add_argument("-laser", default=False, const="info", nargs="?")
        p_power.add_argument("-pmc_signals", default=False, const="info", nargs="?")
        p_power.add_argument("-pay_ta", "-ta", default=False, const="info", nargs="?")
        p_power.add_argument("-pay_ba", "-ba", default=False, const="info", nargs="?")
        p_power.add_argument("-pay_bf", "-bf", default=False, const="info", nargs="?")

        # Action laser
        p_laser = subparsers.add_parser("laser")
        p_laser.set_defaults(func=self.handler_fun)
        p_laser.add_argument("request", choices=["on", "off"])

        # Action plan
        p_plan, g_plan = self._add_action_exclusive_group(
            subparsers, "plan", self.handler_fun, "Load and run Astrobee plan files"
        )
        g_plan.add_argument("-get", default=False, action="store_true")
        g_plan.add_argument("-load", default=None, type=FileType("r"))
        g_plan.add_argument("-run", "-r", default=False, action="store_true")
        g_plan.add_argument("-pause", "-p", default=False, action="store_true")
        g_plan.add_argument("-skip", "-s", default=False, action="store_true")

        # Action cameras
        p_cam, g_cam = self._add_action_exclusive_group(
            subparsers,
            "camera",
            self.handler_fun,
            "Enable/configure cameras for streaming and recording",
        )
        g_cam.add_argument("-get", default=False, action="store_true")
        g_cam.add_argument("-record", default=False, action="store_true")
        g_cam.add_argument("-stream", default=False, action="store_true")
        g_cam.add_argument("-config", default=False, action="store_true")
        p_cam.add_argument(
            "-nav", default=False, nargs="*"
        )  # stream|record|both resolution rate bitrate
        p_cam.add_argument("-dock", default=False, nargs="*")
        p_cam.add_argument("-sci", default=False, nargs="*")
        p_cam.add_argument("-haz", default=False, nargs="*")
        p_cam.add_argument("-perch", default=False, nargs="*")

        # Action planners
        p_planner, g_planner = self._add_action_exclusive_group(
            subparsers, "planner", self.handler_fun, "Query/Switch motion planners"
        )
        g_planner.add_argument("-get", default=False, action="store_true")
        g_planner.add_argument(
            "-set", default=None, choices=CommandHandler.PLANNERS.keys()
        )

        # Action limits
        p_limits, g_limits = self._add_action_exclusive_group(
            subparsers, "limits", self.handler_fun, "Query/Set operating limits"
        )
        g_limits.add_argument("-get", default=False, action="store_true")
        # profile_name, flight_mode, vel, accel, avel, aaccel, collision_distance
        g_limits.add_argument(
            "-set",
            default=None,
            nargs=7,
            metavar=(
                "PROFILE_NAME",
                "FLIGHT_MODE",
                "LIN_VEL",
                "LIN_ACCEL",
                "ANG_VEL",
                "ANG_ACCEL",
                "COLL_DST",
            ),
        )
        g_limits.add_argument("-config", default=None, choices=self.op_limits)

        # Action Guest Science
        p_gs, g_gs = self._add_action_exclusive_group(
            subparsers,
            "gs",
            self.handler_fun,
            "Control Guest Science Android applications",
        )
        g_gs.add_argument("-start", default=None, metavar="APK_NAME")
        g_gs.add_argument("-stop", default=None, metavar="APK_NAME")
        g_gs.add_argument(
            "-command",
            "-cmd",
            default=None,
            nargs=2,
            metavar=("APK_SHORT_NAME/FULL_NAME", "CMD_NAME/CMD_SYNTAX"),
        )
        g_gs.add_argument("-get", default=None, metavar="APK_NAME")
        g_gs.add_argument("-list", "-l", default=False, action="store_true")

        p_shell = subparsers.add_parser("shell", help="Execute shell commands")
        p_shell.set_defaults(func=self.handler_fun)
        p_shell.add_argument("command", nargs="+")

        # Action load nodelet
        p_load = subparsers.add_parser("load")
        p_load.set_defaults(func=self.handler_fun)
        p_load.add_argument("nodelet_name")

        # Action unload nodelet
        p_unload = subparsers.add_parser("unload")
        p_unload.set_defaults(func=self.handler_fun)
        p_unload.add_argument("nodelet_name")

        # Action enable astrobee intercomms
        p_intercomms = subparsers.add_parser("enable_intercomms")
        p_intercomms.set_defaults(func=self.handler_fun)

        # Action function. These are built-in functions
        p_function = subparsers.add_parser("function")
        p_function.set_defaults(func=self.handler_fun)
        sp_function = p_function.add_subparsers(
            help="Available functions",
            dest="function_name",
            parser_class=ArgumentParser,
        )

        p_assert_ml = sp_function.add_parser("assert_ml_count")
        p_assert_ml.add_argument("-timeout", type=int, default=1)
        p_assert_ml.add_argument("-min_positives", type=int, default=1)

        p_assert_pose = sp_function.add_parser("assert_pose")
        p_assert_pose.add_argument("-docked", default=False, action="store_true")

        p_assert_ml_pipeline = sp_function.add_parser("assert_ml_pipeline")

        p_assert_docked_state = sp_function.add_parser("assert_docked_state")

        p_assert_nf = sp_function.add_parser("assert_no_faults")

        p_get_ml_count = sp_function.add_parser("get_ml_count")
        p_get_ml_count.add_argument("-timeout", type=int, default=0)

        p_no_op = sp_function.add_parser("no_op")

        p_eval = subparsers.add_parser("eval", help="Run python expressions")
        p_eval.set_defaults(func=self.handler_fun)
        p_eval.add_argument(
            "expression", help="WARNING: Only use input functions with gds_helper_batch"
        )

        if curses_interface:
            p_clear = subparsers.add_parser("clear", help="Clear ACK window")
            p_clear.set_defaults(func=self.handler_fun)
            p_layout, g_layout = self._add_action_exclusive_group(
                subparsers, "layout", self.handler_fun, "Control visual interface"
            )
            g_layout.add_argument(
                "-show", default=[], nargs="+", choices=InputParser.LAYOUT_OPTIONS
            )
            g_layout.add_argument(
                "-hide", default=[], nargs="+", choices=InputParser.LAYOUT_OPTIONS
            )
            g_layout.add_argument(
                "-set", default=[], nargs="+", choices=InputParser.LAYOUT_OPTIONS
            )
        else:
            # Add -no-feedback and -wait to all parsers
            for p in self.get_subparser_actions().values():
                p.add_argument(
                    "-no-feedback",
                    default=False,
                    action="store_true",
                    help="Ignore all feedback, just successfully return",
                )
                p.add_argument(
                    "-wait",
                    default=0,
                    type=self._positive_int,
                    help="Add a blocking wait of given seconds after command completion",
                )

        self.set_extra_validation_callback(self._validate_after_argparse)
        self.commands = self.get_subparser_actions()

    def complete(self, args_str):
        completing = args_str and args_str[-1] != " "
        last_action = last = None
        last_action_idx = 0
        parsers = [self]
        choices = []

        args = shlex.split(args_str)
        if not args:
            return "", self.get_choices().keys()
        last_chunk = args[-1] if completing else ""

        def looks_like_option(arg):
            return re.match("^(?=-+[a-z])", arg)

        def action_matches_nargs(action, args):
            if action is None:
                return False

            action_args = [a for a in args if not looks_like_option(a)]
            nargs = action.nargs if action.nargs != None else 1
            if isinstance(nargs, int):
                return nargs == len(action_args)
            elif nargs == "?":
                return len(action_args) in [0, 1]
            elif nargs == "+":
                return len(action_args) >= 1
            elif nargs == "*":
                return len(action_args) >= 0
            else:
                return False

        for i, chunk in enumerate(args):
            item = self.get_choices(parsers[-1]).get(chunk)
            last = item if item else chunk
            if isinstance(item, ArgumentParser):
                parsers.append(item)
            if isinstance(item, Action):
                last_action = item
                last_action_idx = i

        curr_parser_choices = self.get_choices(parsers[-1]).keys()

        if last == parsers[-1]:
            # Last chunk is a parser
            curr_parser = parsers[-2] if completing else parsers[-1]
            choices = self.get_choices(curr_parser).keys()
        elif last == last_action:
            # Last chunk is an action
            if completing:
                # User might not be done with action yet.
                # Run filter on all options
                choices = curr_parser_choices
            elif action_matches_nargs(last, args[last_action_idx + 1 :]):
                # Action already fullfils min number of arguments
                # Skip filtering, show all options for next
                return "", curr_parser_choices
            # Action needs arguments, try to suggest options
            elif last.choices:
                return "", last.choices
            elif isinstance(last.type, FileType):
                return "", os.listdir(".")
        else:
            # Last chunk may a value or an incomplete/invalid parser/action
            if looks_like_option(last) or not last_action:
                # Last chunk looks like an option or we have no known option yet
                choices = curr_parser_choices
            elif action_matches_nargs(last_action, args[last_action_idx + 1 :]):
                if not completing:
                    return "", curr_parser_choices

                if last_action.choices:
                    choices = last_action.choices
                elif isinstance(last_action.type, FileType):
                    dirname, rest = os.path.split(last_chunk)
                    sdir = dirname if dirname else "."
                    if not os.path.isdir(sdir):
                        choices = []

                    for e in os.listdir(sdir):
                        choices.append(
                            e + os.sep if os.path.isdir(os.path.join(dirname, e)) else e
                        )
                    last_chunk = rest

        choices = [str(c) for c in choices]
        matches = [i for i in choices if i.startswith(last_chunk)]
        common_start = os.path.commonprefix(matches)
        if len(matches) == 1:  # exact match
            if not common_start.endswith(os.sep):
                common_start += " "
            return args_str + common_start[len(last_chunk) :], []
        elif len(matches) > 1:  # more than one match
            if common_start and common_start != last_chunk:
                return args_str + common_start[len(last_chunk) :], []
            else:
                return "", matches
        return "", []

    def _add_action_exclusive_group(
        self, subparser, action_name, action_fun, help=None, required=True
    ):
        p = subparser.add_parser(action_name, help=help)
        p.set_defaults(func=action_fun)
        g = p.add_mutually_exclusive_group(required=required)
        return (p, g)

    def _positive_int(self, value):
        ivalue = int(value)
        if ivalue <= 0:
            raise ArgumentTypeError("%s is an invalid positive int value" % value)
        return ivalue

    def _validate_after_argparse(self, args):
        sp_name = args.subparser_name
        sp = self.get_subparser_action(sp_name)
        if sp_name == "arm":
            move_arm = args.tilt != None or args.pan != None
            exclusive_group_action = (
                args.gripper != None
                or args.deploy
                or args.stop
                or args.get
                or args.stow
            )

            if not move_arm and not exclusive_group_action:
                sys.stderr.write("Please choose one option\n")
                sys.stderr.write(sp.format_usage() + "\n")
                return False

            if move_arm and exclusive_group_action:
                sys.stderr.write("-tilt and -pan cannot be used with other options\n")
                sys.stderr.write(sp.format_usage() + "\n")
                return False
        elif sp_name == "light":
            if args.set:
                if args.front is None and args.back is None:
                    sys.stderr.write("Please choose one of the two lights\n")
                    sys.stderr.write(sp.format_usage() + "\n")
                    return False
                elif args.front == -1:
                    sys.stderr.write("Please set a value for light FRONT\n")
                    return False
                elif args.back == -1:
                    sys.stderr.write("Please set a value for light BACK\n")
                    return False
                elif args.front != None and args.front not in range(0, 101):
                    sys.stderr.write("Please set FRONT to a value between 0 and 100\n")
                    return False
                elif args.back != None and args.back not in range(0, 101):
                    sys.stderr.write("Please set BACK to a value between 0 and 100\n")
                    return False
            elif args.get:
                if not (
                    (args.front == -1 or args.front == None)
                    and (args.back == -1 or args.back == None)
                ):
                    sys.stderr.write(
                        "-front and -back take no arguments in -get mode\n"
                    )
                    return False
            else:
                return False
        elif sp_name == "power":
            options = [
                args.laser,
                args.pmc_signals,
                args.pay_ta,
                args.pay_ba,
                args.pay_bf,
            ]
            if args.set:
                count = 0
                for opt in options:
                    if opt:
                        count += 1
                        if opt not in ["on", "off"]:
                            sys.stderr.write(
                                'Please set component value to "on" or "off"\n'
                            )
                            return False
                if count == 0:
                    sys.stderr.write("Please select at least one component to power\n")
                    return False
            elif args.get:
                for opt in options:
                    if opt and opt != "info":
                        sys.stderr.write(
                            "Components take no argument when in -get mode\n"
                        )
                        return False
            else:
                return False
        elif sp_name == "camera":
            cameras = [args.nav, args.dock, args.sci, args.haz, args.perch]
            count = 0
            if args.record or args.stream:
                for cam in cameras:
                    if cam is not False:
                        count += 1
                        if len(cam) != 1:
                            sys.stderr.write(
                                "Each camera takes 1 argument (on|off) in -stream or -record mode\n"
                            )
                            return False
                        if cam[0] not in ["on", "off"]:
                            sys.stderr.write('Please set "on" or "off"\n')
                            return False
                if count == 0:
                    sys.stderr.write("Please select at least one camera\n")
                    sys.stderr.write(sp.format_usage() + "\n")
                    return False
            elif args.config:
                for cam in cameras:
                    if cam is not False:
                        count += 1
                        if len(cam) != 4:
                            sys.stderr.write(
                                "Each camera takes 4 arguements in -config mode\n"
                            )
                            sys.stderr.write(sp.format_usage() + "\n")
                            return False
                        rate = str_to_float(cam[2])
                        bitrate = str_to_float(cam[3])
                        if cam[0] not in CommandHandler.CAMERA_MODES.keys():
                            sys.stderr.write("Please select one camera mode\n")
                            sys.stderr.write(sp.format_usage() + "\n")
                            return False
                        if cam[1] not in CommandHandler.CAMERA_RESOLUTIONS:
                            sys.stderr.write("Please select one resolution\n")
                            sys.stderr.write(sp.format_usage() + "\n")
                            return False
                        if rate == None or bitrate == None:
                            sys.stderr.write("Rates need to be float values\n")
                            sys.stderr.write(sp.format_usage() + "\n")
                            return False
                        cam[2] = rate
                        cam[3] = bitrate
                if count == 0:
                    sys.stderr.write("Please select at least one camera\n")
                    sys.stderr.write(sp.format_usage() + "\n")
                    return False
            elif args.get:
                for cam in cameras:
                    if cam is not False and len(cam) > 0:
                        sys.stderr.write(
                            "Each camera takes no arguments in -get mode\n"
                        )
                        sys.stderr.write(sp.format_usage() + "\n")
                        return False
            else:
                return False
        elif sp_name == "limits":
            if args.set is not None:
                if len(args.set) != 7:
                    sys.stderr.write("-set takes 7 arguments\n")
                    sys.stderr.write(sp.format_usage() + "\n")
                    return False
                args.set[2] = str_to_float(args.set[2])
                args.set[3] = str_to_float(args.set[3])
                args.set[4] = str_to_float(args.set[4])
                args.set[5] = str_to_float(args.set[5])
                args.set[6] = str_to_float(args.set[6])
                if args.set[1] not in CommandHandler.FLIGHT_MODES.keys():
                    sys.stderr.write("Please choose a valid flight_mode\n")
                    sys.stderr.write(sp.format_usage() + "\n")
                    return False
                if (
                    args.set[2] is None
                    or args.set[3] is None
                    or args.set[4] is None
                    or args.set[5] is None
                    or args.set[6] is None
                ):
                    sys.stderr.write("Arguments 3-7 need to be float values\n")
                    sys.stderr.write(sp.format_usage() + "\n")
                    return False
        elif sp_name == "move":
            if args.pos is None and args.att is None:
                sys.stderr.write("Please specify pos/att/relative\n")
                sys.stderr.write(sp.format_usage() + "\n")
                return False
        elif sp_name == "telemetry":
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
            names = [
                "-comm",
                "-cpu",
                "-disk",
                "-ekf",
                "-gnc",
                "-pmc",
                "-position",
                "-sparse_map_pose",
            ]
            if args.set:
                count = 0
                for i, opt in enumerate(options):
                    if opt != None:
                        count += 1
                        if opt < 0:
                            sys.stderr.write(
                                "Argument %s takes a positive float value\n" % names[i]
                            )
                            return False
                if count == 0:
                    sys.stderr.write("Please select at least one telemetry item\n")
                    sys.stderr.write(sp.format_usage() + "\n")
                    return False
            elif args.get:
                for i, opt in enumerate(options):
                    if opt != None and opt != -1:
                        sys.stderr.write(
                            "Argument %s takes no value in -get mode\n" % names[i]
                        )
                        return False
            else:
                return False
        return True
