import time
import curses
import threading
import queue
from configparser import ConfigParser, NoOptionError
import serial
import sys
import argparse
import logging
import signal

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

class Device(object):
    def __init__(self, config):
        self.config = config
        self.exception_handlers = []
        self.enabled = False

    def registerExceptionHandler(self, func):
        self.exception_handlers.append(func)

    def defaultExceptionHandler(self, e):
        sys.exit('{}'.format(e))

    def handleException(self, e):
        if len(self.exception_handlers) == 0:
            self.defaultExceptionHandler(e)
        else:
            for handler in self.exception_handlers:
                handler(e)

    def setup(self):
        pass

    def close(self):
        pass

    def writeBytes(self, bytes):
        pass

    def writeByte(self, byte):
        pass

    def readBytes(self, num):
        pass

    def readByte(self):
        pass

    def cancelRead(self):
        pass

class SerialDevice(Device):
    def setup(self):
        super(SerialDevice, self).setup()

        self.serial = None

        if 'url' in self.config:
            try:
                self.serial = serial.serial_for_url(self.config['url'], do_not_open=True)
                
                if not hasattr(self.serial, 'cancel_read'):
                    self.serial.timeout = 1

                self.serial.open()
                self.enabled = True
            except serial.SerialException as e:
                self.enabled = False
                self.handleException(e)
        else:
            try:
                self.serial = serial.serial_for_url(
                    self.config['port'],
                    self.config['baud'],
                    parity=self.config['parity'],
                    rtscts=self.config['rtscts_flowcontrol'],
                    xonxoff=self.config['xonxoff_flowcontrol'],
                    do_not_open=True)

                if not hasattr(self.serial, 'cancel_read'):
                    self.serial.timeout = 1

                if isinstance(self.serial, serial.Serial):
                    self.serial.exclusive = self.config['exclusive']

                self.serial.dtr = self.config['initial_dtr']
                self.serial.rts = self.config['initial_rts']

                self.serial.open()
                self.enabled = True
            except serial.SerialException as e:
                self.enabled = False
                self.handleException(e)

    def close(self):
        try:
            if self.serial is not None and not self.serial.closed:
                self.serial.close()
        except serial.SerialException as e:
            self.handleException(e)

    def writeBytes(self, bytes):
        try:
            self.serial.write(bytes)
        except serial.SerialException as e:
            self.handleException(e)
    
    def writeByte(self, byte):
        self.writeBytes(byte.to_bytes(1, 'little'))

    def readBytes(self, num):
        if self.enabled:
            try:
                return self.serial.read(num)
            except serial.SerialException as e:
                self.enabled = False
                self.handleException(e)
    
    def readByte(self):
        bytes = self.readBytes(1)
        if bytes is None or len(bytes) == 0:
            return -1
        return int.from_bytes(bytes, 'little')

    def cancelRead(self):
        if self.enabled:
            try:
                if hasattr(self.serial, 'cancel_read'):
                    self.serial.cancel_read()        
            except serial.SerialException as e:
                self.enabled = False
                self.handleException(e)

class CenturionTerm(object):
    CMD_FLUSH = -2
    CMD_QUIT = -255

    OSTATE_NORMAL = 0
    OSTATE_ESCAPE = 10
    OSTATE_CUR_ABS_1 = 20
    OSTATE_CUR_ABS_2 = 30
    OSTATE_CUS_HORZ = 40
    OSTATE_CUR_VERT = 50
    OSTATE_DATA_CHAR = 60

    def __init__(self, config, device):
        self.config = config
        self.device = device
        self.device.registerExceptionHandler(self.deviceExceptionHandler)
        self._console_alive = False
        self.out_q = queue.Queue()
        self.scr = None
        self.input_enabled = False
        # self.main_win = None
        # self.status_win = None
        signal.signal(signal.SIGINT, self.signal_handler_SIGINT)

    def signal_handler_SIGINT(self, sig, frame):
        # logging.debug("Ctrl-C SIGINT")
        curses.ungetch(0x03)

    def deviceExceptionHandler(self, e):
        msg = "Communication Error: {}".format(str(e))
        logging.warning(msg)
        self.input_enabled = False
        curses.halfdelay(1)
        if self.scr:
            self.scroll()
            self.scroll()
            self.scroll()
            self.scr.addstr(21,0, msg, curses.A_BOLD)
            self.scr.addstr(23,0, "[Press ENTER to exit]", curses.A_BOLD)
            self.scr.refresh()
            curses.nocbreak()
            self.scr.getch()
            self.stop()
        else:
            sys.exit(msg)

    def start(self):
        self._console_alive = True

        self.thread = threading.Thread(target=self.console_thread, name='centurionterm')
        self.thread.daemon = True
        self.thread.start()

        self.input_thread = threading.Thread(target=self.do_input, name='centurionterm_input')
        self.input_thread.daemon = True
        self.input_thread.start()

        self.input_enabled = True

    def join(self):
        self.input_thread.join()
        self.thread.join()

    def stop(self):
        self._console_alive = False
        self.device.cancelRead()

    def logyx(self, func, msg=""):
        y, x = self.scr.getyx()
        logging.debug("{}: ({},{}) {}".format(func, y, x, msg))

    def scroll(self):
        # self.logyx("scroll", "Begin")
        save_y, save_x = self.scr.getyx()
        
        for y in range(1, 24):
            # self.scr.move(y-1, 0)
            for x in range(80):
                ch = self.scr.inch(y, x)
                self.scr.addch(y-1, x, ch & 0xFF, ch & 0xFFFFFF00)

        self.scr.move(23, 0)
        self.scr.clrtoeol()
        self.scr.move(save_y, save_x)

        self.scr.redrawwin()
        self.scr.refresh()

    def addch(self, ch, attr=0):
        # self.logyx("addch", "Begin ch={}".format(ch))
        y, x = self.scr.getyx()
        if y == 23 and x == 79:
            if self.config['auto_scroll']:
                self.moveCursorForward()
                self.scr.addch(22, 79, ch, attr)
            else:
                self.scr.addch(23, 79, ch, attr)
            self.scr.move(23, 0)
            self.scr.refresh()
        else:
            self.scr.addch(y, x, ch, attr)
            self.scr.move(y, x)
            self.moveCursorForward()

    def moveCursorBack(self):
        # self.logyx("moveCursorBack", "Begin")
        y, x = self.scr.getyx()
        if x == 0 and y == 0:
            self.scr.move(23, 79)
        elif x == 0:
            self.scr.move(y-1, 79)
        else:
            self.scr.move(y, x-1)
        self.scr.refresh()

    def moveCursorDown(self):
        # self.logyx("moveCursorDown", "Begin")
        y, x = self.scr.getyx()
        # eprint("y="+str(y)+", x="+str(x))
        if y >= 23:
            if self.config['auto_scroll']:
                self.scroll()
                self.scr.move(23, x)
            else:
                self.scr.move(0, x)
        else:
            self.scr.move(y+1, x)
        self.scr.refresh()

    def moveCursorForward(self):
        # self.logyx("moveCursorForward", "Begin")
        y, x = self.scr.getyx()
        if x >= 79:
            if y >= 23:
                # I'm unsure what the actual terminal does
                # here and the manual isn't clear
                if self.config['auto_scroll']:
                    self.scroll()
                self.scr.move(23, 0)
            else:
                self.scr.move(y+1, 0)
        else:
            self.scr.move(y, x+1)
        self.scr.refresh()

    def moveCursorHome(self):
        if self.config['auto_scroll']:
            self.scr.move(23, 0) # Lower Left
        else:
            self.scr.move(0, 0) # Upper Left
        self.scr.refresh()

    def moveCursorUp(self):
        # self.logyx("moveCursorUp", "Begin")
        y, x = self.scr.getyx()
        if y == 0:
            self.scr.move(23, x)
        else:
            self.scr.move(y-1, x)
        self.scr.refresh()

    def moveCursor(self, y, x):
        # self.logyx("moveCursor", "Begin to ({},{})".format(y,x))
        if y < 24 and x < 80:
            self.scr.move(y, x)
            self.scr.refresh()

    def moveCursorHorz(self, a):
        y, _ = self.scr.getyx()
        a = a & 0x7F
        group = a >> 4
        pos = a & 0xF
        if pos < 10:
            self.scr.move(y, group * 10 + pos)
            self.scr.refresh()

    def moveCursorVert(self, a):
        _, x = self.scr.getyx()
        a = a & 0x1F
        if a < 24:
            self.scr.move(a, x)
            self.scr.refresh()

    def eraseAll(self):
        self.scr.clear()
        self.scr.refresh()

    def moveCursorLineStart(self):
        y, x = self.scr.getyx()
        self.scr.move(y, 0)
        self.scr.refresh()

    def newLine(self):
        pass

    def eraseEndOfLine(self):
        self.scr.clrtoeol()
        self.scr.refresh()

    def eraseEndOfPage(self):
        self.scr.clrtobot()
        self.scr.refresh()

    def translate_output(self, ch):
        outch = None
        attr = 0

        if self.oState == self.OSTATE_NORMAL:
            if ch == 0x1B: # ESC
                self.oState = self.OSTATE_ESCAPE
            elif ch == 0x10: # DLE, Cursor Move Horizontal
                self.oState = self.OSTATE_CUS_HORZ
            elif ch == 0x0B: # VT, Cursor Move Vertical
                self.oState = self.OSTATE_CUR_VERT
            elif ch == 0x07: # BEL, Audible Tone
                curses.beep()
            elif ch == 0x14: # DC4, AUX port OFF
                # TODO
                outch = ch
            elif ch == 0x12: # DC2, AUX port ON
                # TODO
                outch = ch
            elif ch == 0x08 or ch == 0x15: # BS, NAK, Backspace / Cursor Back
                self.moveCursorBack()
            elif ch == 0x0A: # LF, Cursor Down
                self.moveCursorDown()
            elif ch == 0x06: # ACK, Cursor Forward
                self.moveCursorForward()
            elif ch == 0x01: # SOA, Cursor Home
                self.moveCursorHome()
            elif ch == 0x1A: # SUB, Cursor Up
                self.moveCursorUp()
            elif ch == 0x0C: # FF, Erase All
                self.eraseAll()
            elif ch == 0x0D: # CR, Carriage Return
                self.moveCursorLineStart()
            elif ch == 0x04: # EOT, Keyboard Lock (only when the keyboard lock option is enabled)
                # TODO
                pass
            elif ch == 0x02: # STX, Keyboard Unlock (only when the keyboard lock option is enabled)
                # TODO
                pass
            elif ch == 0x7F: # DEL
                #outch = 0x2593 #  ▓ Dark Shade
                self.scr.addstr(" \x08")
                self.scr.refresh()
            elif ch == 0x00:
                outch = 0xB7 # · Middle Dot
            elif ch >= 32 and ch < 127:
                outch = ch
            elif ch < 32:
                attr = curses.A_STANDOUT
                outch = ch + 64

        elif self.oState == self.OSTATE_ESCAPE:
            if ch == 0x59: # 'Y', Cursor Move Absolute
                self.escape_args = []
                self.oState = self.OSTATE_CUR_ABS_1
            elif ch == 0x4B: # 'K', Erase to End of Line
                self.eraseEndOfLine()
                self.oState = self.OSTATE_NORMAL
            elif ch == 0x6B: # 'k', Erase to End of Page
                self.eraseEndOfPage()
                self.oState = self.OSTATE_NORMAL
            elif ch == 0x35: # '5', Keyboard Lock (only when the keyboard lock option is disabled)
                # TODO
                self.oState = self.OSTATE_NORMAL
            elif ch == 0x36: # '6', Keyboard Unlock (only when the keyboard lock option is disabled)
                # TODO
                self.oState = self.OSTATE_NORMAL
            elif ch == 0x5A: # 'Z', Store Control Character
                # This command causes the characters which follow the command code
                # to be considered as a data character and not acted upon by the
                # terminal, regardles of its location on the ASCII chart.
                self.oState = self.OSTATE_DATA_CHAR
            elif ch == 0x34: # '4', Transparent Print OFF
                # TODO
                self.oState = self.OSTATE_NORMAL
            elif ch == 0x33: # '3', Transparent Print ON
                # TODO
                self.oState = self.OSTATE_NORMAL
            else:
                self.oState = self.OSTATE_NORMAL
        elif self.oState == self.OSTATE_CUR_ABS_1:
            self.escape_args.append(ch)
            self.oState = self.OSTATE_CUR_ABS_2
        elif self.oState == self.OSTATE_CUR_ABS_2:
            self.escape_args.append(ch)
            self.moveCursor(self.escape_args[1], self.escape_args[0])
            self.oState = self.OSTATE_NORMAL
        elif self.oState == self.OSTATE_CUS_HORZ:
            self.moveCursorHorz(ch)
            self.oState = self.OSTATE_NORMAL
        elif self.oState == self.OSTATE_CUR_VERT:
            self.moveCursorVert(ch)
            self.oState = self.OSTATE_NORMAL
        elif self.oState == self.OSTATE_DATA_CHAR:
            if ch == 0:
                outch = 0xB7 # · Middle Dot
            elif ch < 32:
                attr = curses.A_STANDOUT
                outch = ch + 64
            elif ch == 127:
                outch = 0x2593 # ▓ Dark Shade
            else:
                outch = ch
            self.oState = self.OSTATE_NORMAL
        else:
            # Error Unknown State
            outch = ch
            self.oState = self.OSTATE_NORMAL
        
        if outch is not None:
            self.addch(chr(outch), attr)

    def do_output(self, scr):
        self.oState = self.OSTATE_NORMAL
        self.escape_args = []

        curses.raw()
        curses.resize_term(25, 80)
        curses.halfdelay(10)
        curses.start_color()
        #curses.nonl()
        #curses.use_default_colors()

        scr.clear()

        # curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_WHITE)

        # main_win = curses.newwin(24, 80, 0, 0)
        # status_win = curses.newwin(1, 80, 24, 0)

        # status_win.bkgd(' ', curses.color_pair(1))
        # main_win.clear()
        # status_win.clear()

        # status_win.addstr(" Centurian Term")

        # main_win.refresh()
        # status_win.refresh()

        # main_win.keypad(True)

        # self.main_win = main_win
        # self.status_win = status_win
        
        scr.keypad(True)
        scr.idlok(False)
        scr.scrollok(False)
        scr.setscrreg(0, 24)
        scr.resize(25, 80)
        self.scr = scr

        while self._console_alive:
            ch = self.device.readByte()

            # Try and echo characters if enabled
            try:
                while(True):
                    echo_ch = self.out_q.get_nowait()
                    self.translate_output(echo_ch)
            except queue.Empty:
                pass

            if ch >= 0:
                # print("[" + str(ch) + "]")
                self.translate_output(ch)

        self._console_alive = False

    def translate_input(self, ch):
        if ch == 0x0A:
            return [0x0D]
        elif ch >= 0 and ch <= 127:
            return [ch]
        elif ch == curses.KEY_DOWN:
            return [0x0A] # LF, Cursor Down          
        elif ch == curses.KEY_UP:
            return [0x1A] # SUB, Cursor Up
        elif ch == curses.KEY_LEFT:
            return [0x15] # NAK, Backspace / Cursor Back
        elif ch == curses.KEY_RIGHT:
            return [0x06] # ACK, Cursor Forward
        elif ch == curses.KEY_HOME:
            return [0x01] # SOA, Cursor Home
        elif ch == curses.KEY_CLEAR:
            return [0x0C] # FF, Erase All
        elif ch == curses.KEY_DC:
            return [0x7F] # DEL
        elif ch == curses.KEY_BACKSPACE:
            return [0x08] # BS
        elif ch == -1:
            pass
        elif ch == curses.KEY_F10:
            self.stop()

        return None

    def do_input(self):

        while self._console_alive:
            if self.scr is not None and self.input_enabled:
                try:
                    input = self.scr.getch()
                except curses.error:
                    continue
                
                # if input was disabled while in getch
                # put character back
                if not self.input_enabled: 
                    if input >= 0 and input <= 255:
                        curses.ungetch(input)
                    continue

                result = self.translate_input(input)

                if result is not None:
                    for ch in result:
                        if self.config['echo']:
                            self.out_q.put(ch)
                            self.device.cancelRead()
                        self.device.writeByte(ch)
            else:
                time.sleep(0.5)

    # def resize_handler(self, signum, frame):
    #     if self.main_win is not None:
    #         self.main_win.refresh()
    #     if self.status_win is not None:
    #         self.status_win.refresh()

    def console_thread(self):
        # signal(signal.SIGWINCH, self.resize_handler)
        curses.wrapper(self.do_output)
        self.scr = None


def configTruthyfy(s):
    if isinstance(s, str):
        s = s.strip().upper()
        return s == 'ON' or s == 'TRUE' or s == 'YES'
    elif isinstance(s, bool):
        return s
    else:
        return False

# Polyfill derived from Python 3.9's argparse.py
# https://github.com/python/cpython/blob/bcf14ae4336fced718c00edc34b9191c2b48525a/Lib/argparse.py#L865
class BooleanOptionalAction(argparse.Action):
    def __init__(self,
                 option_strings,
                 dest,
                 default=None,
                 type=None,
                 choices=None,
                 required=False,
                 help=None,
                 metavar=None):

        _option_strings = []
        for option_string in option_strings:
            _option_strings.append(option_string)

            if option_string.startswith('--'):
                option_string = '--no-' + option_string[2:]
                _option_strings.append(option_string)

        if help is not None and default is not None and default is not argparse.SUPPRESS:
            help += " (default: %(default)s)"

        super().__init__(
            option_strings=_option_strings,
            dest=dest,
            nargs=0,
            default=default,
            type=type,
            choices=choices,
            required=required,
            help=help,
            metavar=metavar)

    def __call__(self, parser, namespace, values, option_string=None):
        if option_string in self.option_strings:
            setattr(namespace, self.dest, not option_string.startswith('--no-'))

    def format_usage(self):
        return ' | '.join(self.option_strings)


def parseArguments():
    parser = argparse.ArgumentParser(
        description='CenturionTerm - A warriors terminal emulator')

    parser.add_argument(
        'url',
        nargs='?',
        type=str,
        help="connect using URL (https://pyserial.readthedocs.io/en/latest/url_handlers.html)"
    )

    parser.add_argument(
        '--config',
        type=str,
        help='ini config file',
        default="CenturionTerm.ini")

    parser.add_argument(
        '--no-config',
        action='store_true',
        help='disable config file',
        default=False)

    group = parser.add_argument_group('General settings')

    group.add_argument(
        '--normal-case-upper',
        action=BooleanOptionalAction,
        help='normal case is upper, shift for lower')

    group.add_argument(
        '--echo',
        action=BooleanOptionalAction,
        help='local echo / half-duplex')

    group.add_argument(
        '--keyboard-lock-compatability',
        action=BooleanOptionalAction,
        help='keyboard lock ADDS Consul 580 Compatability'
    )

    group.add_argument(
        '--auto-scroll',
        action=BooleanOptionalAction,
        help='auto scroll'
    )

    group = parser.add_argument_group('Serial settings')

    group.add_argument(
        '--port',
        nargs='?',
        type=str,
        help='serial device')

    group.add_argument(
        '--baud',
        nargs='?',
        type=int,
        help='set baud rate')

    group.add_argument(
        '--bits',
        nargs='?',
        type=str,
        help='set number of data bits (5 6 7 8)')

    group.add_argument(
        '--parity',
        choices=['N', 'E', 'O', 'S', 'M'],
        type=lambda c: c.upper(),
        help='set parity, one of {N E O S M}')

    group.add_argument(
        '--stopbits',
        nargs='?',
        type=str,
        help='set number of stop bits (1 2)')

    group.add_argument(
        '--rtscts-flowcontrol',
        action=BooleanOptionalAction,
        help='RTS/CTS flow control')

    group.add_argument(
        '--xonxoff-flowcontrol',
        action=BooleanOptionalAction,
        help='software flow control')

    group.add_argument(
        '--initial-rts',
        action=BooleanOptionalAction,
        help='set initial RTS line state')

    group.add_argument(
        '--initial-dtr',
        action=BooleanOptionalAction,
        help='set initial DTR line state')

    group.add_argument(
        '--exclusive',
        action=BooleanOptionalAction,
        help='locking for native ports')

    return vars(parser.parse_args())

def parseConfig(config_file):
    config = ConfigParser()

    if not config.read(config_file):
        sys.exit("Could not open config file '%s'" % config_file)

    return {s:dict(config.items(s)) for s in config.sections()}

def main():
    logging.info("CenturionTerm Starting ...")

    config_defaults = {
        'normal_case_upper': False, 
        'keyboard_lock_compatability': False, 
        'auto_scroll': True, 
        'echo': False, 
        'port': '/dev/ttyS0', 
        'baud': '9600', 
        'bits': '7', 
        'parity': 'M', 
        'stopbits': '1', 
        'xonxoff_flowcontrol': False, 
        'rtscts_flowcontrol': False, 
        'initial_dtr': False, 
        'initial_rts': False, 
        'exclusive': True, 
    }

    needs_truthyfying = [
        'normal_case_upper', 
        'keyboard_lock_compatability', 
        'auto_scroll', 
        'echo', 
        'xonxoff_flowcontrol', 
        'rtscts_flowcontrol', 
        'initial_dtr', 
        'initial_rts', 
        'exclusive',         
    ]

    args = parseArguments()

    for key, value in dict(args).items():
        if value is None:
            del args[key]

    # If the arguments include --no-config, skip parsing Config
    if 'no_config' not in args or args['no_config'] == False:
        c = parseConfig(args['config'])

        config = c['general']
        if 'serial' in c:
            config.update(c['serial'])

        config.update(args)
    else:
        config = config_defaults | args

    # Convert ON, OFF, etc to real booleans
    for key, value in dict(config).items():
        if key in needs_truthyfying:
            config[key] = configTruthyfy(value)

    # Check some values

    if 'url' not in config:
        # validate serial stuff
        
        if 'port' not in config:
            sys.exit("Undefined serial port; use --port on command line or serial->port in config file")

        if 'baud' not in config:
            sys.exit("Undefined serial baud rate; use --baud on command line or serial->baud in config file")

        try:
            config['baud'] = int(config['baud'])
        except ValueError:
            sys.exit("Baud rate must be an integer")

        if 'bits' not in config:
            sys.exit("Undefined serial data bits; use --bits on command line or serial->bits in config file")

        if config['bits'] == '5':
            config['bits'] = serial.FIVEBITS
        elif config['bits'] == '6':
            config['bits'] = serial.SIXBITS
        elif config['bits'] == '7':
            config['bits'] = serial.SEVENBITS
        elif config['bits'] == '8':
            config['bits'] = serial.EIGHTBITS
        else:
            sys.exit("Unknown serial data bits; --bits on command line or serial->bits in config file needs to be set to 5, 6, 7 or 8")

        if 'parity' not in config:
            sys.exit("Undefined serial parity; use --parity on command line or serial->parity in config file")

        if config['parity'] == 'N':
            config['parity'] = serial.PARITY_NONE
        elif config['parity'] == 'E':
            config['parity'] = serial.PARITY_EVEN
        elif config['parity'] == 'O':
            config['parity'] = serial.PARITY_ODD
        elif config['parity'] == 'M':
            config['parity'] = serial.PARITY_MARK
        elif config['parity'] == 'S':
            config['parity'] = serial.PARITY_SPACE
        else:
            sys.exit("Unknown serial parity; --parity in command line or serial->parity in config file needs to be set to N, E, O, M or S")

        if 'stopbits' not in config:
            sys.exit("Undefined serial stop bits; use --stopbits on command line or serial->stopbits in config file")

        if config['stopbits'] == '1':
            config['stopbits'] = serial.STOPBITS_ONE
        elif config['stopbits'] == '2':
            config['stopbits'] = serial.STOPBITS_TWO
        else:
            sys.exit("Unknown serial stop bits; --stopbits on command line or serial->stopbits in config file needs to be set to 1 or 2")

    # print("Final ---")
    # print(config)

    device = SerialDevice(config)
    device.setup()

    term = CenturionTerm(config, device)
    term.start()

    try:
        term.join()
    except KeyboardInterrupt:
        pass  
    finally:
        curses.echo()
        curses.nocbreak()
        curses.endwin() 

    term.stop()
    device.close()

    logging.info("CenturionTerm Exit")


if __name__ == '__main__':
    logging.basicConfig(filename='CenturionTerm.log', encoding='utf-8', level=logging.DEBUG)
    main()

