#!/usr/bin/env python

import sys
from argparse import ArgumentParser, _SubParsersAction
from contextlib import contextmanager

try:
    # Python 2
    from cStringIO import StringIO
except ImportError:
    # Python 3
    from io import StringIO


class ArgumentParserRedirect(ArgumentParser):
    def __init__(self, *args, **kwargs):
        self.validation_callback = None
        ArgumentParser.__init__(self, *args, **kwargs)

    def get_subparser_actions(self, parser=None):
        ret = {}
        parser = self if parser is None else parser
        subparsers_actions = [
            action
            for action in parser._actions
            if isinstance(action, _SubParsersAction)
        ]

        for subparsers_action in subparsers_actions:
            # get all subparsers and print help
            for choice, subparser in subparsers_action.choices.items():
                ret[choice] = subparser
        return ret

    def get_choices(self, parser=None):
        choices = self.get_subparser_actions(parser)
        parser = self if parser is None else parser
        choices.update(parser._optionals._option_string_actions)
        return choices

    def get_subparser_action(self, action_name):
        actions = self.get_subparser_actions()
        return actions.get(action_name, None)

    def set_extra_validation_callback(self, callback):
        self.validation_callback = callback

    def parse_known_args_and_validate(self, input):
        args, unknown = self.parse_known_args(input)
        if self.validation_callback is not None and not self._run_validation_callback(
            args
        ):
            return (None, None)
        else:
            return (args, unknown)

    def _run_validation_callback(self, args):
        ret = self.validation_callback(args)
        if ret is None:
            return False
        else:
            return ret

    @contextmanager
    def _redirect_stdout_stderr(self, stream):
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = stream
        sys.stderr = stream
        try:
            yield
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

    def parse_arguments_capture_output(self, input):
        f = StringIO()
        args = unknown = output = None
        with self._redirect_stdout_stderr(f):
            try:
                args, unknown = self.parse_known_args_and_validate(input)
            except SystemExit:
                pass
        return (args, unknown, f.getvalue())
