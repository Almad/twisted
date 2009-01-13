# -*- test-case-name: twisted.test.test_stringtransport -*-
# Copyright (c) 2001-2009 Twisted Matrix Laboratories.
# See LICENSE for details.

"""
Assorted functionality which is commonly useful when writing unit tests.
"""

try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO

from zope.interface import implements

from twisted.internet.interfaces import ITransport, IConsumer, IPushProducer
from twisted.protocols import basic
from twisted.internet import error


class LineSendingProtocol(basic.LineReceiver):
    lostConn = False

    def __init__(self, lines, start = True):
        self.lines = lines[:]
        self.response = []
        self.start = start

    def connectionMade(self):
        if self.start:
            map(self.sendLine, self.lines)

    def lineReceived(self, line):
        if not self.start:
            map(self.sendLine, self.lines)
            self.lines = []
        self.response.append(line)

    def connectionLost(self, reason):
        self.lostConn = True


class FakeDatagramTransport:
    noAddr = object()

    def __init__(self):
        self.written = []

    def write(self, packet, addr=noAddr):
        self.written.append((packet, addr))


class StringTransport:
    """
    A transport implementation which buffers data in memory and keeps track of
    its other state without providing any behavior.

    L{StringTransport} has a number of attributes which are not part of any of
    the interfaces it claims to implement.  These attributes are provided for
    testing purposes.  Implementation code should not use any of these
    attributes; they are not provided by other transports.

    @ivar disconnecting: A C{bool} which is C{False} until L{loseConnection} is
        called, then C{True}.

    @ivar producer: If a producer is currently registered, C{producer} is a
        reference to it.  Otherwise, C{None}.

    @ivar streaming: If a producer is currently registered, C{streaming} refers
        to the value of the second parameter passed to C{registerProducer}.

    @ivar hostAddr: C{None} or an object which will be returned as the host
        address of this transport.  If C{None}, a nasty tuple will be returned
        instead.

    @ivar peerAddr: C{None} or an object which will be returned as the peer
        address of this transport.  If C{None}, a nasty tuple will be returned
        instead.

    @ivar producerState: The state of this L{StringTransport} in its capacity
        as an L{IPushProducer}.  One of C{'producing'}, C{'paused'}, or
        C{'stopped'}.

    @ivar io: A L{StringIO} which holds the data which has been written to this
        transport since the last call to L{clear}.  Use L{value} instead of
        accessing this directly.
    """
    implements(ITransport, IConsumer, IPushProducer)

    disconnecting = 0

    producer = None
    streaming = None

    hostAddr = None
    peerAddr = None

    producerState = 'producing'

    def __init__(self, hostAddress=None, peerAddress=None):
        self.clear()
        if hostAddress is not None:
            self.hostAddr = hostAddress
        if peerAddress is not None:
            self.peerAddr = peerAddress
        self.connected = True

    def clear(self):
        """
        Discard all data written to this transport so far.

        This is not a transport method.  It is intended for tests.  Do not use
        it in implementation code.
        """
        self.io = StringIO()


    def value(self):
        """
        Retrieve all data which has been buffered by this transport.

        This is not a transport method.  It is intended for tests.  Do not use
        it in implementation code.

        @return: A C{str} giving all data written to this transport since the
            last call to L{clear}.
        @rtype: C{str}
        """
        return self.io.getvalue()


    # ITransport
    def write(self, data):
        if isinstance(data, unicode): # no, really, I mean it
            raise TypeError("Data must not be unicode")
        self.io.write(data)


    def writeSequence(self, data):
        self.io.write(''.join(data))


    def loseConnection(self):
        self.disconnecting = True


    def getPeer(self):
        if self.peerAddr is None:
            return ('StringIO', repr(self.io))
        return self.peerAddr


    def getHost(self):
        if self.hostAddr is None:
            return ('StringIO', repr(self.io))
        return self.hostAddr


    # IConsumer
    def registerProducer(self, producer, streaming):
        if self.producer is not None:
            raise RuntimeError("Cannot register two producers")
        self.producer = producer
        self.streaming = streaming


    def unregisterProducer(self):
        if self.producer is None:
            raise RuntimeError(
                "Cannot unregister a producer unless one is registered")
        self.producer = None
        self.streaming = None


    # IPushProducer
    def _checkState(self):
        if self.disconnecting:
            raise RuntimeError(
                "Cannot resume producing after loseConnection")
        if self.producerState == 'stopped':
            raise RuntimeError("Cannot resume a stopped producer")


    def pauseProducing(self):
        self._checkState()
        self.producerState = 'paused'


    def stopProducing(self):
        self.producerState = 'stopped'


    def resumeProducing(self):
        self._checkState()
        self.producerState = 'producing'



class StringTransportWithDisconnection(StringTransport):
    def loseConnection(self):
        if self.connected:
            self.connected = False
            self.protocol.connectionLost(error.ConnectionDone("Bye."))

