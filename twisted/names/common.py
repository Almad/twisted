
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

import operator, sys, socket, random

from twisted.protocols import dns
from twisted.internet import defer, error
from twisted.python import failure, log

EMPTY_RESULT = (), (), ()

class ResolverBase:
    typeToMethod = None

    def __init__(self):
        self.typeToMethod = {}
        for (k, v) in typeToMethod.items():
            self.typeToMethod[k] = getattr(self, v)

    def query(self, query, timeout = None):
        try:
            return self.typeToMethod[query.type](str(query.name), timeout)
        except KeyError, e:
            return defer.fail(failure.Failure(NotImplementedError(str(self.__class__) + " " + str(query.type))))

    def _lookup(self, name, cls, type, timeout):
        raise NotImplementedError("ResolverBase._lookup")

    def lookupAddress(self, name, timeout = None):
        return self._lookup(name, dns.IN, dns.A, timeout)

    def lookupIPV6Address(self, name, timeout = None):
        return self._lookup(name, dns.IN, dns.AAAA, timeout)

    def lookupAddress6(self, name, timeout = None):
        return self._lookup(name, dns.IN, dns.A6, timeout)

    def lookupMailExchange(self, name, timeout = None):
        return self._lookup(name, dns.IN, dns.MX, timeout)

    def lookupNameservers(self, name, timeout = None):
        return self._lookup(name, dns.IN, dns.NS, timeout)

    def lookupCanonicalName(self, name, timeout = None):
        return self._lookup(name, dns.IN, dns.CNAME, timeout)

    def lookupMailBox(self, name, timeout = None):
        return self._lookup(name, dns.IN, dns.MB, timeout)

    def lookupMailGroup(self, name, timeout = None):
        return self._lookup(name, dns.IN, dns.MG, timeout)

    def lookupMailRename(self, name, timeout = None):
        return self._lookup(name, dns.IN, dns.MR, timeout)

    def lookupPointer(self, name, timeout = None):
        return self._lookup(name, dns.IN, dns.PTR, timeout)

    def lookupAuthority(self, name, timeout = None):
        return self._lookup(name, dns.IN, dns.SOA, timeout)

    def lookupNull(self, name, timeout = None):
        return self._lookup(name, dns.IN, dns.NULL, timeout)

    def lookupWellKnownServices(self, name, timeout = None):
        return self._lookup(name, dns.IN, dns.WKS, timeout)

    def lookupService(self, name, timeout = None):
        return self._lookup(name, dns.IN, dns.SRV, timeout)

    def lookupHostInfo(self, name, timeout = None):
        return self._lookup(name, dns.IN, dns.HINFO, timeout)

    def lookupMailboxInfo(self, name, timeout = None):
        return self._lookup(name, dns.IN, dns.MINFO, timeout)

    def lookupText(self, name, timeout = None):
        return self._lookup(name, dns.IN, dns.TXT, timeout)

    def lookupResponsibility(self, name, timeout = None):
        return self._lookup(name, dns.IN, dns.RP, timeout)

    def lookupAFSDatabase(self, name, timeout = None):
        return self._lookup(name, dns.IN, dns.AFSDB, timeout)

    def lookupZone(self, name, timeout = None):
        return self._lookup(name, dns.IN, dns.AXFR, timeout)

    def lookupAllRecords(self, name, timeout = None):
        return self._lookup(name, dns.IN, dns.ALL_RECORDS, timeout)

    def getHostByName(self, name, timeout = None, effort = 10):
        # XXX - respect timeout
        return self._lookup(name, dns.IN, dns.ALL_RECORDS, timeout).addCallback(
            self._cbRecords, name, effort
        )

    def _cbRecords(self, (ans, auth, add), name, effort):
        result = extractRecord(self, dns.Name(name), ans + auth + add, effort)
        if not result:
            raise error.DNSLookupError(name)
        return result


if hasattr(socket, 'inet_ntop'):
    def extractRecord(resolver, name, answers, level = 10):
        if not level:
            return None
        for r in answers:
            if r.name == name and r.type == dns.A6:
                return socket.inet_ntop(socket.AF_INET6, r.payload.address)
        for r in answers:
            if r.name == name and r.type == dns.AAAA:
                return socket.inet_ntop(socket.AF_INET6, r.payload.address)
        for r in answers:
            if r.name == name and r.type == dns.A:
                return socket.inet_ntop(socket.AF_INET, r.payload.address)
        for r in answers:
            if r.name == name and r.type == dns.CNAME:
                result = extractRecord(resolver, r.payload.name, answers, level - 1)
                if not result:
                    return resolver.getHostByName(str(r.payload.name), effort=level-1)
                return result
        
else:
    def extractRecord(resolver, name, answers, level = 10):
        if not level:
            return None
        for r in answers:
            if r.name == name and r.type == dns.A:
                return socket.inet_ntoa(r.payload.address)
        for r in answers:
            if r.name == name and r.type == dns.CNAME:
                result = extractRecord(resolver, r.payload.name, answers, level - 1)
                if not result:
                    return resolver.getHostByName(str(r.payload.name), effort=level-1)
                return result

typeToMethod = {
    dns.A:     'lookupAddress',
    dns.AAAA:  'lookupIPV6Address',
    dns.A6:    'lookupAddress6',
    dns.NS:    'lookupNameservers',
    dns.CNAME: 'lookupCanonicalName',
    dns.SOA:   'lookupAuthority',
    dns.MB:    'lookupMailBox',
    dns.MG:    'lookupMailGroup',
    dns.MR:    'lookupMailRename',
    dns.NULL:  'lookupNull',
    dns.WKS:   'lookupWellKnownServices',
    dns.PTR:   'lookupPointer',
    dns.HINFO: 'lookupHostInfo',
    dns.MINFO: 'lookupMailboxInfo',
    dns.MX:    'lookupMailExchange',
    dns.TXT:   'lookupText',
    
    dns.RP:    'lookupResponsibility',
    dns.AFSDB: 'lookupAFSDatabase',
    dns.SRV:   'lookupService',
    
    dns.AXFR:         'lookupZone',
    dns.ALL_RECORDS:  'lookupAllRecords',
}
