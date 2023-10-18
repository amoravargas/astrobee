#!/bin/sh
"""":
pybin=$( which python || which python3 ) || { echo >&2 "Python not found"; exit 1; }
exec $pybin "$0" "$@"
"""  # "

# TODO: Resources consumed are low but can be better
# TODO: Make it resiliant to FSW restarts
# TODO: Finish implementation of some commands
# TODO: Add more help to argparse
# TODO: Add help to the visual interface
# TODO: Add menus?
# TODO: Add extra commands, like arm raw commands and FSW checks
# TODO: Add more aliases
# TODO: Add checks to make sure all topics required are being published

import curses
import os
import shlex
import signal
import sys
from math import degrees, isnan

import rosgraph

try:
    from shlex import quote as cmd_quote
except ImportError:
    from pipes import quote as cmd_quote
# Custom imports
# filepath = os.path.dirname(os.path.realpath(__file__))
# sys.path.append(os.path.join(filepath, "../common"))
# sys.path.append(os.path.join(filepath, "../scripts"))
# from astrobee_handler import AstrobeeHandler
# from curses_wt import (CommandTextBox, Label, LayoutProperties, LinearLayout,
#                       LinearLayoutProperties, Menu, MenuItem, MenuView,
#                       Screen, TextView)
# from input_parser import InputParser
# from telemetry_handler import TelemetryHandler
# from utils import euler_from_quaternion

from commanding.astrobee_handler import AstrobeeHandler
from commanding.input_parser import InputParser
from commanding.telemetry_handler import TelemetryHandler
from util.curses_wt import (
    CommandTextBox,
    Label,
    LayoutProperties,
    LinearLayout,
    LinearLayoutProperties,
    Menu,
    MenuItem,
    MenuView,
    Screen,
    TextView,
)
from util.utils import euler_from_quaternion


class GdsHelper(Screen):
    def __init__(self, layout=None):
        Screen.__init__(self, exit_key=curses.KEY_F12)
        # Layouts
        self.layout_selection = layout
        self.parent_layout = None
        self.cmd_layout = None
        self.tel_layout = None
        # Windows
        self.cmdwin = None
        self.infowin = None
        self.telwin = None
        self.gswin = None
        # Print GS data or not (only affects the display, data is still captured)
        self.print_gs_data = True
        # GS config and state
        self.apks = None
        self.apk_states = None
        # Initial absolute position for cursor
        self.abs_x = self.abs_y = 0
        # Keys the application recognizes for control
        self.cmds2ackwin = [curses.KEY_F2, curses.KEY_F3]
        self.ackwin_keymap = {
            curses.KEY_F2: curses.KEY_UP,
            curses.KEY_F3: curses.KEY_DOWN,
        }
        self.menuwin_keymap = {
            curses.KEY_F4: curses.KEY_UP,
            curses.KEY_F5: curses.KEY_DOWN,
        }
        self.telwin_keymap = {
            curses.KEY_F6: curses.KEY_UP,
            curses.KEY_F7: curses.KEY_DOWN,
        }
        self.gswin_keymap = {
            curses.KEY_F9: curses.KEY_UP,
            curses.KEY_F10: curses.KEY_DOWN,
            curses.KEY_F8: curses.KEY_F8,
        }

        # Telemetry display pattern
        self.tel_pattern = (
            "\033[07m X \033[00m{pos_x:< 7.{ndigits}f} "
            "\033[07m Y \033[00m{pos_y:< 7.{ndigits}f} "
            "\033[07m Z \033[00m{pos_z:< 7.{ndigits}f}\n"
            "\033[07m R \033[00m{roll:< 7.{ndigits}f} "
            "\033[07m P \033[00m{pitch:< 7.{ndigits}f} "
            "\033[07m Y \033[00m{yaw:< 7.{ndigits}f}"
        )
        self.tel_pattern += (
            "\n\n\033[07m TILT \033[00m{tilt_ang: .{ndigits}f} "
            "\033[07m PAN \033[00m{pan_ang: .{ndigits}f} "
            "\033[07m GRIP \033[00m{gripper_ang: .{ndigits}f}"
        )
        self.tel_pattern += (
            "\n\n\033[07m STATUS   \033[00m {op_state}/{mob_state} {sub_mob_state}"
        )
        self.tel_pattern += (
            "\n\n\033[07m FACE FORWARD \033[00m {ff}"
            "\n\033[07m OBSTACLES    \033[00m {obstacles}"
            "\n\033[07m CHECK ZONES  \033[00m {zones}"
            "\n\033[07m FLIGHT MODE  \033[00m {fm_profile}/{f_mode}"
        )
        self.tel_pattern += "\n\n\033[07m BAGGER   \033[00m {recording}{profile}"
        self.tel_pattern += "\n\n\033[07m DATA LLP \033[00m {llp_data:.1%} \033[07m MLP \033[00m {mlp_data:.1%}"
        self.tel_pattern += "\n\n\033[07m FEAT ML  \033[00m {ml_count:d} \033[07m AR \033[00m {ar_count:d}"
        self.tel_pattern += "\n\n\033[07m BATTERY  \033[00m {batt_tl}% | {batt_tr}% | {batt_bl}% | {batt_br}%"
        self.tel_pattern += (
            "\n\n\033[07m FAULTS   \033[00m {faults_count:d}\n\n{faults_list}"
        )
        # Actual string to display, it will be contructed later from pattern
        self.tel_str = ""
        # This will handle user input and send it to the right implementation
        self.handler = AstrobeeHandler()
        self.handler.callbacks["action_clear"] = lambda x: self.ackwin.set_text("")
        self.handler.callbacks["action_layout"] = self.control_layout
        # Create command line interface
        self.parser = InputParser(
            self.handler.handle_action, "Astrobee Commanding Helper"
        )
        self.parser.build_parser(curses_interface=True)
        self.failed_master_calls = 0
        self.respawn = False

    def on_start(self):
        # Parent container
        self.parent_layout = LinearLayout(LinearLayout.HORIZONTAL)

        # Build commanding and text display section
        self.cmd_layout = LinearLayout(LinearLayout.VERTICAL)
        self.cmd_layout.layout_properties = LinearLayoutProperties(
            0.5, LayoutProperties.PERCENTAGE
        )
        self.cmdtxt = Label(
            "\n % Commanding [UP/DOWN: History | F12: Exit]", attributes=curses.A_BOLD
        )
        self.cmdtxt.layout_properties = LinearLayoutProperties(size=2)
        self.cmdwin = CommandTextBox(self.submit_callback, padding=1)
        self.cmdwin.layout_properties = LinearLayoutProperties(size=3)
        self.acktxt = Label(
            "\n % ACKs and help [F2/F3: Scroll]", attributes=curses.A_BOLD
        )
        self.acktxt.layout_properties = LinearLayoutProperties(size=2)
        self.ackwin = TextView(keep_on_tail=True)
        self.ackwin.layout_properties = LinearLayoutProperties(
            0.7, LayoutProperties.PERCENTAGE
        )
        self.menutxt = Label("\n % GS Menu [F4/F5: Scroll]", attributes=curses.A_BOLD)
        self.menutxt.layout_properties = LinearLayoutProperties(size=2)
        self.menuwin = Menu()
        self.menuwin.layout_properties = LinearLayoutProperties(
            0.3, LayoutProperties.PERCENTAGE
        )
        self.cmd_layout.add(self.cmdtxt)
        self.cmd_layout.add(self.cmdwin)
        self.cmd_layout.add(self.acktxt)
        self.cmd_layout.add(self.ackwin)
        self.cmd_layout.add(self.menutxt)
        self.cmd_layout.add(self.menuwin)

        # Telemetry layout
        self.tel_layout = LinearLayout(LinearLayout.VERTICAL)
        self.tel_layout.layout_properties = LinearLayoutProperties(
            0.5, LayoutProperties.PERCENTAGE
        )
        # Telemetry window
        self.teltxt = Label("\n % Telemetry [F6/F7: Scroll]", attributes=curses.A_BOLD)
        self.teltxt.layout_properties = LinearLayoutProperties(size=2)
        self.telwin = TextView()
        self.telwin.layout_properties = LinearLayoutProperties(
            0.6, LayoutProperties.PERCENTAGE
        )
        self.gstxt = Label(
            "\n % GS Data [F9/F10: Scroll | F8: Pause/Play]", attributes=curses.A_BOLD
        )
        self.gstxt.layout_properties = LinearLayoutProperties(size=2)
        self.gswin = TextView()
        self.gswin.layout_properties = LinearLayoutProperties(
            0.4, LayoutProperties.PERCENTAGE
        )

        self.tel_layout.add(self.teltxt)
        self.tel_layout.add(self.telwin)
        self.tel_layout.add(self.gstxt)
        self.tel_layout.add(self.gswin)

        self.parent_layout.add(self.cmd_layout)
        self.parent_layout.add(self.tel_layout)
        self.set_layout(self.parent_layout)
        self.draw()

        # Temporal fixed position
        self.abs_x = 1
        self.abs_y = 3
        # Print help message
        info_txt = "\033[07m Welcome to the GDS helper "
        self.ackwin.set_text(info_txt)

        if self.layout_selection:
            self.submit_callback("layout -set " + " ".join(self.layout_selection))

    def _set_cmdwin_text(self, text):
        self.cmdwin.set_text(text)
        self.cmdwin._show_line_end()
        self.abs_y, self.abs_x = curses.getsyx()

    def handle_input(self, input):
        if input != self.exit_key:
            if input in self.ackwin_keymap:
                self.ackwin.handle_input(self.ackwin_keymap.get(input))
            elif input in self.telwin_keymap:
                self.telwin.handle_input(self.telwin_keymap.get(input))
            elif input in self.gswin_keymap:
                if input == curses.KEY_F8:
                    self.print_gs_data = not self.print_gs_data
                else:
                    self.gswin.handle_input(self.gswin_keymap.get(input))
            elif input in self.menuwin_keymap:
                self.menuwin.handle_input(self.menuwin_keymap.get(input))
            elif input == 9:  # TAB
                curr_text = self.cmdwin.get_text()
                if self.cmdwin._cursor_pointer != len(curr_text):
                    # Ignore if not at the end of the buffer
                    return
                # Complete/suggest
                completed, suggestions = self.parser.complete(curr_text)
                if completed:
                    self._set_cmdwin_text(completed)
                elif suggestions:
                    suggestions = [str(s) for s in suggestions]
                    self.ackwin.add_text(
                        "\n\n\033[07m OPTIONS \n" + "\n".join(suggestions)
                    )
            else:
                self.cmdwin.handle_input(input)
                self.abs_y, self.abs_x = curses.getsyx()

    def do_background(self):
        if not rosgraph.is_master_online():
            self.failed_master_calls += 1
            if self.failed_master_calls > 2:
                self._input = self.exit_key
                self.respawn = True

        # Update displays
        self._update_ack_window()
        self._update_gs_menu()
        self._update_telemetry_window()
        self._update_gs_data()

        # Move cursor back to last absolute position before printing characteres
        self.move_cursor(self.abs_x, self.abs_y)

    def _update_ack_window(self):
        # Print ACK feedback
        while not self.handler.cmdh.feedback_cmds.isEmpty():
            cmd_fback = self.handler.cmdh.feedback_cmds.dequeue()
            cmd_fback.translate_status()
            cmd = self.handler.cmdh.sent_cmds[cmd_fback.id]
            msg = "\033[01m %s [%d] \033[00m%s :: Result %s" % (
                cmd.name,
                cmd.seq,
                cmd_fback.str_status,
                cmd_fback.str_completed_status,
            )
            if cmd_fback.message != "":
                msg += "\n %s" % cmd_fback.message
            self.ackwin.add_text(msg)

        # Print requested telemetry
        while not self.handler.telh.feedback_telemetry.isEmpty():
            tel_fback = self.handler.telh.feedback_telemetry.dequeue()
            msg = " \033[01m%s:\033[00m %s" % (tel_fback.summary, tel_fback.description)
            for k, v in tel_fback.data.items():
                if isinstance(v, float):
                    v = round(v, 4)
                msg += "\n   %s: %s" % (k, v)
            self.ackwin.add_text(msg)

    def _update_gs_menu(self):
        if self.menuwin.is_hidden():
            # We don't need a history of menu items so, saves us some
            # computation if menu is not visible
            return

        apks = self.handler.telh.gs_config.apks
        apk_states = self.handler.telh.gs_state.runningApks

        if apks == self.apks and apk_states == self.apk_states:
            # Nothing new, let's igonore this
            return

        if len(apks) != len(apk_states):
            # Unmatched telemetry, ignore
            return

        clear_cmd = lambda: self._set_cmdwin_text("")

        current_menu = self.menuwin._current_menu._name
        self.menuwin.clear_items()
        self.menuwin.set_title(
            "%d APKs available" % len(apks), hover_callback=clear_cmd
        )
        self.menuwin._back_hover = lambda: self._set_cmdwin_text("1")

        for i, apk in enumerate(apks):
            state = "ACTIVE" if apk_states[i] else " IDLE "
            # Callbacks
            fill_index = lambda i=i: self._set_cmdwin_text(str(i + 1))
            fill_apk_start = lambda apk=apk: self._set_cmdwin_text(
                'gs -start "%s"' % apk.short_name
            )
            fill_apk_stop = lambda apk=apk: self._set_cmdwin_text(
                'gs -stop "%s"' % apk.short_name
            )
            start_apk = lambda apk=apk: self.submit_callback(
                'gs -start "%s"' % apk.short_name
            )
            stop_apk = lambda apk=apk: self.submit_callback(
                'gs -stop "%s"' % apk.short_name
            )

            # Add an item per APK
            item_text = "[%s] %s" % (state, apk.short_name)
            item = self.menuwin.add_item(item_text, hover_callback=fill_index)

            submenu = item.add_submenu(
                apk.apk_name, item_text, hover_callback=clear_cmd
            )

            # Add start/stop commands
            submenu.add_item("Start", start_apk, fill_apk_start)
            submenu.add_item("Stop", stop_apk, fill_apk_stop)

            # Add all other custom commands
            for c in apk.commands:
                cmd_s = "gs -cmd '%s' %s" % (apk.short_name, cmd_quote(c.command))
                cmd_callback = lambda cmd_s=cmd_s: self._set_cmdwin_text(cmd_s)
                submenu.add_item(c.name, cmd_callback, cmd_callback)

        self.menuwin.set_current_menu(current_menu)

        self.menuwin._draw_items(refresh=False)

        self.apks = apks
        self.apk_states = apk_states

    def _update_telemetry_window(self):
        if self.telwin.is_hidden():
            # We don't need a history of telemetry so, saves us some
            # computation if telemetry win is not visible
            return

        # Poll and process robot main telemetry
        pose = self.handler.telh.ekf_state.pose
        rot = euler_from_quaternion(
            pose.orientation.x,
            pose.orientation.y,
            pose.orientation.z,
            pose.orientation.w,
        )
        agent_state = self.handler.telh.agent_state
        bagger_state = self.handler.telh.bagger_state
        llp_data = self.handler.telh.llp_data_state
        mlp_data = self.handler.telh.mlp_data_state
        fault_str = ""  # TODO
        for f in self.handler.telh.sys_monitor_state.faults:
            fault_str += "%d: %s\n" % (f.id, f.msg)

        # Poll and process battery information
        batt_info = [
            self.handler.telh.battery_tl_state.percentage,
            self.handler.telh.battery_tr_state.percentage,
            self.handler.telh.battery_bl_state.percentage,
            self.handler.telh.battery_br_state.percentage,
        ]

        batt_currents = [
            self.handler.telh.battery_tl_state.current,
            self.handler.telh.battery_tr_state.current,
            self.handler.telh.battery_bl_state.current,
            self.handler.telh.battery_br_state.current,
        ]

        for k, batt in enumerate(batt_info):
            if isinstance(batt, float) and not isnan(batt):
                # Inactive
                sign = ""
                if batt_currents[k] > 0:
                    # Charging
                    sign = "+"
                if batt_currents[k] < 0:
                    # Discharging
                    sign = "-"
                batt_info[k] = "%s%d" % (sign, int(batt * 100))
            else:
                # Not present
                batt_info[k] = "NaN"

        # Generate telemetry string from pattern
        self.tel_str = self.tel_pattern.format(
            pos_x=pose.position.x,
            pos_y=pose.position.y,
            pos_z=pose.position.z,
            roll=degrees(rot[0]),
            pitch=degrees(rot[1]),
            yaw=degrees(rot[2]),
            ndigits=2,
            # Arm
            tilt_ang=self.handler.telh.arm_tilt_angle,
            pan_ang=self.handler.telh.arm_pan_angle,
            gripper_ang=self.handler.telh.arm_gripper_angle,
            # Agent state
            op_state=TelemetryHandler.OPERATING_STATE.get(
                agent_state.operating_state.state, "-"
            ),
            mob_state=TelemetryHandler.MOBILITY_STATE.get(
                agent_state.mobility_state.state, "-"
            ),
            sub_mob_state=agent_state.mobility_state.sub_state,
            ff=not agent_state.holonomic_enabled,
            obstacles=agent_state.check_obstacles,
            zones=agent_state.check_zones,
            fm_profile=agent_state.profile_name if agent_state.profile_name else "-",
            f_mode=agent_state.flight_mode,
            # Bagger state
            profile=bagger_state.name or "no profile",
            recording="\033[07m REC \033[00m " if bagger_state.recording else "",
            llp_data=(
                float(llp_data.disks[0].used) / float(llp_data.disks[0].capacity)
                if llp_data.disks
                else -0.01
            ),
            mlp_data=(
                float(mlp_data.disks[0].used) / float(mlp_data.disks[0].capacity)
                if mlp_data.disks
                else -0.01
            ),
            # Feature count
            ml_count=len(self.handler.telh.ml_features.landmarks),
            ar_count=len(self.handler.telh.ar_features.landmarks),
            # Batteries
            batt_tl=batt_info[0],
            batt_tr=batt_info[1],
            batt_bl=batt_info[2],
            batt_br=batt_info[3],
            # Faults
            faults_count=len(self.handler.telh.sys_monitor_state.faults),
            faults_list=fault_str,
        )
        # Display telemetry
        self.telwin.set_text(self.tel_str)

    def _update_gs_data(self):
        # Print GS data
        while not self.handler.telh.gs_data_queue.isEmpty() and self.print_gs_data:
            gs_data = self.handler.telh.gs_data_queue.dequeue()
            short_apk_name = self.handler.cmdh._get_apk_short_name(
                gs_data.apk_name, gs_data.apk_name
            )
            msg = "\n\n\033[07mAPK/TOPIC\033[00m %s/%s\n%s" % (
                short_apk_name,
                gs_data.topic,
                str(gs_data.data),
            )
            self.gswin.add_text(msg)

        # Update F8 label to show if data is being printed or in paused state
        gstxt_f8 = "Pause" if self.print_gs_data else "Resume"
        self.gstxt.set_text("\n % GS Data [F9/F10: Scroll | F8: " + gstxt_f8 + "]")

    def submit_callback(self, args_str):
        if args_str.isdigit() and not self.menuwin.is_hidden():
            self.menuwin.handle_input(args_str)
        else:
            txt = "\n\033[07m COMMAND \033[00m %s [%d]" % (
                args_str,
                self.handler.cmdh.cmd_count + 1,
            )
            self.ackwin.add_text(txt)
            self.execute_command(shlex.split(args_str))

    def execute_command(self, input):
        self.args, self.unknown, output = self.parser.parse_arguments_capture_output(
            input
        )
        if self.args is not None:
            self.args.func(self.args)
        if output:
            self.ackwin.add_text(output)

    def _set_visibility(self, sections, hidden):
        self.scr.clear()

        for item in sections:
            if item == "ack":
                self.acktxt.set_hidden(hidden)
                self.ackwin.set_hidden(hidden)
            if item == "menu":
                self.menutxt.set_hidden(hidden)
                self.menuwin.set_hidden(hidden)
            if item == "tel":
                self.teltxt.set_hidden(hidden)
                self.telwin.set_hidden(hidden)
            if item == "data":
                self.gstxt.set_hidden(hidden)
                self.gswin.set_hidden(hidden)

        telemetry_hidden = (
            self.teltxt.is_hidden()
            and self.telwin.is_hidden()
            and self.gstxt.is_hidden()
            and self.gswin.is_hidden()
        )

        self.tel_layout.set_hidden(telemetry_hidden)

        self.draw()

    def control_layout(self, args):
        items = args.hide or args.show or args.set
        hidden = args.hide

        self._set_visibility(items, hidden)

        if args.set:
            hidden_items = [i for i in InputParser.LAYOUT_OPTIONS if i not in args.set]
            self._set_visibility(hidden_items, True)


def handler(signum, frame):
    # Keep using regular exit, otherwise we mess up the terminal
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, handler)

    layout = [i for i in sys.argv[1:] if i in InputParser.LAYOUT_OPTIONS]
    cmd_helper = GdsHelper(layout or None)
    cmd_helper.start()
    # print(cmd_helper.layout.debug)
    # print(cmd_helper.layout._items[0].debug)
    # print(cmd_helper.layout._items[1].debug)
    # print(cmd_helper.debug)
    # print(cmd_helper.ackwin.debug)
    # print(cmd_helper.ackwin.errors)
    # print(cmd_helper.cmdwin.debug)

    if cmd_helper.respawn:
        print("\nRespawning gds_helper.py, let's find a new master to serve...\n")
        os.execv(os.path.basename(__file__), sys.argv)
    os._exit(0)
