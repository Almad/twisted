
# Twisted, the Framework of Your Internet
# Copyright (C) 2001 Matthew W. Lefkowitz
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

"""
Asynchronous client DNS

API Stability: Unstable

Future plans: Proper nameserver acquisition on Windows/MacOS,
better caching, respect timeouts

@author: U{Jp Calderone<mailto:exarkun@twistedmatrix.com>}
"""

from __future__ import nested_scopes

import socket
import os

# Twisted imports
from twisted.python.runtime import platform
from twisted.internet import defer, protocol, interfaces, threads
from twisted.python import log
from twisted.protocols import dns

import common


class Resolver(common.ResolverBase):
    __implements__ = (interfaces.IResolver,)

    index = 0
    timeout = 10

    factory = None
    servers = None
    pending = None
    protocol = None
    connections = None

    def __init__(self, resolv = None, servers = None, timeout = 10):
        """
        @type servers: C{list} of C{(str, int)} or C{None}
        @param servers: If not None, interpreted as a list of addresses of
        domain name servers to attempt to use for this lookup.  Addresses
        should be in dotted-quad form.  If specified, overrides C{resolv}.
        
        @type resolv: C{str}
        @param resolv: Filename to read and parse as a resolver(5)
        configuration file.
        
        @type timeout: C{int}
        @param timeout: Default number of seconds after which to fail with a
        C{twisted.internet.defer.TimeoutError}
        
        @raise ValueError: Raised if no nameserver addresses can be found.
        """
        common.ResolverBase.__init__(self)

        self.timeout = timeout

        if servers is None:
            self.servers = []
        else:
            self.servers = servers
        
        if resolv and os.path.exists(resolv):
            self.parseConfig(resolv)
        
        if not len(self.servers):
            raise ValueError, "No nameservers specified"
        
        self.factory = DNSClientFactory(self, timeout)
        self.factory.noisy = 0   # Be quiet by default
        
        self.protocol = dns.DNSDatagramProtocol(self)
        self.protocol.noisy = 0  # You too
        
        self.connections = []
        self.pending = []


    def __getstate__(self):
        d = self.__dict__.copy()
        d['connections'] = []
        return d


    def parseConfig(self, conf):
        lines = open(conf).readlines()
        for l in lines:
            l = l.strip()
            if l.startswith('nameserver'):
                self.servers.append((l.split()[1], dns.PORT))
                log.msg("Resolver added %r to server list" % (self.servers[-1],))
            elif l.startswith('domain'):
                self.domain = l.split()[1]
                self.search = None
            elif l.startswith('search'):
                self.search = l.split()[1:]
                self.domain = None


    def pickServer(self):
        """
        Return the address of a nameserver.
        
        TODO: Weight servers for response time so faster ones can be
        preferred.
        """
        self.index = (self.index + 1) % len(self.servers)
        return self.servers[self.index]


    def connectionMade(self, protocol):
        self.connections.append(protocol)
        # XXX - need to use timeout
        for (d, q, t) in self.pending:
            protocol.query(q).chainDeferred(d)
        del self.pending[:]
    
    
    def messageReceived(self, protocol, message, address = None):
        log.msg("Unexpected message received from %r" % (address,))


    def queryUDP(self, queries, timeout = None):
        """
        Make a number of DNS queries via UDP.

        @type queries: A C{list} of C{dns.Query} instances
        @param queries: The queries to make.
        
        @type timeout: C{int}
        @param timeout: Number of seconds after which to give up the query.

        @rtype: C{Deferred}
        @raise C{twisted.internet.defer.TimeoutError}: When the query times
        out.
        """
        address = self.pickServer()
        if timeout is None:
            timeout = self.timeout
        return self.protocol.query(address, queries, timeout)


    def queryTCP(self, queries, timeout = None):
        """
        Make a number of DNS queries via TCP.

        @type queries: Any non-zero number of C{dns.Query} instances
        @param queries: The queries to make.
        
        @rtype: C{Deferred}
        """
        if not len(self.connections):
            host, port = self.pickServer()
            from twisted.internet import reactor
            reactor.connectTCP(host, port, self.factory)
            self.pending.append((defer.Deferred(), queries, timeout))
            return self.pending[-1][0]
        else:
            return self.connections[0].query(queries)


    def filterAnswers(self, message):
        if message.trunc:
            return self.queryTCP(message.queries).addCallback(self.filterAnswers)
        else:
            return (message.answers, message.authority, message.additional)


    def _lookup(self, name, cls, type, timeout):
        return self.queryUDP(
            [dns.Query(name, type, cls)], timeout
        ).addCallback(self.filterAnswers)
    
    
    # This one doesn't ever belong on UDP
    def lookupZone(self, name, timeout = 10):
        return self.queryTCP(
            [dns.Query(name, dns.AXFR, dns.IN)], timeout
        ).addCallback(self.filterAnswers)


class ThreadedResolver:
    __implements__ = (interfaces.IResolverSimple,)

    def __init__(self):
        self.cache = {}

    def getHostByName(self, name, timeout = 10):
        # XXX - Make this respect timeout
        return threads.deferToThread(socket.gethostbyname, name)


class DNSClientFactory(protocol.ClientFactory):
    def __init__(self, controller, timeout = 10):
        self.controller = controller
        self.timeout = timeout
    

    def clientConnectionLost(self, connector, reason):
        pass


    def buildProtocol(self, addr):
        p = dns.DNSProtocol(self.controller)
        p.factory = self
        return p


def createResolver(servers = None):
    import resolve, cache, hosts
    if platform.getType() == 'posix':
        theResolver = Resolver('/etc/resolv.conf', servers)
        hostResolver = hosts.Resolver()
    else:
        theResolver = ThreadedResolver()
        hostResolver = hosts.Resolver(r'c:\windows\hosts')
    return resolve.ResolverChain([hostResolver, cache.CacheResolver(), theResolver])

try:
    theResolver
except NameError:
    try:
        theResolver = createResolver()
    except ValueError:
        theResolver = createResolver(servers=[('127.0.0.1', 53)])

    for (k, v) in common.typeToMethod.items():
        exec "%s = getattr(theResolver, %r)" % (v, v)
