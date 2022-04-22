import time
import curses
import threading
import queue
from configparser import ConfigParser, NoOptionError
import serial
import sys
import argparse

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


class Device(object):
    def __init__(self, config):
        self.config = config

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
                self.serial.open()
            except serial.SerialException as e:
                eprint('Could not open url {!r}: {}'.format(self.config['url'], e))
                sys.exit(1)
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
            except serial.SerialException as e:
                eprint('Could not open port {!r}: {}'.format(self.config['port'], e))
                sys.exit(1)

    def close(self):
        if self.serial is not None and not self.serial.closed:
            self.serial.close()

    def writeBytes(self, bytes):
        self.serial.write(bytes)
    
    def writeByte(self, byte):
        self.writeBytes(byte.to_bytes(1, 'little'))

    def readBytes(self, num):
        return self.serial.read(num)
    
    def readByte(self):
        return int.from_bytes(self.readBytes(1), 'little')

    def cancelRead(self):
        if hasattr(self.serial, 'cancel_read'):
            self.serial.cancel_read()        

class CenturionTerm(object):
    CMD_FLUSH = -2
    CMD_QUIT = -255

    OSTATE_NORMAL = 0
    OSTATE_ESCAPE = 10
    OSTATE_CUR_ABS_1 = 20
    OSTATE_CUR_ABS_2 = 30
    OSTATE_CUS_HORZ = 40
    OSTATE_CUR_VERT = 50

    def __init__(self, config, device):
        self.config = config
        self.device = device
        self._console_alive = False
        self.in_q = queue.Queue()
        self.out_q = queue.Queue()
        self.scr = None
        # self.main_win = None
        # self.status_win = None

    def start(self):
        self._console_alive = True

        self.thread = threading.Thread(target=self.console_thread, name='centurionterm')
        self.thread.daemon = True
        self.thread.start()

        self.input_thread = threading.Thread(target=self.do_input, name='centurionterm_input')
        self.input_thread.daemon = True
        self.input_thread.start()

    def join(self):
        self.input_thread.join()
        self.thread.join()

    def stop(self):
        self._console_alive = False
        self.device.cancelRead()

    def moveCursorBack(self):
        y, x = self.scr.getyx()
        if x == 0 and y == 0:
            self.scr.move(23, 79)
        elif x == 0:
            self.scr.move(y-1, 79)
        else:
            self.scr.move(y, x-1)
        self.scr.refresh()

    def moveCursorDown(self):
        y, x = self.scr.getyx()
        if y == 23:
            if self.config['auto_scroll']:
                self.scr.addstr("\n") # Scroll
                self.scr.refresh()
                self.scr.move(23, x)
            else:
                self.scr.move(0, x)
        else:
            self.scr.move(y+1, x)
        self.scr.refresh()

    def moveCursorForward(self):
        y, x = self.scr.getyx()
        if x == 79:
            if y == 23:
                # I'm unsure what the actual terminal does
                # here and the manual isn't clear
                if self.config['auto_scroll']:
                    self.scr.addstr("\n") # Scroll
                else:
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
        y, x = self.scr.getyx()
        if y == 0:
            self.scr.move(23, x)
        else:
            self.scr.move(y-1, x)
        self.scr.refresh()

    def moveCursor(self, y, x):
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
            else:
                outch = ch
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
                # TODO
                self.oState = self.OSTATE_NORMAL
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
        else:
            # Error Unknown State
            outch = ch
            self.oState = self.OSTATE_NORMAL
        
        if outch is not None:
            # self.main_win.addstr(chr(outch))
            # self.main_win.refresh()
            self.scr.addstr(chr(outch))
            self.scr.refresh()

    def do_output(self, scr):
        self.oState = self.OSTATE_NORMAL
        self.escape_args = []


        curses.halfdelay(255)
        curses.start_color()
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
        scr.idlok(True)
        scr.scrollok(True)
        self.scr = scr
        # print("Left->"+ str(curses.KEY_LEFT))

        while self._console_alive:
            #ch = self.out_q.get()
            ch = self.device.readByte()

            if ch >= 0:
                # print("[" + str(ch) + "]")
                self.translate_output(ch)
            elif ch == self.CMD_FLUSH:
                #self.main_win.refresh()
                self.scr.refresh()
            elif ch == self.CMD_QUIT:
                break

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
            if self.scr is not None:
                try:
                    input = self.scr.getch()
                except curses.error:
                    continue

                result = self.translate_input(input)

                if result is not None:
                    for ch in result:
                        #self.in_q.put(ch)
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
        '--parity',
        choices=['N', 'E', 'O', 'S', 'M'],
        type=lambda c: c.upper(),
        help='set parity, one of {N E O S M}')

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

    term.stop()
    device.close()

if __name__ == '__main__':
    main()
