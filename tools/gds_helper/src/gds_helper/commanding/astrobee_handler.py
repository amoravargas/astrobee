#!/usr/bin/env python

import os
import sys

# from command_handler import CommandHandler
# from telemetry_handler import TelemetryHandler
from commanding.command_handler import CommandHandler
from commanding.telemetry_handler import TelemetryHandler
from util.ros_node import RosNode

# filepath = os.path.dirname(os.path.realpath(__file__))
# sys.path.append(os.path.join(filepath, "../../common"))
# from ros_node import RosNode


class AstrobeeHandler(RosNode):
    NODE_BASE_NAME = "astrobee_handler_node"

    def __init__(self, anonymous=True, disable_signals=False):
        RosNode.__init__(
            self, AstrobeeHandler.NODE_BASE_NAME, anonymous, disable_signals
        )
        self.run()
        self.cmdh = CommandHandler(self)
        self.telh = TelemetryHandler(self)
        self.callbacks = {}

    def handle_action(self, args):
        action_name = "action_" + args.subparser_name
        cmd_action = getattr(self.cmdh, action_name, lambda x: False)
        tel_action = getattr(self.telh, action_name, lambda x: False)
        callback = self.callbacks.get(action_name, lambda x: False)
        return cmd_action(args) or tel_action(args) or callback(args)
