#!/usr/bin/env python

import os
import shlex
import signal
import sys
import time
import traceback
from argparse import ArgumentParser, FileType

import yaml
from commanding.astrobee_handler import AstrobeeHandler
from commanding.input_parser import InputParser

# filepath = os.path.dirname(os.path.realpath(__file__))
# sys.path.append(os.path.join(filepath, "../scripts"))
# sys.path.append(os.path.join(filepath, "../common"))
# import yaml_parser
# from astrobee_handler import AstrobeeHandler
from ff_msgs.msg import AckCompletedStatus, AckStatus
from util import yaml_parser
from util.shell_colors import Back, Colors, Fore, Style
from util.utils import read_input

# from input_parser import InputParser
# from shell_colors import Back, Colors, Fore, Style
# from utils import read_input


class GdsHelperBatch(AstrobeeHandler):
    def __init__(self):
        AstrobeeHandler.__init__(self)
        self.handler_parser = InputParser(
            self.handle_action, "Astrobee Commanding Helper Batch"
        )
        self.handler_parser.build_parser()
        time.sleep(0.3)

    def execute_command(self, command_str=""):
        # Convert string into a list of arguments
        chunks = shlex.split(command_str)
        # Send arguments to parser and capture output from the parser if any
        (
            self.args,
            self.unknown,
            exit_output,
        ) = self.handler_parser.parse_arguments_capture_output(chunks)

        if exit_output:
            # Parser could not understand the command, showing error to user
            print(exit_output + "\n")
            return False

        if self.args is not None:
            # Input was parsed successfully, send to predefined handler function
            print("\n%s[ EXECUTE ]%s : %s" % (Style.bold, Colors.reset, command_str))
            self.args.func(self.args)

        # Wait for feedback on the command if needed
        was_completed_ok = True
        while not self.args.no_feedback:
            consumed, was_completed_ok = self._process_feedback()
            if consumed:
                break
            time.sleep(0.3)

        time.sleep(self.args.wait)
        return was_completed_ok

    def execute_command_list(self, commands, ignore_errors, interactive):
        for idx, cmd in enumerate(commands):
            # If completed, continue, otherwise react accordingly
            if self.execute_command(cmd):
                continue
            if interactive:
                msg = (
                    Style.bold
                    + Fore.orange
                    + "[ PAUSED  ]"
                    + Colors.reset
                    + " Enter=ignore, R=retry, E=edit, Q=exit : "
                )
                inp = read_input(msg)
                if inp == "Q":
                    return idx + 1
                if inp == "E":
                    msg = "%s[ EDITING ]%s : " % (Style.bold, Colors.reset)
                    commands[idx] = read_input(msg, commands[idx])
                if inp == "R" or inp == "E":
                    return self.execute_command_list(
                        commands[idx:], ignore_errors, interactive
                    )
            elif not ignore_errors:
                return idx + 1
        return 0

    def menu_interface(self, commands, ignore_errors, interactive):
        ret = -1

        def _print_menu():
            print("\n%s[ MENUOPT ]%s\n" % (Style.bold + Fore.lightblue, Colors.reset))
            for i, c in enumerate(commands):
                print("%d) %s" % (i, c))

        if commands is None:
            print(
                "%s%s[ FAILED  ]%s No commands to show\n"
                % (Style.bold, Fore.red, Colors.reset)
            )
            return ret

        _print_menu()

        while True:
            msg = (
                "\n%s[ SELECT  ]%s" % (Style.bold, Colors.reset)
                + " Range|Index=execute, IndexE=edit, IndexQ=queue, M=menu, Q=exit : "
            )
            selection = read_input(msg)

            if selection == "Q":
                return 0

            try:
                if selection == "M":
                    # See comment at try-else clause
                    # pass
                    _print_menu()
                elif selection.endswith("E"):
                    idx = int(selection[:-1])
                    msg = Style.bold + Fore.orange + "[ EDITING ] " + Colors.reset
                    commands[idx] = read_input(msg, commands[idx])
                elif selection.endswith("Q"):
                    idx = int(selection[:-1])
                    msg = Style.bold + Fore.orange + "[ PAUSED  ] " + Colors.reset
                    self.execute_command_list(
                        [read_input(msg, commands[idx])], ignore_errors, interactive
                    )
                elif selection:
                    chunks = selection.split(":")
                    start = int(chunks[0]) if chunks[0] else None
                    if not chunks[1:]:
                        # User provided a single index
                        end = start + 1
                    else:
                        # User provided a range
                        end = int(chunks[1]) + 1 if chunks[1] else None
                    if not commands[start:end]:
                        raise IndexError("Entry did not produce commands to execute")
                    self.execute_command_list(
                        commands[start:end], ignore_errors, interactive
                    )
                else:
                    raise TypeError("No selection received")
            except (TypeError, ValueError, IndexError) as e:
                print(
                    "%s%s[ ERROR   ]%s Invalid entry\n"
                    % (Style.bold, Fore.red, Colors.reset)
                )
                print(e)
            # Maybe we don't want to print the menu every time?
            # else:
            #     _print_menu()

    def _process_feedback(self):
        if not self.cmdh.feedback_cmds.isEmpty():
            cmd_fback = self.cmdh.feedback_cmds.dequeue()
            if cmd_fback.id == self.cmdh.last_cmd_id:
                # ACK matches command, process
                cmd_fback.translate_status()
                cmd = self.cmdh.sent_cmds[cmd_fback.id]
                msg = "%s[ REPLY   ]%s : %s, Status: %s, Completed: %s" % (
                    Style.bold,
                    Colors.reset,
                    cmd.name,
                    cmd_fback.str_status,
                    cmd_fback.str_completed_status,
                )

                if cmd_fback.message != "":
                    msg += "\n%s[ MESSAGE ]%s : %s" % (
                        Style.bold,
                        Colors.reset,
                        cmd_fback.message,
                    )
                print(msg)

                if cmd_fback.status == AckStatus.COMPLETED:
                    # Feedback consumed and result dependent on feedback
                    if cmd_fback.completed_status == AckCompletedStatus.OK:
                        print(Style.bold + Fore.green + "[ SUCCESS ]\n" + Colors.reset)
                        return (True, True)
                    else:
                        print(Style.bold + Fore.red + "[ FAILED  ]\n" + Colors.reset)
                        return (True, False)

        if not self.telh.feedback_telemetry.isEmpty():
            tel_fback = self.telh.feedback_telemetry.dequeue()
            msg = "%s[ SUMMARY ]%s : %s : %s" % (
                Style.bold,
                Colors.reset,
                tel_fback.summary,
                tel_fback.description,
            )

            # msg = "++ %s: %s" % ( tel_fback.summary, tel_fback.description)
            for k, v in tel_fback.data.items():
                if isinstance(v, float):
                    v = round(v, 4)
                msg += "\n| %s : %s" % (k, v)
            print(msg)
            if tel_fback.success:
                print(Style.bold + Fore.green + "[ SUCCESS ]\n" + Colors.reset)
            else:
                print(Style.bold + Fore.red + "[ FAILED  ]\n" + Colors.reset)

            # Feedback consumed and return result
            return (True, tel_fback.success)

        # No feedback consumed and not successful
        return (False, False)


def flatten_list(data):
    flat_list = []
    for element in data:
        if isinstance(element, list):
            flat_list += flatten_list(element)
        else:
            flat_list.append(element)
    return flat_list


def is_list_of_strings(lst):
    if lst and isinstance(lst, list):
        return all(is_string(elem) for elem in lst)
    else:
        return False


def is_string(input):
    # Python 2 and 3 compatible
    if hasattr(__builtins__, "basestring"):
        return isinstance(input, basestring)
    else:
        return isinstance(input, str)


def parse_and_get_command_list(file, section, argsk, argsv):
    ret, parsed = yaml_parser.parse_document(file, 0, section, argsk, argsv)

    # Flatten multiline lists in case references were used in yaml file
    if isinstance(parsed, list):
        parsed = flatten_list(parsed)
        # Remove empty elements
        parsed = [cmd for cmd in parsed if cmd]

    if parsed != None and not is_list_of_strings(parsed):
        print(
            "Procedure or section is not a list of strings. May be "
            + " wrong format or you may need to choose a section"
        )
        return None

    return parsed


def handler(signum, frame):
    print(
        "\n%s%s[ SUMMARY ]%s : User stopped execution!"
        % (Style.bold, Fore.blue, Colors.reset)
    )
    # sys.exit(0)
    os._exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, handler)
    parser = ArgumentParser(description="GDS Helper Batch")

    g_mode = parser.add_mutually_exclusive_group(required=False)
    g_mode.add_argument(
        "-dependent",
        "-d",
        default=False,
        action="store_true",
        help="Stop sequence if one item fails, this is the default mode",
    )
    g_mode.add_argument(
        "-interactive",
        "-i",
        default=False,
        action="store_true",
        help="Allow the user to repeat, skip, or cancel if one item fails",
    )
    g_mode.add_argument(
        "-skip_errors",
        "-s",
        default=False,
        action="store_true",
        help="Ignore errors, continue with the sequence",
    )
    parser.add_argument(
        "-menu",
        "-m",
        default=False,
        action="store_true",
        help="Do not start the sequence, instead, show a menu with given items",
    )

    subparsers = parser.add_subparsers(dest="subparser_name")

    p_cmd = subparsers.add_parser(
        "cmd", help="Run a batch of commands given as arguments"
    )
    p_cmd.add_argument(
        "commands",
        nargs="+",
        help="A collections of commands separated by @@, no quotes needed",
    )

    p_read = subparsers.add_parser(
        "file", help="Read commands from file, syntax same as regular gds_helper"
    )
    p_read.add_argument("file", type=FileType("r"))

    p_file = subparsers.add_parser(
        "plan", help="Run a batch of commands given a predefined plan file"
    )
    p_file.add_argument(
        "ifile",
        type=FileType("r"),
        help="A file in yaml format containing the commands for the helper",
    )
    p_file.add_argument("section", nargs="?", default=None)
    p_file.add_argument("-args_yaml", "-a", default=[], nargs="*")
    p_file.add_argument(
        "-kwargs_yaml", "-k", default={}, nargs="*", action=yaml_parser.ParseKwargs
    )
    args = parser.parse_args()
    cmd_helper = GdsHelperBatch()
    ret = -1
    cmds = []
    if args.subparser_name == "cmd":
        cmds = " ".join(args.commands).split("@@")
    if args.subparser_name == "file":
        cmds = args.file.read().split("\n")[:-1]
    if args.subparser_name == "plan":
        cmds = parse_and_get_command_list(
            args.ifile, args.section, args.args_yaml, args.kwargs_yaml
        )

    if args.menu:
        ret = cmd_helper.menu_interface(cmds, args.skip_errors, args.interactive)
    elif cmds != None:
        ret = cmd_helper.execute_command_list(cmds, args.skip_errors, args.interactive)
        if ret >= 0:
            executed_cmds = len(cmds) if ret == 0 else ret
            print(
                "\n%s%s[ SUMMARY ]%s : Executed %d/%d commands"
                % (Style.bold, Fore.blue, Colors.reset, executed_cmds, len(cmds))
            )

    # There is a bug in rospy for Ubuntu 16-20 which causes a race condition
    # at shutdown. You may get Exceptions about socket.close() at this point.
    # A workaround has been merged but not yet available as debian package.

    # See:
    # https://github.com/ros/ros_comm/issues/2212
    # https://github.com/ros/ros_comm/pull/2233

    # sys.exit(ret)

    # In the meantime... let's kill it with fire
    os._exit(ret)
