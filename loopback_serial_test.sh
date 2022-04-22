# Loopback serial - used to test
#   Creates two fake serial ports /tmp/vserial1 and /tmp/vserial2
#   Run this and then connect in two other sessions
#
#   First session connect using python3 CenturionTerm.py --port=/tmp/vserial1
#   Second session connect using python3 CenturionTerm.py --port=/tmp/vserial2
#
#   The two sessions should be able to communcate with each other
#
socat -d -d pty,link=/tmp/vserial1,raw,echo=0 pty,link=/tmp/vserial2,raw,echo=0
