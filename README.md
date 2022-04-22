# Terminal Emulation for Centurion Terminals (ADDS Regent 25)

This provides terminal emulation to communicate with Centurion Computers. 

# Prerequisites

[Python >= v3](https://www.python.org/)


## Linux

On Ubuntu/Debian/Raspbian:

```bash
sudo apt-get install python3 python3-pip
```

# Windows

On WSL2/Ubuntu:

```bash
sudo apt-get install python3 python3-pip
```

On Powershell/CMD:

* Download and install from [Python's Website](https://www.python.org/downloads/windows/).

# Installation

With `pip3`:

```bash
git clone https://
cd CenturionTerm
pip3 install -r requirements.txt
```

# License
[MIT](LICENSE.md)

# Getting Started

## Configuration

CenturionTerm is configured via an INI file.  The default config file is called 'CenturionTerm.ini'.  However, you can specify a different one on the command line.  See 'CenturionTerm.ini' for documentation.

## Running

```bash
python3 CenturionTerm.py
```
