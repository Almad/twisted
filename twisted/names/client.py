# -*- test-case-name: twisted.names.test.test_names -*-
# Copyright (c) 2001-2006 Twisted Matrix Laboratories.
# See LICENSE for details.


"""
Asynchronous client DNS

API Stability: Unstable

The functions exposed in this module can be used for asynchronous name
resolution and dns queries.

If you need to create a resolver with specific requirements, such as needing to
do queries against a particular host, the L{createResolver} function will
return an C{IResolver}.

Future plans: Proper nameserver acquisition on Windows/MacOS,
better caching, respect timeouts

@author: U{Jp Calderone<mailto:exarkun@twistedmatrix.com>}
"""

from __future__ import nested_scopes

import os
import errno

from zope.interface import implements

# Twisted imports
from twisted.python.runtime import platform
from twisted.internet import error, defer, protocol, interfaces
from twisted.python import log, failure
from twisted.names import dns, common
from twisted.names.error import DNSFormatError, DNSServerError, DNSNameError
from twisted.names.error import DNSNotImplementedError, DNSQueryRefusedError
from twisted.names.error import DNSUnknownError


class Resolver(common.ResolverBase):
    implements(interfaces.IResolver)

    index = 0
    timeout = None

    factory = None
    servers = None
    dynServers = ()
    pending = None
    protocol = None
    connections = None

    resolv = None
    _lastResolvTime = None
    _resolvReadInterval = 60

    _errormap = {
        dns.EFORMAT: DNSFormatError,
        dns.ESERVER: DNSServerError,
        dns.ENAME: DNSNameError,
        dns.ENOTIMP: DNSNotImplementedError,
        dns.EREFUSED: DNSQueryRefusedError}

    def __init__(self, resolv = None, servers = None, timeout = (1, 3, 11, 45)):
        """
        Construct a resolver which will query domain name servers listed in
        the C{resolv.conf(5)}-format file given by C{resolv} as well as
        those in the given C{servers} list.  Servers are queried in a
        round-robin fashion.  If given, C{resolv} is periodically checked
        for modification and re-parsed if it is noticed to have changed.

        @type servers: C{list} of C{(str, int)} or C{None}
        @param servers: If not C{None}, interpreted as a list of addresses of
        domain name servers to attempt to use for this lookup.  Addresses
        should be in dotted-quad form.  If specified, overrides C{resolv}.

        @type resolv: C{str}
        @param resolv: Filename to read and parse as a resolver(5)
        configuration file.

        @type timeout: Sequence of C{int}
        @param timeout: Default number of seconds after which to reissue the query.
        When the last timeout expires, the query is considered failed.

        @raise ValueError: Raised if no nameserver addresses can be found.
        """
        common.ResolverBase.__init__(self)

        self.timeout = timeout

        if servers is None:
            self.servers = []
        else:
            self.servers = servers

        self.resolv = resolv

        if not len(self.servers) and not resolv:
            raise ValueError, "No nameservers specified"

        self.factory = DNSClientFactory(self, timeout)
        self.factory.noisy = 0   # Be quiet by default

        self.protocol = dns.DNSDatagramProtocol(self)
        self.protocol.noisy = 0  # You too

        self.connections = []
        self.pending = []

        self.maybeParseConfig()


    def __getstate__(self):
        d = self.__dict__.copy()
        d['connections'] = []
        d['_parseCall'] = None
        return d


    def __setstate__(self, state):
        self.__dict__.update(state)
        self.maybeParseConfig()


    def maybeParseConfig(self):
        if self.resolv is None:
            # Don't try to parse it, don't set up a call loop
            return

        try:
            resolvConf = file(self.resolv)
        except IOError, e:
            if e.errno == errno.ENOENT:
                # Missing resolv.conf is treated the same as an empty resolv.conf
                self.parseConfig(())
            else:
                raise
        else:
            mtime = os.fstat(resolvConf.fileno()).st_mtime
            if mtime != self._lastResolvTime:
                log.msg('%s changed, reparsing' % (self.resolv,))
                self._lastResolvTime = mtime
                self.parseConfig(resolvConf)

        # Check again in a little while
        from twisted.internet import reactor
        self._parseCall = reactor.callLater(self._resolvReadInterval, self.maybeParseConfig)


    def parseConfig(self, resolvConf):
        servers = []
        for L in resolvConf:
            L = L.strip()
            if L.startswith('nameserver'):
                resolver = (L.split()[1], dns.PORT)
                servers.append(resolver)
                log.msg("Resolver added %r to server list" % (resolver,))
            elif L.startswith('domain'):
                try:
                    self.domain = L.split()[1]
                except IndexError:
                    self.domain = ''
                self.search = None
            elif L.startswith('search'):
                try:
                    self.search = L.split()[1:]
                except IndexError:
                    self.search = ''
                self.domain = None
        if not servers:
            servers.append(('127.0.0.1', dns.PORT))
        self.dynServers = servers


    def pickServer(self):
        """
        Return the address of a nameserver.

        TODO: Weight servers for response time so faster ones can be
        preferred.
        """
        if not self.servers and not self.dynServers:
            return None
        serverL = len(self.servers)
        dynL = len(self.dynServers)

        self.index += 1
        self.index %= (serverL + dynL)
        if self.index < serverL:
            return self.servers[self.index]
        else:
            return self.dynServers[self.index - serverL]

    def connectionMade(self, protocol):
        self.connections.append(protocol)
        for (d, q, t) in self.pending:
            self.queryTCP(q, t).chainDeferred(d)
        del self.pending[:]


    def messageReceived(self, message, protocol, address = None):
        log.msg("Unexpected message (%d) received from %r" % (message.id, address))


    def queryUDP(self, queries, timeout = None):
        """
        Make a number of DNS queries via UDP.

        @type queries: A C{list} of C{dns.Query} instances
        @param queries: The queries to make.

        @type timeout: Sequence of C{int}
        @param timeout: Number of seconds after which to reissue the query.
        When the last timeout expires, the query is considered failed.

        @rtype: C{Deferred}
        @raise C{twisted.internet.defer.TimeoutError}: When the query times
        out.
        """
        if timeout is None:
            timeout = self.timeout

        addresses = self.servers + list(self.dynServers)
        if not addresses:
            return defer.fail(IOError("No domain name servers available"))

        used = addresses.pop()
        return self.protocol.query(used, queries, timeout[0]
            ).addErrback(self._reissue, addresses, [used], queries, timeout
            )


    def _reissue(self, reason, addressesLeft, addressesUsed, query, timeout):
        reason.trap(dns.DNSQueryTimeoutError)

        # If there are no servers left to be tried, adjust the timeout
        # to the next longest timeout period and move all the
        # "used" addresses back to the list of addresses to try.
        if not addressesLeft:
            addressesLeft = addressesUsed
            addressesLeft.reverse()
            addressesUsed = []
            timeout = timeout[1:]

        # If all timeout values have been used, or the protocol has no
        # transport, this query has failed.  Tell the protocol we're
        # giving up on it and return a terminal timeout failure to our
        # caller.
        if not timeout or self.protocol.transport is None:
            self.protocol.removeResend(reason.value.id)
            return failure.Failure(defer.TimeoutError(query))

        # Get an address to try.  Take it out of the list of addresses
        # to try and put it ino the list of already tried addresses.
        address = addressesLeft.pop()
        addressesUsed.append(address)

        # Issue a query to a server.  Use the current timeout.  Add this
        # function as a timeout errback in case another retry is required.
        d = self.protocol.query(address, query, timeout[0], reason.value.id)
        d.addErrback(self._reissue, addressesLeft, addressesUsed, query, timeout)
        return d


    def queryTCP(self, queries, timeout = 10):
        """
        Make a number of DNS queries via TCP.

        @type queries: Any non-zero number of C{dns.Query} instances
        @param queries: The queries to make.

        @type timeout: C{int}
        @param timeout: The number of seconds after which to fail.

        @rtype: C{Deferred}
        """
        if not len(self.connections):
            address = self.pickServer()
            if address is None:
                return defer.fail(IOError("No domain name servers available"))
            host, port = address
            from twisted.internet import reactor
            reactor.connectTCP(host, port, self.factory)
            self.pending.append((defer.Deferred(), queries, timeout))
            return self.pending[-1][0]
        else:
            return self.connections[0].query(queries, timeout)


    def filterAnswers(self, message):
        """
        Extract results from the given message.

        If the message was truncated, re-attempt the query over TCP and return
        a Deferred which will fire with the results of that query.

        If the message's result code is not L{dns.OK}, return a Failure
        indicating the type of error which occurred.

        Otherwise, return a three-tuple of lists containing the results from
        the answers section, the authority section, and the additional section.
        """
        if message.trunc:
            return self.queryTCP(message.queries).addCallback(self.filterAnswers)
        if message.rCode != dns.OK:
            return failure.Failure(self._errormap.get(message.rCode, DNSUnknownError)(message))
        return (message.answers, message.authority, message.additional)


    def _lookup(self, name, cls, type, timeout):
        return self.queryUDP(
            [dns.Query(name, type, cls)], timeout
        ).addCallback(self.filterAnswers)


    # This one doesn't ever belong on UDP
    def lookupZone(self, name, timeout = 10):
        """
        Perform an AXFR request. This is quite different from usual
        DNS requests. See http://cr.yp.to/djbdns/axfr-notes.html for
        more information.
        """
        address = self.pickServer()
        if address is None:
            return defer.fail(IOError('No domain name servers available'))
        host, port = address
        d = defer.Deferred()
        controller = AXFRController(name, d)
        factory = DNSClientFactory(controller, timeout)
        factory.noisy = False #stfu

        from twisted.internet import reactor
        connector = reactor.connectTCP(host, port, factory)
        controller.timeoutCall = reactor.callLater(timeout or 10,
                                                   self._timeoutZone,
                                                   d, controller,
                                                   connector,
                                                   timeout or 10)
        return d.addCallback(self._cbLookupZone, connector)

    def _timeoutZone(self, d, controller, connector, seconds):
        connector.disconnect()
        controller.timeoutCall = None
        controller.deferred = None
        d.errback(error.TimeoutError("Zone lookup timed out after %d seconds" % (seconds,)))

    def _cbLookupZone(self, result, connector):
        connector.disconnect()
        return (result, [], [])


class AXFRController:
    timeoutCall = None

    def __init__(self, name, deferred):
        self.name = name
        self.deferred = deferred
        self.soa = None
        self.records = []

    def connectionMade(self, protocol):
        # dig saids recursion-desired to 0, so I will too
        message = dns.Message(protocol.pickID(), recDes=0)
        message.queries = [dns.Query(self.name, dns.AXFR, dns.IN)]
        protocol.writeMessage(message)

    def messageReceived(self, message, protocol):
        # Caveat: We have to handle two cases: All records are in 1
        # message, or all records are in N messages.

        # According to http://cr.yp.to/djbdns/axfr-notes.html,
        # 'authority' and 'additional' are always empty, and only
        # 'answers' is present.
        self.records.extend(message.answers)
        if not self.records:
            return
        if not self.soa:
            if self.records[0].type == dns.SOA:
                #print "first SOA!"
                self.soa = self.records[0]
        if len(self.records) > 1 and self.records[-1].type == dns.SOA:
            #print "It's the second SOA! We're done."
            if self.timeoutCall is not None:
                self.timeoutCall.cancel()
                self.timeoutCall = None
            if self.deferred is not None:
                self.deferred.callback(self.records)
                self.deferred = None



from twisted.internet.base import ThreadedResolver as _ThreadedResolverImpl

class ThreadedResolver(_ThreadedResolverImpl):
    def __init__(self, reactor=None):
        if reactor is None:
            from twisted.internet import reactor
        _ThreadedResolverImpl.__init__(self, reactor)
        # warnings.warn("twisted.names.client.ThreadedResolver is deprecated, use XXX instead.")

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



def createResolver(servers=None, resolvconf=None, hosts=None):
    """
    Create and return a Resolver.

    @type servers: C{list} of C{(str, int)} or C{None}
    @param servers: If not C{None}, interpreted as a list of addresses of
    domain name servers to attempt to use.  Addresses should be in dotted-quad
    form.

    @type resolvconf: C{str} or C{None}
    @param resolvconf: If not C{None}, on posix systems will be interpreted as
    an alternate resolv.conf to use. Will do nothing on windows systems. If
    C{None}, /etc/resolv.conf will be used.

    @type hosts: C{str} or C{None}
    @param hosts: If not C{None}, an alternate hosts file to use. If C{None}
    on posix systems, /etc/hosts will be used. On windows, C:\windows\hosts
    will be used.

    @rtype: C{IResolver}
    """
    from twisted.names import resolve, cache, root, hosts as hostsModule
    if platform.getType() == 'posix':
        if resolvconf is None:
            resolvconf = '/etc/resolv.conf'
        if hosts is None:
            hosts = '/etc/hosts'
        theResolver = Resolver(resolvconf, servers)
        hostResolver = hostsModule.Resolver(hosts)
    else:
        if hosts is None:
            hosts = r'c:\windows\hosts'
        from twisted.internet import reactor
        bootstrap = _ThreadedResolverImpl(reactor)
        hostResolver = hostsModule.Resolver(hosts)
        theResolver = root.bootstrap(bootstrap)

    L = [hostResolver, cache.CacheResolver(), theResolver]
    return resolve.ResolverChain(L)

theResolver = None
def getResolver():
    """
    Get a Resolver instance.

    Create twisted.names.client.theResolver if it is C{None}, and then return
    that value.

    @rtype: C{IResolver}
    """
    global theResolver
    if theResolver is None:
        try:
            theResolver = createResolver()
        except ValueError:
            theResolver = createResolver(servers=[('127.0.0.1', 53)])
    return theResolver

def getHostByName(name, timeout=None, effort=10):
    """
    Resolve a name to a valid ipv4 or ipv6 address.

    Will errback with C{DNSQueryTimeoutError} on a timeout, C{DomainError} or
    C{AuthoritativeDomainError} (or subclasses) on other errors.

    @type name: C{str}
    @param name: DNS name to resolve.

    @type timeout: Sequence of C{int}
    @param timeout: Number of seconds after which to reissue the query.
    When the last timeout expires, the query is considered failed.

    @type effort: C{int}
    @param effort: How many times CNAME and NS records to follow while
    resolving this name.

    @rtype: C{Deferred}
    """
    return getResolver().getHostByName(name, timeout, effort)

def lookupAddress(name, timeout=None):
    """
    Perform an A record lookup.

    @type name: C{str}
    @param name: DNS name to resolve.
    
    @type timeout: Sequence of C{int}
    @param timeout: Number of seconds after which to reissue the query.
    When the last timeout expires, the query is considered failed.
    
    @rtype: C{Deferred}
    """
    return getResolver().lookupAddress(name, timeout)

def lookupIPV6Address(name, timeout=None):
    """
    Perform an AAAA record lookup.

    @type name: C{str}
    @param name: DNS name to resolve.
    
    @type timeout: Sequence of C{int}
    @param timeout: Number of seconds after which to reissue the query.
    When the last timeout expires, the query is considered failed.
    
    @rtype: C{Deferred}
    """
    return getResolver().lookupIPV6Address(name, timeout)

def lookupAddress6(name, timeout=None):
    """
    Perform an A6 record lookup.

    @type name: C{str}
    @param name: DNS name to resolve.
    
    @type timeout: Sequence of C{int}
    @param timeout: Number of seconds after which to reissue the query.
    When the last timeout expires, the query is considered failed.
    
    @rtype: C{Deferred}
    """
    return getResolver().lookupAddress6(name, timeout)

def lookupMailExchange(name, timeout=None):
    """
    Perform an MX record lookup.

    @type name: C{str}
    @param name: DNS name to resolve.
    
    @type timeout: Sequence of C{int}
    @param timeout: Number of seconds after which to reissue the query.
    When the last timeout expires, the query is considered failed.
    
    @rtype: C{Deferred}
    """
    return getResolver().lookupMailExchange(name, timeout)

def lookupNameservers(name, timeout=None):
    """
    Perform an NS record lookup.

    @type name: C{str}
    @param name: DNS name to resolve.
    
    @type timeout: Sequence of C{int}
    @param timeout: Number of seconds after which to reissue the query.
    When the last timeout expires, the query is considered failed.
    
    @rtype: C{Deferred}
    """
    return getResolver().lookupNameservers(name, timeout)

def lookupCanonicalName(name, timeout=None):
    """
    Perform a CNAME record lookup.

    @type name: C{str}
    @param name: DNS name to resolve.
    
    @type timeout: Sequence of C{int}
    @param timeout: Number of seconds after which to reissue the query.
    When the last timeout expires, the query is considered failed.
    
    @rtype: C{Deferred}
    """
    return getResolver().lookupCanonicalName(name, timeout)

def lookupMailBox(name, timeout=None):
    """
    Perform an MB record lookup.

    @type name: C{str}
    @param name: DNS name to resolve.
    
    @type timeout: Sequence of C{int}
    @param timeout: Number of seconds after which to reissue the query.
    When the last timeout expires, the query is considered failed.
    
    @rtype: C{Deferred}
    """
    return getResolver().lookupMailBox(name, timeout)

def lookupMailGroup(name, timeout=None):
    """
    Perform an MG record lookup.

    @type name: C{str}
    @param name: DNS name to resolve.
    
    @type timeout: Sequence of C{int}
    @param timeout: Number of seconds after which to reissue the query.
    When the last timeout expires, the query is considered failed.
    
    @rtype: C{Deferred}
    """
    return getResolver().lookupMailGroup(name, timeout)

def lookupMailRename(name, timeout=None):
    """
    Perform an MR record lookup.

    @type name: C{str}
    @param name: DNS name to resolve.
    
    @type timeout: Sequence of C{int}
    @param timeout: Number of seconds after which to reissue the query.
    When the last timeout expires, the query is considered failed.
    
    @rtype: C{Deferred}
    """
    return getResolver().lookupMailRename(name, timeout)

def lookupPointer(name, timeout=None):
    """
    Perform a PTR record lookup.

    @type name: C{str}
    @param name: DNS name to resolve.
    
    @type timeout: Sequence of C{int}
    @param timeout: Number of seconds after which to reissue the query.
    When the last timeout expires, the query is considered failed.
    
    @rtype: C{Deferred}
    """
    return getResolver().lookupPointer(name, timeout)

def lookupAuthority(name, timeout=None):
    """
    Perform an SOA record lookup.

    @type name: C{str}
    @param name: DNS name to resolve.
    
    @type timeout: Sequence of C{int}
    @param timeout: Number of seconds after which to reissue the query.
    When the last timeout expires, the query is considered failed.
    
    @rtype: C{Deferred}
    """
    return getResolver().lookupAuthority(name, timeout)

def lookupNull(name, timeout=None):
    """
    Perform a NULL record lookup.

    @type name: C{str}
    @param name: DNS name to resolve.
    
    @type timeout: Sequence of C{int}
    @param timeout: Number of seconds after which to reissue the query.
    When the last timeout expires, the query is considered failed.
    
    @rtype: C{Deferred}
    """
    return getResolver().lookupNull(name, timeout)

def lookupWellKnownServices(name, timeout=None):
    """
    Perform a WKS record lookup.

    @type name: C{str}
    @param name: DNS name to resolve.
    
    @type timeout: Sequence of C{int}
    @param timeout: Number of seconds after which to reissue the query.
    When the last timeout expires, the query is considered failed.
    
    @rtype: C{Deferred}
    """
    return getResolver().lookupWellKnownServices(name, timeout)

def lookupService(name, timeout=None):
    """
    Perform an SRV record lookup.

    @type name: C{str}
    @param name: DNS name to resolve.
    
    @type timeout: Sequence of C{int}
    @param timeout: Number of seconds after which to reissue the query.
    When the last timeout expires, the query is considered failed.
    
    @rtype: C{Deferred}
    """
    return getResolver().lookupService(name, timeout)

def lookupHostInfo(name, timeout=None):
    """
    Perform a HINFO record lookup.

    @type name: C{str}
    @param name: DNS name to resolve.
    
    @type timeout: Sequence of C{int}
    @param timeout: Number of seconds after which to reissue the query.
    When the last timeout expires, the query is considered failed.
    
    @rtype: C{Deferred}
    """
    return getResolver().lookupHostInfo(name, timeout)

def lookupMailboxInfo(name, timeout=None):
    """
    Perform an MINFO record lookup.

    @type name: C{str}
    @param name: DNS name to resolve.
    
    @type timeout: Sequence of C{int}
    @param timeout: Number of seconds after which to reissue the query.
    When the last timeout expires, the query is considered failed.
    
    @rtype: C{Deferred}
    """
    return getResolver().lookupMailboxInfo(name, timeout)

def lookupText(name, timeout=None):
    """
    Perform a TXT record lookup.

    @type name: C{str}
    @param name: DNS name to resolve.
    
    @type timeout: Sequence of C{int}
    @param timeout: Number of seconds after which to reissue the query.
    When the last timeout expires, the query is considered failed.
    
    @rtype: C{Deferred}
    """
    return getResolver().lookupText(name, timeout)

def lookupResponsibility(name, timeout=None):
    """
    Perform an RP record lookup.

    @type name: C{str}
    @param name: DNS name to resolve.
    
    @type timeout: Sequence of C{int}
    @param timeout: Number of seconds after which to reissue the query.
    When the last timeout expires, the query is considered failed.
    
    @rtype: C{Deferred}
    """
    return getResolver().lookupResponsibility(name, timeout)

def lookupAFSDatabase(name, timeout=None):
    """
    Perform an AFSDB record lookup.

    @type name: C{str}
    @param name: DNS name to resolve.
    
    @type timeout: Sequence of C{int}
    @param timeout: Number of seconds after which to reissue the query.
    When the last timeout expires, the query is considered failed.
    
    @rtype: C{Deferred}
    """
    return getResolver().lookupAFSDatabase(name, timeout)

def lookupZone(name, timeout=None):
    """
    Perform an AXFR record lookup.

    @type name: C{str}
    @param name: DNS name to resolve.
    
    @type timeout: C{int}
    @param timeout: When this timeout expires, the query is considered failed.
    
    @rtype: C{Deferred}
    """
    # XXX: timeout here is not a list of ints, it is a single int.
    return getResolver().lookupZone(name, timeout)

def lookupAllRecords(name, timeout=None):
    """
    ALL_RECORD lookup.

    @type name: C{str}
    @param name: DNS name to resolve.
    
    @type timeout: Sequence of C{int}
    @param timeout: Number of seconds after which to reissue the query.
    When the last timeout expires, the query is considered failed.
    
    @rtype: C{Deferred}
    """
    return getResolver().lookupAllRecords(name, timeout)

