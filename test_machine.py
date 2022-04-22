import serial
import sys
import getopt
import random
import time

def print_random(ser):
    while True:
        chint = random.randint(32,127)
        ser.write(bytes(chr(chint), 'latin'))
        time.sleep(0.2)

def main(argv):
    device = ''
    try:
        opts, args = getopt.getopt(argv, "hD:", ["device="])
    except getopt.GetoptError:
        print(sys.argv[0] + " -D <serial device>")
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-h':
            print(sys.argv[0] + " -D <serial device>")
            sys.exit()
        elif opt in ("-D", "--device"):
            device = arg

    ser = serial.Serial(device, 9600)
    print('Using device "' + device + '"')

    print_random(ser)

if __name__ == "__main__":
    main(sys.argv[1:])
