# Terminal Emulation for Centurion Terminals

This provides terminal emulation to communicate with Centurion Computers.<br> 
It is broadly compatiable with the ADDS Regent 25 terminal.

# Prerequisites

[Python >= v3](https://www.python.org/)

## Linux

On Ubuntu/Debian/Raspbian:

```bash
sudo apt-get install git python3 python3-pip
```

## Windows

On WSL2/Ubuntu:

```bash
sudo apt-get install git python3 python3-pip
```

On Powershell/CMD:

* Download and install Python from https://www.python.org/downloads/ <br>
    During Python install, check "Add Python to PATH"
* Download and install Git from https://git-scm.com/download/win <br>
    During Git install, make sure an option for using Git from the command line is selected

# Installation

On Linux/Ubuntu/Raspbian/WSL:

```bash
git clone https://github.com/DracoDrake/CenturionTerm.git
cd CenturionTerm
pip3 install -r requirements.txt
```

On Powershell/CMD:

```
git clone https://github.com/DracoDrake/CenturionTerm.git
cd CenturionTerm
pip3 install -r requirements.txt
pip3 install windows-curses
```

# License
[MIT](LICENSE.md)

# Getting Started

## Configuration

Configuration is either avaliable in a configuration ini file or on the command line.<br>
The command line overrides the configuration file.<br>
The configuration file 'CenturionTerm.ini' is used by default.

### Options

```
CenturionTerm - A warriors terminal emulator

positional arguments:
  url                   connect using URL (https://pyserial.readthedocs.io/en/latest/url_handlers.html)

optional arguments:
  -h, --help            show this help message and exit
  --config CONFIG       ini config file
  --no-config           disable config file

General settings:
  --normal-case-upper, --no-normal-case-upper
                        normal case is upper, shift for lower
  --echo, --no-echo     local echo / half-duplex
  --keyboard-lock-compatability, --no-keyboard-lock-compatability
                        keyboard lock ADDS Consul 580 Compatability
  --auto-scroll, --no-auto-scroll
                        auto scroll

Serial settings:
  --port [PORT]         serial device
  --baud [BAUD]         set baud rate
  --bits [BITS]         set number of data bits (5 6 7 8)
  --parity {N,E,O,S,M}  set parity, one of {N E O S M}
  --stopbits [STOPBITS]
                        set number of stop bits (1 2)
  --rtscts-flowcontrol, --no-rtscts-flowcontrol
                        RTS/CTS flow control
  --xonxoff-flowcontrol, --no-xonxoff-flowcontrol
                        software flow control
  --initial-rts, --no-initial-rts
                        set initial RTS line state
  --initial-dtr, --no-initial-dtr
                        set initial DTR line state
  --exclusive, --no-exclusive
                        locking for native ports
```

## Keys

* ```Home``` - Terminal Home Key
* ```Backspace``` - Terminal Backspace Key
* ```Delete``` - Terminal Del Key
* ```Arrow Keys``` - Terminal Arrow Keys
* ```F10``` - Quits Emulator

## Running

If using Putty, be sure it is sending "putty" as the terminal type string or use ```export TERM=putty``` before running.  The default for putty is "xterm" and it is not correct for all the keys.<br>

```bash
python CenturionTerm.py
```
