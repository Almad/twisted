
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

"""Test HTTP support."""

from __future__ import nested_scopes

from twisted.trial import unittest
from twisted.protocols import http, loopback
from twisted.internet import protocol
from twisted.test.test_protocols import StringIOWithoutClosing
import string, random


class DateTimeTest(unittest.TestCase):
    """Test date parsing functions."""

    def testRoundtrip(self):
        for i in range(10000):
            time = random.randint(0, 2000000000)
            timestr = http.datetimeToString(time)
            time2 = http.stringToDatetime(timestr)
            self.assertEquals(time, time2)


class OrderedDict:

    def __init__(self, dict):
        self.dict = dict
        self.l = dict.keys()

    def __setitem__(self, k, v):
        self.l.append(k)
        self.dict[k] = v

    def __getitem__(self, k):
        return self.dict[k]

    def items(self):
        result = []
        for i in self.l:
            result.append((i, self.dict[i]))
        return result

    def __getattr__(self, attr):
        return getattr(self.dict, attr)


class DummyHTTPHandler(http.Request):

    def process(self):
        self.headers = OrderedDict(self.headers)
        self.content.seek(0, 0)
        data = self.content.read()
        length = self.getHeader('content-length')
        request = "'''\n"+str(length)+"\n"+data+"'''\n"
        self.setResponseCode(200)
        self.setHeader("Request", self.uri)
        self.setHeader("Command", self.method)
        self.setHeader("Version", self.clientproto)
        self.setHeader("Content-Length", len(request))
        self.write(request)
        self.finish()


class LoopbackHTTPClient(http.HTTPClient):

    def connectionMade(self):
        self.sendCommand("GET", "/foo/bar")
        self.sendHeader("Content-Length", 10)
        self.endHeaders()
        self.transport.write("0123456789")


class HTTP1_0TestCase(unittest.TestCase):

    requests = '''\
GET / HTTP/1.0

GET / HTTP/1.1
Accept: text/html

'''
    requests = string.replace(requests, '\n', '\r\n')

    expected_response = "HTTP/1.0 200 OK\015\012Request: /\015\012Command: GET\015\012Version: HTTP/1.0\015\012Content-length: 13\015\012\015\012'''\012None\012'''\012"

    def testBuffer(self):
        b = StringIOWithoutClosing()
        a = http.HTTPChannel()
        a.requestFactory = DummyHTTPHandler
        a.makeConnection(protocol.FileWrapper(b))
        # one byte at a time, to stress it.
        for byte in self.requests:
            a.dataReceived(byte)
        a.connectionLost(IOError("all one"))
        value = b.getvalue()
        if value != self.expected_response:
            for i in range(len(value)):
                if len(self.expected_response) <= i:
                    print `value[i-5:i+10]`, `self.expected_response[i-5:i+10]`
                elif value[i] != self.expected_response[i]:
                    print `value[i-5:i+10]`, `self.expected_response[i-5:i+10]`
                    break
            print '---VALUE---'
            print repr(value)
            print '---EXPECTED---'
            print repr(self.expected_response)
            raise AssertionError


class HTTP1_1TestCase(HTTP1_0TestCase):

    requests = '''\
GET / HTTP/1.1
Accept: text/html

POST / HTTP/1.1
Content-Length: 10

0123456789POST / HTTP/1.1
Content-Length: 10

0123456789HEAD / HTTP/1.1

'''
    requests = string.replace(requests, '\n', '\r\n')

    expected_response = "HTTP/1.1 200 OK\015\012Request: /\015\012Command: GET\015\012Version: HTTP/1.1\015\012Content-length: 13\015\012\015\012'''\012None\012'''\012HTTP/1.1 200 OK\015\012Request: /\015\012Command: POST\015\012Version: HTTP/1.1\015\012Content-length: 21\015\012\015\012'''\01210\0120123456789'''\012HTTP/1.1 200 OK\015\012Request: /\015\012Command: POST\015\012Version: HTTP/1.1\015\012Content-length: 21\015\012\015\012'''\01210\0120123456789'''\012HTTP/1.1 200 OK\015\012Request: /\015\012Command: HEAD\015\012Version: HTTP/1.1\015\012Content-length: 13\015\012\015\012"

class HTTP1_1_close_TestCase(HTTP1_0TestCase):

    requests = '''\
GET / HTTP/1.1
Accept: text/html
Connection: close

GET / HTTP/1.0

'''

    requests = string.replace(requests, '\n', '\r\n')

    expected_response = "HTTP/1.1 200 OK\015\012Connection: close\015\012Request: /\015\012Command: GET\015\012Version: HTTP/1.1\015\012Content-length: 13\015\012\015\012'''\012None\012'''\012"


class HTTP0_9TestCase(HTTP1_0TestCase):

    requests = '''\
GET /
'''
    requests = string.replace(requests, '\n', '\r\n')

    expected_response = "HTTP/1.1 400 Bad Request\r\n\r\n"


class HTTPLoopbackTestCase(unittest.TestCase):

    expectedHeaders = {'request' : '/foo/bar',
                       'command' : 'GET',
                       'version' : 'HTTP/1.0',
                       'content-length' : '21'}
    numHeaders = 0
    gotStatus = 0
    gotResponse = 0
    gotEndHeaders = 0

    def _handleStatus(self, version, status, message):
        self.gotStatus = 1
        self.assertEquals(version, "HTTP/1.0")
        self.assertEquals(status, "200")

    def _handleResponse(self, data):
        self.gotResponse = 1
        self.assertEquals(data, "'''\n10\n0123456789'''\n")

    def _handleHeader(self, key, value):
        self.numHeaders = self.numHeaders + 1
        self.assertEquals(self.expectedHeaders[string.lower(key)], value)

    def _handleEndHeaders(self):
        self.gotEndHeaders = 1
        self.assertEquals(self.numHeaders, 4)

    def testLoopback(self):
        server = http.HTTPChannel()
        server.requestFactory = DummyHTTPHandler
        client = LoopbackHTTPClient()
        client.handleResponse = self._handleResponse
        client.handleHeader = self._handleHeader
        client.handleEndHeaders = self._handleEndHeaders
        client.handleStatus = self._handleStatus
        loopback.loopback(server, client)
        if not (self.gotStatus and self.gotResponse and self.gotEndHeaders):
            raise RuntimeError, "didn't got all callbacks %s" % [self.gotStatus, self.gotResponse, self.gotEndHeaders]
        del self.gotEndHeaders
        del self.gotResponse
        del self.gotStatus
        del self.numHeaders


class PRequest:
    """Dummy request for persistence tests."""

    def __init__(self, **headers):
        self.received_headers = headers
        self.headers = {}

    def getHeader(self, k):
        return self.received_headers.get(k, '')

    def setHeader(self, k, v):
        self.headers[k] = v


class PersistenceTestCase(unittest.TestCase):
    """Tests for persistent HTTP connections."""

    ptests = [#(PRequest(connection="Keep-Alive"), "HTTP/1.0", 1, {'connection' : 'Keep-Alive'}),
              (PRequest(), "HTTP/1.0", 0, {'connection': None}),
              (PRequest(connection="close"), "HTTP/1.1", 0, {'connection' : 'close'}),
              (PRequest(), "HTTP/1.1", 1, {'connection': None}),
              (PRequest(), "HTTP/0.9", 0, {'connection': None}),
              ]


    def testAlgorithm(self):
        c = http.HTTPChannel()
        for req, version, correctResult, resultHeaders in self.ptests:
            result = c.checkPersistence(req, version)
            self.assertEquals(result, correctResult)
            for header in resultHeaders.keys():
                self.assertEquals(req.headers.get(header, None), resultHeaders[header])


class ChunkingTestCase(unittest.TestCase):

    strings = ["abcv", "", "fdfsd423", "Ffasfas\r\n",
               "523523\n\rfsdf", "4234"]

    def testChunks(self):
        for s in self.strings:
            self.assertEquals((s, ''), http.fromChunk(http.toChunk(s)))

    def testConcatenatedChunks(self):
        chunked = string.join(map(http.toChunk, self.strings), '')
        result = []
        buffer = ""
        for c in chunked:
            buffer = buffer + c
            try:
                data, buffer = http.fromChunk(buffer)
                result.append(data)
            except ValueError:
                pass
        self.assertEquals(result, self.strings)



class ParsingTestCase(unittest.TestCase):

    def runRequest(self, httpRequest, requestClass):
        httpRequest = httpRequest.replace("\n", "\r\n")
        b = StringIOWithoutClosing()
        a = http.HTTPChannel()
        a.requestFactory = requestClass
        a.makeConnection(protocol.FileWrapper(b))
        # one byte at a time, to stress it.
        for byte in httpRequest:
            a.dataReceived(byte)
        a.connectionLost(IOError("all done"))
        self.assertEquals(self.didRequest, 1)
        del self.didRequest

    def testHeaders(self):
        httpRequest = """\
GET / HTTP/1.0
Foo: bar
baz: 1 2 3

"""
        testcase = self

        class MyRequest(http.Request):
            def process(self):
                testcase.assertEquals(self.getHeader('foo'), 'bar')
                testcase.assertEquals(self.getHeader('Foo'), 'bar')
                testcase.assertEquals(self.getHeader('bAz'), '1 2 3')
                testcase.didRequest = 1
                self.finish()

        self.runRequest(httpRequest, MyRequest)

    def testCookies(self):
        httpRequest = '''\
GET / HTTP/1.0
Cookie: rabbit="eat carrot"; ninja=secret

'''
        testcase = self

        class MyRequest(http.Request):
            def process(self):
                testcase.assertEquals(self.getCookie('rabbit'), '"eat carrot"')
                testcase.assertEquals(self.getCookie('ninja'), 'secret')
                testcase.didRequest = 1
                self.finish()

        self.runRequest(httpRequest, MyRequest)

    def testGET(self):
        httpRequest = '''\
GET /?key=value&multiple=two+words&multiple=more%20words&empty= HTTP/1.0

'''
        testcase = self
        class MyRequest(http.Request):
            def process(self):
                testcase.assertEquals(self.method, "GET")
                testcase.assertEquals(self.args["key"], ["value"])
                testcase.assertEquals(self.args["empty"], [""])
                testcase.assertEquals(self.args["multiple"], ["two words", "more words"])
                testcase.didRequest = 1
                self.finish()

        self.runRequest(httpRequest, MyRequest)

    def testPOST(self):
        query = 'key=value&multiple=two+words&multiple=more%20words&empty='
        httpRequest = '''\
POST / HTTP/1.0
Content-Length: %d
Content-Type: application/x-www-form-urlencoded

%s''' % (len(query), query)

        testcase = self
        class MyRequest(http.Request):
            def process(self):
                testcase.assertEquals(self.method, "POST")
                testcase.assertEquals(self.args["key"], ["value"])
                testcase.assertEquals(self.args["empty"], [""])
                testcase.assertEquals(self.args["multiple"], ["two words", "more words"])
                testcase.didRequest = 1
                self.finish()

        self.runRequest(httpRequest, MyRequest)
