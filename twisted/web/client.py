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
"""HTTP client."""

from twisted.protocols import http
from twisted.internet import defer, protocol, reactor
from twisted.python import failure
import urlparse

class HTTPPageGetter(http.HTTPClient):

    quietLoss = 0

    def connectionMade(self):
        method = getattr(self.factory, 'method', 'GET')
        self.sendCommand(method, self.factory.url)
        self.sendHeader('Host', self.factory.host)
        self.sendHeader('User-Agent', self.factory.agent)
        for (key, value) in self.factory.headers.items():
            self.sendHeader(key, value)
        self.endHeaders()
        self.headers = {}
        data = getattr(self.factory, 'postdata', None)
        if data is not None:
            self.transport.write(data)

    def handleHeader(self, key, value):
        key = key.lower()
        l = self.headers[key] = self.headers.get(key, [])
        l.append(value)

    def handleStatus(self, version, status, message):
        self.version, self.status, self.message = version, status, message

    def handleEndHeaders(self):
        m = getattr(self, 'handleStatus_'+self.status, self.handleStatusDefault)
        m()

    def handleStatus_200(self):
        self.factory.gotHeaders(self.headers)

    def handleStatusDefault(self):
        self.factory.noPage(failure.Failure(ValueError(self.status,
                                                       self.message)))
        self.transport.loseConnection()


    def handleStatus_301(self):
        l = self.headers.get('location')
        if not l:
            self.handleStatusDefault()
        host, port, url = _parse(l[0])
        self.factory.host, self.factory.url = host, url
        reactor.connectTCP(host, port, self.factory)
        self.quietLoss = 1
        self.transport.loseConnection()

    handleStatus_302 = handleStatus_301

    def connectionLost(self, reason):
        if not self.quietLoss:
            http.HTTPClient.connectionLost(self, reason)
            self.factory.noPage(reason)

    def handleResponse(self, response):
        self.factory.page(response)


class HTTPPageDownloader(HTTPPageGetter):

    transmittingPage = 0

    def handleStatus_200(self):
        HTTPPageGetter.handleStatus_200(self)
        self.transmittingPage = 1
        self.factory.pageStart()

    def handleResponsePart(self, data):
        if self.transmittingPage:
            self.factory.pagePart(data)

    def handleResponseEnd(self):
        if self.transmittingPage:
            self.factory.pageEnd()
            self.transmittingPage = 0


class HTTPClientFactory(protocol.ClientFactory):

    headers = {}

    protocol = HTTPPageGetter

    def __init__(self, host, url, method='GET', postdata=None, headers=None, agent="Twisted PageGetter"):
        if headers is not None:
            self.headers = headers
        if postdata is not None:
            self.headers.setdefault('Content-Length', len(postdata))
        self.postdata = postdata
        self.method = method
        self.host = host
        self.url = url
        self.agent = agent
        self.waiting = 1
        self.deferred = defer.Deferred()

    def gotHeaders(self, headers):
        pass

    def page(self, page):
        if self.waiting:
            self.waiting = 0
            self.deferred.callback(page)

    def noPage(self, reason):
        if self.waiting:
            self.waiting = 0
            self.deferred.errback(reason)

    def clientConnectionFailed(self, _, reason):
        if self.waiting:
            self.waiting = 0
            self.deferred.errback(reason)

class HTTPDownloader(HTTPClientFactory):

    protocol = HTTPPageDownloader
    value = None

    def __init__(self, host, url, fileName, method='GET', postdata=None, headers=None, agent="Twisted client"):
        HTTPClientFactory.__init__(self, host, url, method=method, postdata=postdata, headers=headers, agent=agent)
        self.fileName = fileName
        self.deferred = defer.Deferred()
        self.waiting = 1
        self.file = None

    def pageStart(self):
        if self.waiting:
            self.waiting = 0
            self.file = open(self.fileName, 'w')

    def pageEnd(self):
        if self.file:
            self.file.close()
        self.deferred.callback(self.value)

    def pagePart(self, data):
        if self.file:
            self.file.write(data)


def _parse(url):
    parsed = urlparse.urlparse(url)
    url = urlparse.urlunparse(('','')+parsed[2:])
    host, port = parsed[1], 80
    if ':' in host:
        host, port = host.split(':')
        port = int(port)
    return host, port, url

def getPage(url, *args, **kwargs):
    '''download a web page

    Download a page. Return a deferred, which will
    callback with a page or errback with a description
    of the error.
    '''
    host, port, url = _parse(url)
    factory = HTTPClientFactory(host, url, *args, **kwargs)
    reactor.connectTCP(host, port, factory)
    return factory.deferred

def downloadPage(url, file, *args, **kwargs):
    host, port, url = _parse(url)
    factory = HTTPDownloader(host, url, file, *args, **kwargs)
    reactor.connectTCP(host, port, factory)
    return factory.deferred
