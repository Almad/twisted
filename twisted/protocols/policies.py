# -*- test-case-name: twisted.test.test_policies -*-
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

"""Resource limiting policies."""

# system imports
import sys, operator, time

# twisted imports
from twisted.internet.protocol import ServerFactory, Protocol, ClientFactory
from twisted.internet.interfaces import ITransport
from twisted.internet import reactor, error
from twisted.python import log


class ProtocolWrapper(Protocol):
    """Wraps protocol instances and acts as their transport as well."""
    
    __implements__ = ITransport,

    disconnecting = 0

    def __init__(self, factory, wrappedProtocol):
        self.wrappedProtocol = wrappedProtocol
        self.factory = factory

    # Transport relaying
    
    def write(self, data):
        self.transport.write(data)

    def writeSequence(self, data):
        self.transport.writeSequence(data)

    def loseConnection(self):
        self.disconnecting = 1
        self.transport.loseConnection()

    def getPeer(self):
        return self.transport.getPeer()

    def getHost(self):
        return self.transport.getHost()
    
    def registerProducer(self, producer, streaming):
        self.transport.registerProducer(producer, streaming)

    def unregisterProducer(self):
        self.transport.unregisterProducer()

    def stopConsuming(self):
        self.transport.stopConsuming()

    
    # Protocol relaying
    
    def connectionMade(self):
        self.factory.registerProtocol(self)
        self.wrappedProtocol.makeConnection(self)

    def dataReceived(self, data):
        self.wrappedProtocol.dataReceived(data)

    def connectionLost(self, reason):
        self.factory.unregisterProtocol(self)
        self.wrappedProtocol.connectionLost(reason)


class WrappingFactory(ClientFactory):
    """Wraps a factory and its protocols, and keeps track of them."""
    
    protocol = ProtocolWrapper
    
    def __init__(self, wrappedFactory):
        self.wrappedFactory = wrappedFactory
        self.protocols = {}

    def startedConnecting(self, connector):
        self.wrappedFactory.startedConnecting(connector)

    def clientConnectionFailed(self, connector, reason):
        self.wrappedFactory.clientConnectionFailed(connector, reason)

    def clientConnectionLost(self, connector, reason):
        self.wrappedFactory.clientConnectionLost(connector, reason)

    def buildProtocol(self, addr):
        return self.protocol(self, self.wrappedFactory.buildProtocol(addr))    

    def registerProtocol(self, p):
        """Called by protocol to register itself."""
        self.protocols[p] = 1

    def unregisterProtocol(self, p):
        """Called by protocols when they go away."""
        del self.protocols[p]


class ThrottlingProtocol(ProtocolWrapper):
    """Protocol for ThrottlingFactory."""

    # wrap API for tracking bandwidth
    
    def write(self, data):
        self.factory.registerWritten(len(data))
        ProtocolWrapper.write(self, data)

    def writeSequence(self, seq):
        self.factory.registerWritten(reduce(operator.add, map(len, seq)))
        ProtocolWrapper.writeSequence(self, seq)

    def dataReceived(self, data):
        self.factory.registerRead(len(data))
        ProtocolWrapper.dataReceived(self, data)

    def registerProducer(self, producer, streaming):
        self.producer = producer
        ProtocolWrapper.registerProducer(self, producer, streaming)

    def unregisterProducer(self):
        del self.producer
        ProtocolWrapper.unregisterProducer(self)

    
    def throttleReads(self):
        self.transport.stopReading()

    def unthrottleReads(self):
        self.transport.startReading()

    def throttleWrites(self):
        if hasattr(self, "producer"):
            self.producer.pauseProducing()

    def unthrottleWrites(self):
        if hasattr(self, "producer"):
            self.producer.resumeProducing()


class ThrottlingFactory(WrappingFactory):
    """Throttles bandwidth and number of connections.

    Write bandwidth will only be throttled if there is a producer
    registered.
    """

    protocol = ThrottlingProtocol

    def __init__(self, wrappedFactory, maxConnectionCount=sys.maxint, readLimit=None, writeLimit=None):
        WrappingFactory.__init__(self, wrappedFactory)
        self.connectionCount = 0
        self.maxConnectionCount = maxConnectionCount
        self.readLimit = readLimit # max bytes we should read per second
        self.writeLimit = writeLimit # max bytes we should write per second
        self.readThisSecond = 0
        self.writtenThisSecond = 0
        self.unthrottleReadsID = None
        self.checkReadBandwidthID = None
        self.unthrottleWritesID = None
        self.checkWriteBandwidthID = None

    def registerWritten(self, length):
        """Called by protocol to tell us more bytes were written."""
        self.writtenThisSecond += length

    def registerRead(self, length):
        """Called by protocol to tell us more bytes were read."""
        self.readThisSecond += length

    def checkReadBandwidth(self):
        """Checks if we've passed bandwidth limits."""
        if self.readThisSecond > self.readLimit:
            self.throttleReads()
            throttleTime = (float(self.readThisSecond) / self.readLimit) - 1.0
            self.unthrottleReadsID = reactor.callLater(throttleTime,
                                                       self.unthrottleReads)
        self.readThisSecond = 0
        self.checkReadBandwidthID = reactor.callLater(1, self.checkReadBandwidth)

    def checkWriteBandwidth(self):
        if self.writtenThisSecond > self.writeLimit:
            self.throttleWrites()
            throttleTime = (float(self.writtenThisSecond) / self.writeLimit) - 1.0
            self.unthrottleWritesID = reactor.callLater(throttleTime,
                                                        self.unthrottleWrites)
        # reset for next round    
        self.writtenThisSecond = 0
        self.checkWriteBandwidthID = reactor.callLater(1, self.checkWriteBandwidth)

    def throttleReads(self):
        """Throttle reads on all protocols."""
        log.msg("Throttling reads on %s" % self)
        for p in self.protocols.keys():
            p.throttleReads()

    def unthrottleReads(self):
        """Stop throttling reads on all protocols."""
        self.unthrottleReadsID = None
        log.msg("Stopped throttling reads on %s" % self)
        for p in self.protocols.keys():
            p.unthrottleReads()

    def throttleWrites(self):
        """Throttle writes on all protocols."""
        log.msg("Throttling writes on %s" % self)
        for p in self.protocols.keys():
            p.throttleWrites()

    def unthrottleWrites(self):
        """Stop throttling writes on all protocols."""
        self.unthrottleWritesID = None
        log.msg("Stopped throttling writes on %s" % self)
        for p in self.protocols.keys():
            p.unthrottleWrites()

    def buildProtocol(self, addr):
        if self.connectionCount == 0:
            if self.readLimit is not None:
                self.checkReadBandwidth()
            if self.writeLimit is not None:
                self.checkWriteBandwidth()

        if self.connectionCount < self.maxConnectionCount:
            self.connectionCount += 1
            return WrappingFactory.buildProtocol(self, addr)
        else:
            log.msg("Max connection count reached!")
            return None

    def unregisterProtocol(self, p):
        WrappingFactory.unregisterProtocol(self, p)
        self.connectionCount -= 1
        if self.connectionCount == 0:
            if self.unthrottleReadsID is not None:
                self.unthrottleReadsID.cancel()
            if self.checkReadBandwidthID is not None:
                self.checkReadBandwidthID.cancel()
            if self.unthrottleWritesID is not None:
                self.unthrottleWritesID.cancel()
            if self.checkWriteBandwidthID is not None:
                self.checkWriteBandwidthID.cancel()

class SpewingProtocol(ProtocolWrapper):
    def dataReceived(self, data):
        log.msg("Received: %r" % data)
        ProtocolWrapper.dataReceived(self,data)

    def write(self, data):
        log.msg("Sending: %r" % data)
        ProtocolWrapper.write(self,data)

class SpewingFactory(WrappingFactory):
    protocol = SpewingProtocol


class LimitConnectionsByPeerProtocol(ProtocolWrapper):
    """Stability: Unstable"""
    def connectionLost(self):
        self.factory.peerDisconnected(self)
        self.wrappedProtocol.connectionLost(self)
    

class LimitConnectionsByPeer(WrappingFactory):
    """Stability: Unstable"""
    protocol = LimitConnectionsByPeerProtocol

    maxConnectionsPerPeer = 5

    def startFactory(self):
        self.peerConnections = {}
        
    def buildProtocol(self, addr):
        peerHost = addr[1]
        connectionCount = self.peerConnections.get(peerHost, 0)
        if connectionCount >= self.maxConnectionsPerPeer:
            return None
        self.peerConnections[peerHost] = connectionCount + 1
        return WrappingFactory.buildProtocol(self, addr)

    def unregisterProtocol(self, p):
        peerHost = p.getPeer()[1]
        self.peerConnections[peerHost] -= 1
        if self.peerConnections[peerHost] == 0:
            del self.peerConnections[peerHost]


class TimeoutProtocol(ProtocolWrapper):
    """Protocol that automatically disconnects when the connection is idle.
    
    Stability: Unstable
    """

    def __init__(self, factory, wrappedProtocol, timeoutPeriod):
        """Constructor.

        @param factory: An L{IFactory}.
        @param wrappedProtocol: A L{Protocol} to wrapp.
        @param timeoutPeriod: Number of seconds to wait for activity before
            timing out.
        """
        ProtocolWrapper.__init__(self, factory, wrappedProtocol)
        self.timeoutCall = None
        self.setTimeout(timeoutPeriod)

    def setTimeout(self, timeoutPeriod=None):
        """Set a timeout.
        
        This will cancel any existing timeouts.

        @param timeoutPeriod: If not C{None}, change the timeout period.
            Otherwise, use the existing value.
        """
        self.cancelTimeout()
        if timeoutPeriod is not None:
            self.timeoutPeriod = timeoutPeriod
        self.timeoutCall = reactor.callLater(self.timeoutPeriod, self.timeoutFunc)

    def cancelTimeout(self):
        """Cancel the timeout.
        
        If the timeout was already cancelled, this does nothing.
        """
        if self.timeoutCall:
            try:
                self.timeoutCall.cancel()
            except error.AlreadyCalled:
                pass
            self.timeoutCall = None
    
    def resetTimeout(self):
        """Reset the timeout, usually because some activity just happened."""
        if self.timeoutCall:
            self.timeoutCall.reset(self.timeoutPeriod)

    def write(self, data):
        self.resetTimeout()
        ProtocolWrapper.write(self, data)

    def writeSequence(self, seq):
        self.resetTimeout()
        ProtocolWrapper.writeSequence(self, seq)

    def dataReceived(self, data):
        self.resetTimeout()
        ProtocolWrapper.dataReceived(self, data)

    def connectionLost(self, reason):
        self.cancelTimeout()
        ProtocolWrapper.connectionLost(self, reason)

    def timeoutFunc(self):
        """This method is called when the timeout is triggered.

        By default it calls L{loseConnection}.  Override this if you want
        something else to happen.
        """
        self.loseConnection()


class TimeoutFactory(WrappingFactory):
    """Factory for TimeoutWrapper.

    Stability: Unstable
    """
    protocol = TimeoutProtocol

    def __init__(self, wrappedFactory, timeoutPeriod=30*60):
        self.timeoutPeriod = timeoutPeriod
        WrappingFactory.__init__(self, wrappedFactory)

    def buildProtocol(self, addr):
        return self.protocol(self, self.wrappedFactory.buildProtocol(addr),
                             timeoutPeriod=self.timeoutPeriod)    


class TimeoutMixin:
    """Mixin for protocols which wish to timeout connections

    @cvar timeOut: The number of seconds after which to timeout the connection.
    """
    timeOut = None

    __timeoutCall = None
    __lastReceived = None

    def resetTimeout(self):
        """Reset the timeout count down"""
        self.__lastReceived = time.time()
    
    def setTimeout(self, period):
        """Change the timeout period
        
        @type period: C{int} or C{NoneType}
        @param period: The period, in seconds, to change the timeout to, or
        C{None} to disable the timeout.
        """
        prev = self.timeOut
        self.timeOut = period
        self.__lastReceived = time.time()
        if self.__timeoutCall:
            self.__timeoutCall.cancel()
            self.__timeoutCall = None
        if period is not None:
            self.__timeoutCall = reactor.callLater(period, self.__timedOut)
        return prev

    def __timedOut(self):
        self.__timeoutCall = None

        now = time.time()
        if now - (self.__lastReceived or now) > self.timeOut:
            self.timeoutConnection()
        else:
            when = self.__lastReceived - now + self.timeOut
            self.__timeoutCall = reactor.callLater(when, self.__timedOut)

    def timeoutConnection(self):
        """Called when the connection times out.
        Override to define behavior other than dropping the connection.
        """
        self.transport.loseConnection()
