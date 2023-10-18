#!/usr/bin/env python

""" A very basic curses widget toolkit """

from __future__ import division

import curses
import datetime
import math
import sys
import textwrap
import time
from collections import OrderedDict

# from utils import round_down
from util.utils import round_down

TERM_SEQ_TO_CURSES_ATTRIB = {
    "[01": curses.A_BOLD,
    "[05": curses.A_BLINK,
    "[07": curses.A_REVERSE,
}


class Screen(object):
    """A representation of a curses terminal screen"""

    def __init__(self, exit_key=curses.KEY_F10, use_default_colors=True):
        self.exit_key = exit_key
        self._use_default_colors = use_default_colors
        # The curses screen object
        self.scr = None
        # Window size variables
        self.width = 0
        self.height = 0
        # Container layout to draw on screen
        self.layout = None
        # Storage for stuff to print at exit, after curses releases the terminal
        self.debug = {}
        # Variable that can be used to simulate key input to this program
        self._input = None

    def start(self):
        """Entry point. Call this from your implementation to start"""
        curses.wrapper(self._run)

    def on_start(self):
        """This will be called before the main loop is started"""
        pass

    def do_background(self):
        """Main loop background callback. Override in your implementation"""
        pass

    def handle_input(self, input):
        """Main loop input callback. Override in your implementation"""
        pass

    def exit_callback(self):
        """Main loop exit callback. Override if needed"""
        pass

    def resize_callback(self):
        """Default behavior for a resize callback event"""
        h, w = self.scr.getmaxyx()
        if (h, w) != (self.height, self.width):
            self.scr.clear()
            curses.resizeterm(h, w)
            self.height, self.width = self.scr.getmaxyx()
            self.draw()

    def move_cursor(self, x, y):
        try:
            self.scr.move(y, x)
            return True
        except curses.error:
            return False

    def is_term_resized(self):
        return self.scr.getmaxyx() != (self.height, self.width)

    def set_layout(self, layout):
        self.layout = layout

    def draw(self):
        if self.layout is None:
            return False
        self.layout.draw(self.scr, 0, 0, self.width, self.height)
        return True

    def _run(self, scr):
        """This gets called from the curses wrapper"""
        self.scr = scr
        # Use terminal colors if requested
        if self._use_default_colors:
            curses.use_default_colors()
        # This controls how long will handle_input wait before do_background
        # takes over
        # Increase to consume less resources but will refresh at a slower rate
        self.scr.timeout(300)
        # Get current size of the terminal
        self.height, self.width = self.scr.getmaxyx()
        # Run extra user defined code
        self.on_start()
        # Start the looper for handle_input and do_background
        self._loop()

    def _loop(self):
        """Loops over handle_input and do_background"""
        self._input = curses.ERR
        while self._input != self.exit_key:
            self._input = self.scr.getch()
            if self._input == curses.ERR:  # No input after timeout
                # Hide cursor while we do background work
                curses.curs_set(0)
                self.do_background()
                curses.curs_set(1)
            elif self._input == curses.KEY_RESIZE:
                # Hide cursor while we resize terminal
                curses.curs_set(0)
                self.resize_callback()
                # Do background will show the cursor in the next iterarion
            else:
                self.handle_input(self._input)
        self.exit_callback()


class LayoutProperties(object):
    PERCENTAGE = 1
    ABSOLUTE = 2

    def __init__(self, hidden=False):
        self.hidden = hidden


class LinearLayoutProperties(LayoutProperties):
    def __init__(self, size, unit_type=LayoutProperties.ABSOLUTE, hidden=False):
        LayoutProperties.__init__(self, hidden)
        # Size can be given in characteres or percentage (0-1 float)
        self.size = size
        # Defines if the size is based on characteres or percentage
        self.unit_type = unit_type
        # If the size is percentage, the actual size in characteres will be here
        # Otherwise it just copies it over
        self._actual_size = 0
        # Since this is a lineat layout, on of this will be calculated from parent
        self._height = 0
        self._width = 0

    def _calculate_actual_size(self, reference_size):
        if self.unit_type == LayoutProperties.PERCENTAGE:
            # Size will be a percentage of the reference size in characteres
            self._actual_size = int(round_down(reference_size * self.size))
        elif self.unit_type == LayoutProperties.ABSOLUTE:
            self._actual_size = self.size
        else:
            return False
        return True


class View(object):
    def __init__(self):
        # Position of the top left corner of this view in reference to screen
        self.pos_x = self.pos_y = 0
        # A reference to the curses screen object
        self.scr = None
        # Properties to define how to draw this view
        self.layout_properties = None
        # A debug array to print later
        self.debug = {}
        self.errors = []

    def is_hidden(self):
        return self.layout_properties.hidden

    def set_hidden(self, hidden=True):
        self.layout_properties.hidden = hidden


class LinearLayout(View):
    # Available directions
    VERTICAL = 1
    HORIZONTAL = 2

    def __init__(self, direction, properties=None):
        View.__init__(self)
        # By default we assume no parent, this will change if this object is
        # added to another layout using the add() function
        self.parent = None
        self.direction = direction
        self.layout_properties = properties
        # Maximum space where layout can expand, it will be set in _draw()
        self.max_height = self.max_width = 0
        # This will hold the views inside
        self._items = []
        # Debugging # TODO Remove?
        self.debug = {}
        self.debug["list"] = []

    # Add items to this layout, they need to have layout_properties set
    def add(self, item):
        if item.layout_properties is None or not isinstance(
            item.layout_properties, LinearLayoutProperties
        ):
            return False
        item.parent = self
        self._items.append(item)
        return True

    # Calculates and sets height and width based on available space and direction
    def _set_dimentions(self):
        skip_size_calculation = False
        if self.layout_properties is None:
            # If properties is not provided, create default with max size
            self.layout_properties = LinearLayoutProperties(
                1, LayoutProperties.PERCENTAGE
            )

        if self.parent is None:
            # if layout is root use its own direction to calculate size
            direction = self.direction
        else:
            # If the layout is a child of another use parent direction to
            # set dimentions. Don't calculate size because the parent layout
            # already did
            skip_size_calculation = True
            direction = self.parent.direction

        # Calculate size using max values and layout properties
        p = self.layout_properties
        if direction == LinearLayout.VERTICAL:
            if skip_size_calculation:
                p._height = p._actual_size = self.max_height
            else:
                if not p._calculate_actual_size(self.max_height):
                    return False
                p._height = p._actual_size
            p._width = self.max_width
        elif direction == LinearLayout.HORIZONTAL:
            if skip_size_calculation:
                p._width = p._actual_size = self.max_width
            else:
                if not p._calculate_actual_size(self.max_width):
                    return False
                p._width = p._actual_size
            p._height = self.max_height
        else:
            return False
        return True

    def _calculate_items_size(self):
        self._set_dimentions()
        # TODO Check if this makes sense, should we leave max values as given by draw?
        self.max_height, self.max_width = (
            self.layout_properties._height,
            self.layout_properties._width,
        )
        # Separate items with absolute size from percentage size
        absolutes = [
            i.layout_properties
            for i in self._items
            if i.layout_properties.unit_type == LayoutProperties.ABSOLUTE
            and not i.layout_properties.hidden
        ]
        percentage = [
            i.layout_properties
            for i in self._items
            if i.layout_properties.unit_type == LayoutProperties.PERCENTAGE
            and not i.layout_properties.hidden
        ]

        if self.direction == LinearLayout.VERTICAL:
            available = self.max_height
            for i in absolutes:
                i._actual_size = i._height = i.size
                i._width = self.max_width
                available -= i._actual_size

            # Get the size of the percentage dimention items
            # (they will use the remaining space)
            available_after_abs = available
            for i in percentage:
                i._actual_size = i._height = int(
                    round_down(available_after_abs * i.size)
                )
                i._width = self.max_width
                available -= i._actual_size
            # Last one takes any remaining space
            if percentage:
                percentage[-1]._actual_size += available
                percentage[-1]._height += available

        elif self.direction == LinearLayout.HORIZONTAL:
            available = self.max_width
            for i in absolutes:
                i._actual_size = i._width = i.size
                i._height = self.max_height
                available -= i._actual_size

            # Get the size of the percentage dimention items
            # (they will use the remaining space)
            available_after_abs = available
            for i in percentage:
                i._actual_size = i._width = int(
                    round_down(available_after_abs * i.size)
                )
                i._height = self.max_height
                available -= i._actual_size
            # Last one takes any remaining space
            if percentage:
                percentage[-1]._actual_size += available
                percentage[-1]._width += available
        else:
            return False
        return True

    def draw(self, scr, pos_x, pos_y, width, height):
        self.scr = scr
        self.pos_x = pos_x
        self.pos_y = pos_y
        self.max_width = width
        self.max_height = height
        self._calculate_items_size()

        added_pos_x = self.pos_x
        added_pos_y = self.pos_y
        for i in self._items:
            p = i.layout_properties
            if p.hidden:
                continue

            if self.direction == LinearLayout.VERTICAL:
                i.draw(self.scr, self.pos_x, added_pos_y, p._width, p._height)
                added_pos_y += p._actual_size
            elif self.direction == LinearLayout.HORIZONTAL:
                i.draw(self.scr, added_pos_x, self.pos_y, p._width, p._height)
                added_pos_x += p._actual_size
        curses.doupdate()


class Window(View):
    def __init__(self, padding=1, border=True):
        View.__init__(self)
        # Should we draw a border?
        self.border = border
        # The window object that will contain the edit window plus the border
        self.border_window = None
        # The window where text can be shown
        self.window = None
        # Padding in character spaces
        self.padding = padding
        # The current position of the cursor relative to the edit window
        self.curr_x = 0
        self.curr_y = 0
        # Total size of the window or max pad buffer
        self.width = self.height = 0
        # Size of the window where we can add text
        self.edit_width = self.edit_height = 0

    def draw_border(self):
        if self.border_window is None:
            # Create border window with full given size and position
            self.border_window = curses.newwin(
                self.height, self.width, self.pos_y, self.pos_x
            )
        else:
            # Resize and reposition
            self.border_window.resize(self.height, self.width)
            self.border_window.mvwin(self.pos_y, self.pos_x)
            self.border_window.clear()

        if self.border:
            self.border_window.border(0)  # Draw a border if asked to
        self._noutrefresh_border()

    def draw(self, scr, pos_x, pos_y, width, height):
        self.scr = scr
        self.width = width
        self.height = height
        self.pos_x = pos_x
        self.pos_y = pos_y
        self._calculate_edit_size()

        self.draw_border()
        if self.window is None:
            # Create window
            self.window = curses.newwin(
                self.edit_height,
                self.edit_width,
                self.pos_y + self.padding,
                self.pos_x + self.padding,
            )
        else:
            # Resize and reposition
            self.window.resize(self.edit_height, self.edit_width)
            self.window.mvwin(self.pos_y + self.padding, self.pos_x + self.padding)

        self._noutrefresh_border()
        self._noutrefresh_window()

    def refresh(self):
        self._noutrefresh_window()
        curses.doupdate()

    def add_err(self, name, description):
        id = str(time.time())
        self.errors.append({"id": id, "name": name, "description": description})

    def update_xy(self):
        self.curr_y, self.curr_x = self.window.getyx()

    def _noutrefresh_window(self):
        self.window.noutrefresh()
        self.update_xy()

    def _noutrefresh_border(self):
        self.scr.noutrefresh()
        self.border_window.noutrefresh()

    def _calculate_edit_size(self):
        self.edit_width = self.width - self.padding * 2
        self.edit_height = self.height - self.padding * 2

    def _move_cursor(self, x, y, refresh=False):
        try:
            self.window.move(y, x)
            self.update_xy()
        except:
            return False

        self._noutrefresh_window()
        if refresh:
            curses.doupdate()
        return True


class Label(Window):
    def __init__(self, text, padding=0, border=False, attributes=0):
        Window.__init__(self, padding, border)
        self._text = text
        self._attributes = attributes

    def draw(self, scr, pos_x, pos_y, width, height):
        try:
            Window.draw(self, scr, pos_x, pos_y, width, height)
        except:
            # Failed to draw container windows, most likely terminal too small
            # Let's ignore so we can recover when terminal is resized again
            pass
        else:
            self._draw_text(refresh=False)

    def set_text(self, text):
        self._text = text
        self._draw_text()

    def _draw_text(self, refresh=True):
        if self.layout_properties.hidden:
            return

        self.window.erase()
        try:
            if len(self._text) > self.edit_width:
                # Indicate we can't show all text
                self.window.addstr(
                    self._text[: self.edit_width - 3] + "...", self._attributes
                )
            else:
                self.window.addstr(self._text, self._attributes)
        except:
            # Can't draw text, most likely term is smaller than 3 spaces
            pass

        self._noutrefresh_window()
        if refresh:
            curses.doupdate()


class TextView(Window):
    def __init__(self, padding=1, border=True, start_on_tail=False, keep_on_tail=False):
        Window.__init__(self, padding, border)
        self.top_line = 0
        self._buffer = []
        self._buffer_len = 0
        self._wrap_info = {}
        self._start_on_tail = start_on_tail
        self._keep_on_tail = keep_on_tail

    def draw(self, scr, pos_x, pos_y, width, height):
        try:
            Window.draw(self, scr, pos_x, pos_y, width, height)
        except:
            # Failed to draw container windows, most likely terminal too small
            # Let's ignore so we can recover when terminal is resized again
            pass
        else:
            if self._buffer_len - 1 in self._wrap_info:
                # User was looking at the last line, let's keep it that way
                self._reverse_draw_text(refresh=False)
            else:
                # User was looking somewhere else, keep same top line
                self._draw_text(refresh=False)

    def handle_input(self, input):
        if input == curses.KEY_UP:
            self._scroll_up()
        elif input == curses.KEY_DOWN:
            self._scroll_down()
        else:
            return False
        return True

    def set_text(self, text):
        self._buffer = []
        self._buffer_len = 0
        self.add_text(text)

    def add_text(self, text):
        # Replace tabs with spaces and break into lines
        text = text.replace("\t", " " * 4).split("\n")
        # Save last line index currently on buffer
        last_buff_line = self._buffer_len - 1
        # Add lines to buffer
        self._buffer += text
        self._buffer_len = len(self._buffer)
        if last_buff_line == -1:
            # Buffer is empty
            if self._start_on_tail:
                # User requested to show buffer tail the first time
                self._reverse_draw_text()
            else:
                self._draw_text()
        elif self._keep_on_tail or last_buff_line in self._wrap_info:
            # Last buffer line was on display, draw new stuff
            self._reverse_draw_text()

    def _scroll_down(self):
        if not self._buffer_len - 1 in self._wrap_info:
            # Last buffer line still not visible, scroll down
            self.top_line += 1
            self._draw_text()

    def _scroll_up(self):
        if self.top_line > 0:
            self.top_line -= 1
            self._draw_text()

    def _draw_text(self, refresh=True):
        if self.layout_properties.hidden:
            return

        self.window.erase()
        self._wrap_info.clear()
        for idx, line in enumerate(self._buffer[self.top_line :]):
            try:
                # Handle terminal styles
                chunks = line.split("\033")
                self.window.addstr(chunks[0], 0)
                for chunk in chunks[1:]:
                    attribute = chunk.split("m")[0]
                    chunk = chunk[len(attribute) + 1 :]
                    # Add line, wrap as needed
                    self.window.addstr(
                        chunk, TERM_SEQ_TO_CURSES_ATTRIB.get(attribute, 0)
                    )
                # Get cursor position after adding line
                self.update_xy()
                # Save last display line index for this buffer line
                self._wrap_info[self.top_line + idx] = self.curr_y
                # Jump to next line, cursor is already at the end of current
                if not self._move_cursor(0, self.curr_y + 1):
                    # Can't move to next line, end of window
                    break
            except:
                # Failed to draw line, line does not fit
                break
        self._move_cursor(0, self.edit_height - 1)
        self._noutrefresh_window()
        if refresh:
            curses.doupdate()

    def _reverse_draw_text(self, refresh=True):
        lines_needed = idx = 0
        for idx, line in enumerate(reversed(self._buffer)):
            lines_needed += math.ceil((len(line) + 1) / self.edit_width) if line else 1
            if lines_needed > self.edit_height:
                self.top_line = self._buffer_len - idx
                break
        else:
            self.top_line = 0
        self._draw_text(refresh)


class CommandTextBox(Window):
    def __init__(self, submit_callback, padding=1, border=True):
        Window.__init__(self, padding, border)
        self._submit_callback = submit_callback
        self._buffer = []
        self._top_char = 0
        self._cursor_pointer = 0
        self._command_history = []
        self._command_history_len = 0
        self._command_pointer = 0
        # Command that the user hasn't submited yet but may later
        self._volatile_input = ""

    def draw(self, scr, pos_x, pos_y, width, height):
        try:
            Window.draw(self, scr, pos_x, pos_y, width, height)
        except:
            # Failed to draw container windows, most likely terminal too small
            # Let's ignore so we can recover when terminal is resized again
            pass
        else:
            self._draw_and_move(refresh=False)

    def handle_input(self, input):
        # Buffer modification
        if input >= 32 and input <= 126:  # Char entry
            self._add_char(input)
        elif input == curses.KEY_DC:
            self._delete_char()
        elif input == curses.KEY_BACKSPACE:
            self._backspace_char()
        # Buffer navigation
        elif input == curses.KEY_LEFT:
            self._prev()
        elif input == curses.KEY_RIGHT:
            self._next()
        elif input == curses.KEY_HOME:
            self._cursor_pointer = self._top_char = 0
            self._draw_and_move()
        elif input == curses.KEY_END:
            self._show_line_end()
        # History navogation
        elif input == curses.KEY_UP:
            self._show_prev_cmd()
        elif input == curses.KEY_DOWN:
            self._show_next_cmd()
        # Command submission
        elif input == 13 or input == 10:  # Enter
            self._submit()
        else:
            return False
        return True

    def get_text(self):
        return "".join(self._buffer)

    def set_text(self, text):
        self._buffer = list(text)
        self._cursor_pointer = self._top_char = 0
        self._draw_and_move()

    def _next(self):
        if self._cursor_pointer < len(self._buffer):
            self._cursor_pointer += 1
            if self._cursor_pointer >= self._top_char + self.edit_width:
                self._top_char += 1
            self._draw_and_move()

    def _prev(self):
        if self._cursor_pointer > 0:
            self._cursor_pointer -= 1
            if self._cursor_pointer < self._top_char:
                self._top_char -= 1
            self._draw_and_move()

    def _add_char(self, input):
        self._buffer.insert(self._cursor_pointer, chr(input))
        self._next()

    def _backspace_char(self):
        if self._buffer:
            self._buffer.pop(self._cursor_pointer - 1)
            if self._top_char > 0:
                # If start of line is not visible, keep cursor where it is on
                # display (scroll instead) so user can see what is deleting
                self._top_char -= 1
            self._prev()

    def _delete_char(self):
        try:
            self._buffer.pop(self._cursor_pointer)
            self._draw_and_move()
        except IndexError:
            # Nothing to remove
            pass

    def _submit(self):
        curr_text = self.get_text().strip()
        if curr_text:
            self._command_history.append(curr_text)
            self._command_history_len = len(self._command_history)
            self._command_pointer = self._command_history_len
        self.set_text("")
        if callable(self._submit_callback):
            self._submit_callback(curr_text)
        self._show_line_end()

    def _show_next_cmd(self):
        try:
            if self._command_pointer < self._command_history_len:
                self._command_pointer += 1
                self.set_text(self._command_history[self._command_pointer])
                self._show_line_end()
        except IndexError:
            # End of history, show command the user was working on
            self.set_text(self._volatile_input)
            self._show_line_end()

    def _show_prev_cmd(self):
        if self._command_pointer > 0:
            if self._command_pointer == self._command_history_len:
                # User was typing a command, save for later
                self._volatile_input = self.get_text()
            self._command_pointer -= 1
            self.set_text(self._command_history[self._command_pointer])
            self._show_line_end()

    def _show_line_end(self):
        self._cursor_pointer = len(self._buffer)
        self._top_char = max(0, self._cursor_pointer - self.edit_width + 1)
        self._draw_and_move()

    def _draw_and_move(self, refresh=True):
        self._draw_text(refresh=False)
        self._move_cursor(self._cursor_pointer - self._top_char, self.curr_y)
        if refresh:
            self.refresh()

    def _draw_text(self, refresh=True):
        self.window.erase()
        try:
            self.window.addnstr(
                "".join(self._buffer[self._top_char :]), self.edit_width - 1
            )
        except curses.error:
            pass
        self._noutrefresh_window()
        if refresh:
            curses.doupdate()


class MenuItem(object):
    def __init__(self, label, callback=lambda: False, hover_callback=lambda: False):
        self._context = None
        self._label = label
        self._submenu = None
        self._parent = None
        self._callback = callback
        self._hover_callback = hover_callback

    def add_submenu(self, name, label, hover_callback=lambda: False):
        submenu = MenuView(label, hover_callback)
        submenu._parent = self._parent
        submenu._name = name
        submenu._items.insert(
            0, MenuItem("Back", self._context._back, self._context._back_hover)
        )
        self._submenu = submenu
        return self._submenu


class MenuView(object):
    def __init__(self, title, hover_title_callback=lambda: False):
        self._name = None
        self._title = MenuItem(title, hover_callback=hover_title_callback)
        self._items = []
        self._parent = None

    def add_item(self, item, callback=lambda: False, hover_callback=lambda: False):
        if not isinstance(item, MenuItem):
            item = MenuItem(item, callback, hover_callback)
        item._parent = self
        self._items.append(item)
        return item

    def set_title(self, title_str, hover_callback=lambda: False):
        self._title._label = title_str
        self._title._hover_callback = hover_callback

    def clear_items(self):
        self._items = []

    def find_menu(self, name):
        for i in self._items:
            if not i._submenu:
                continue
            if i._submenu._name == name:
                return i._submenu
            subm = i._submenu.find_menu(name)
            if subm:
                return subm
        return None


class Menu(Window, MenuView):
    HOVERED = curses.A_REVERSE | curses.A_BOLD

    def __init__(
        self, title="", hover_title_callback=lambda: False, padding=1, border=True
    ):
        Window.__init__(self, padding, border)
        MenuView.__init__(self, title, hover_title_callback)

        self._current_menu = self
        self._current_item = -1
        self._top_item = 0

        self._visible_items = []

    def handle_input(self, input):
        if self.layout_properties.hidden:
            return False

        if input == curses.KEY_UP:
            self._move_up()
        elif input == curses.KEY_DOWN:
            self._move_down()
        elif str(input).isdigit():
            selection = int(input) - 1
            if 0 <= selection < len(self._items):
                selected = self._current_menu._items[selection]
                if selected._submenu:
                    self._current_menu = selected._submenu
                    self._top_item = 0
                    self._current_item = -1
                    self._draw_items()
                selected._callback()
        else:
            return False
        return True

    def add_item(self, item, callback=lambda: False, hover_callback=lambda: False):
        item = MenuView.add_item(self, item, callback, hover_callback)
        item._context = self
        return item

    def set_current_menu(self, name):
        menu = self.find_menu(name)
        self._current_menu = menu or self

    def _back(self):
        self._current_menu = self._current_menu._parent
        # Show beginning of list
        self._top_item = 0
        # Focus on title
        self._current_item = -1
        self._draw_items()

    def _back_hover(self):
        pass

    def _move_up(self):
        if self._current_item - 1 >= 0:
            # There is a previous item, move focus to that
            # Scroll up until new item is visible
            top = self._top_item
            while self._current_item - 1 not in self._visible_items:
                if self._top_item <= 0:
                    # Top item hit beginning of list, current failed to draw
                    # Cancel move and restore top item
                    self._top_item = top
                    break
                # Top item still within range, keep scrolling
                self._top_item -= 1
                self._draw_items(refresh=False)
            else:
                # Scrolling completed successfully, item will be visible
                # Change focus to new item and run hover callback
                self._current_item -= 1
                self._run_hover_callback()

        else:
            # Current line is a negative number, move focus to title
            self._current_item = -1
            self._top_item = 0
            self._run_hover_callback()

        self._draw_items()

    def _move_down(self):
        if self._current_item + 1 < len(self._current_menu._items):
            # There is a next item, move focus to that
            # Scroll down until new item is visible
            top = self._top_item
            while self._current_item + 1 not in self._visible_items:
                if self._top_item >= len(self._current_menu._items):
                    # Top item hit end of list, current could not the drawn
                    # Restore original top item so we can recover later
                    self._top_item = top
                    break
                # Top item is still within range, keep scrolling
                self._top_item += 1
                self._draw_items(refresh=False)
            else:
                # Scrolling completed successfully, item will be visible
                # Change focus to new item run hover callback
                self._current_item += 1
                self._run_hover_callback()
            # Try and draw from top item, no matter if move was successful
            # This will restore the state if scrolling failed
            self._draw_items()

    def _run_hover_callback(self):
        if self._current_item < 0:
            self._current_menu._title._hover_callback()
        else:
            self._current_menu._items[self._current_item]._hover_callback()

    def draw(self, scr, pos_x, pos_y, width, height):
        try:
            Window.draw(self, scr, pos_x, pos_y, width, height)
        except:
            # Failed to draw container windows, most likely terminal too small
            # Let's ignore so we can recover when terminal is resized again
            pass
        else:
            self._draw_items(refresh=False)

    def _draw_items(self, refresh=True):
        if self.layout_properties.hidden:
            return

        self.window.erase()
        try:
            # Draw title
            attr = Menu.HOVERED if self._current_item == -1 else 0
            self.window.addstr(
                "{:^{}}".format(
                    self._current_menu._title._label, max(self.edit_width, 0)
                ),
                attr,
            )
            # Draw items
            self._visible_items = []
            for i, item in enumerate(self._current_menu._items):
                if i < self._top_item:
                    # Ignore items if won't be visible
                    continue

                attr = Menu.HOVERED if self._current_item == i else 0
                self.window.addstr(
                    "\n{:>2} {:<{}}".format(
                        i + 1, item._label, max(self.edit_width - 4, 0)
                    ),
                    attr,
                )

                self._visible_items.append(i)
        except curses.error:
            pass

        self._noutrefresh_window()
        if refresh:
            curses.doupdate()
