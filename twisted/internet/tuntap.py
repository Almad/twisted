# Twisted, the Framework of Your Internet
# Copyright (C) 2001-2002 Matthew W. Lefkowitz
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of version 2.1 of the GNU Lesser General Public
# License as published by the Free Software Foundation.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#
import errno, os
from twisted.python import log, reflect
from twisted.internet import base, fdesc
from twisted.protocols import ethernet

from eunuchs.tuntap import opentuntap, TuntapPacketInfo, makePacketInfo

class TuntapPort(base.BasePort):
    """A Port that reads and writes packets from/to a TUN/TAP-device.

    TODO: Share general start/stop etc implementation details with
    twisted.internet.udp.Port.
    """
    maxThroughput = 256 * 1024 # max bytes we read in one eventloop iteration

    def __init__(self, interface, proto, maxPacketSize=8192, reactor=None):
        if isinstance(proto, ethernet.EthernetProtocol):
            self.ethernet = 1
        else:
            self.ethernet = 0
            assert isinstance(proto, ip.IPProtocol)
        base.BasePort.__init__(self, reactor)
        self.interface = interface
        self.protocol = proto
        self.maxPacketSize = maxPacketSize
        self.setLogStr()

    def __repr__(self):
        return "<%s on %s>" % (self.protocol.__class__, self.port)

    def startListening(self):
        """Create and bind my socket, and begin listening on it.

        This is called on unserialization, and must be called after creating a
        server to begin listening on the specified port.
        """
        self._bindSocket()
        self._connectToProtocol()

    def _bindSocket(self):
        log.msg("%s starting on %s"%(self.protocol.__class__, self.interface))
        try:
            fd, name = opentuntap(name=self.interface,
                                  ethernet=self.ethernet,
                                  packetinfo=1)
        except OSError, e:
            raise error.CannotListenError, (self.interface, e)
        fdesc.setNonBlocking(fd)
        self.interface = name
        self.connected = 1
        self.fd = fd

    def fileno(self):
        return self.fd

    def _connectToProtocol(self):
        self.protocol.makeConnection(self)
        self.startReading()

    def doRead(self):
        """Called when my socket is ready for reading."""
        read = 0
        while read < self.maxThroughput:
            try:
                data = os.read(self.fd, self.maxPacketSize)
                read += len(data)
                pkt = TuntapPacketInfo(data)
                self.protocol.datagramReceived(pkt.data,
                                               partial=pkt.isPartial(),
                                               )
            except OSError, e:
                if e.errno in (errno.EWOULDBLOCK,):
                    return
                else:
                    raise
            except IOError, e:
                if e.errno in (errno.EAGAIN, errno.EINTR):
                    return
                else:
                    raise
            except:
                log.deferr()

    def write(self, datagram):
        """Write a datagram."""
        header = makePacketInfo(0, 0)
        try:
            return os.write(self.fd, header + datagram)
        except IOError, e:
            if e.errno == errno.EINTR:
                return self.write(datagram)
            elif e.errno == errno.EMSGSIZE:
                raise error.MessageLengthError, "message too long"
            elif e.errno == errno.ECONNREFUSED:
                raise error.ConnectionRefusedError
            else:
                raise

    def writeSequence(self, seq, addr):
        self.write("".join(seq), addr)

    def loseConnection(self):
        """Stop accepting connections on this port.

        This will shut down my socket and call self.connectionLost().
        """
        self.stopReading()
        if self.connected:
            from twisted.internet import reactor
            reactor.callLater(0, self.connectionLost)

    stopListening = loseConnection

    def connectionLost(self, reason=None):
        """Cleans up my socket.
        """
        log.msg('(Tuntap %s Closed)' % self.interface)
        base.BasePort.connectionLost(self, reason)
        if hasattr(self, "protocol"):
            # we won't have attribute in ConnectedPort, in cases
            # where there was an error in connection process
            self.protocol.doStop()
        self.connected = 0
        os.close(self.fd)
        del self.fd

    def setLogStr(self):
        self.logstr = reflect.qual(self.protocol.__class__) + " (TUNTAP)"

    def logPrefix(self):
        """Returns the name of my class, to prefix log entries with.
        """
        return self.logstr

    def getHost(self):
        """
        Returns a tuple of ('TUNTAP', interface), indicating
        the servers address
        """
        return ('TUNTAP',)+self.interface
