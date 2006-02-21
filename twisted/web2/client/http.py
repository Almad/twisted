from twisted.internet import defer, protocol
from twisted.protocols import basic, policies
from twisted.web2 import stream as stream_mod, http, http_headers, responsecode
from twisted.web2.channel import http as httpchan
from twisted.web2.channel.http import PERSIST_NO_PIPELINE, PERSIST_PIPELINE

#from twisted.python.util import tracer

class ProtocolError(Exception):
    pass

class ClientRequest(object):
    def __init__(self, method, uri, headers, stream):
        self.method = method
        self.uri = uri
        if isinstance(headers, http_headers.Headers):
            self.headers = headers
        else:
            self.headers = http_headers.Headers(headers or {})
            
        if stream is not None:
            self.stream = stream_mod.IByteStream(stream)
        else:
            self.stream = None

class HTTPClientChannelRequest(httpchan.HTTPParser):
    parseCloseAsEnd = True
    outgoing_version = "HTTP/1.1"
    chunkedOut = False
    finished = False
    
    closeAfter = False
    
    def __init__(self, channel, request, closeAfter):
        httpchan.HTTPParser.__init__(self, channel)
        self.request = request
        self.closeAfter = closeAfter
        self.transport = self.channel.transport
        self.responseDefer = defer.Deferred()
        
    def submit(self):
        l = []
        request = self.request
        if request.method == "HEAD":
            # No incoming data will arrive.
            self.length = 0
        
        l.append('%s %s %s\r\n' % (request.method, request.uri,
                                   self.outgoing_version))
        if request.headers is not None:
            for name, valuelist in request.headers.getAllRawHeaders():
                for value in valuelist:
                    l.append("%s: %s\r\n" % (name, value))
        
        if request.stream is not None:
            if request.stream.length is not None:
                l.append("%s: %s\r\n" % ('Content-Length', request.stream.length))
            else:
                # Got a stream with no length. Send as chunked and hope, against
                # the odds, that the server actually supports chunked uploads.
                l.append("%s: %s\r\n" % ('Transfer-Encoding', 'chunked'))
                self.chunkedOut = True

        if self.closeAfter:
            l.append("%s: %s\r\n" % ('Connection', 'close'))
        else:
            l.append("%s: %s\r\n" % ('Connection', 'Keep-Alive'))
        
        l.append("\r\n")
        self.transport.writeSequence(l)
        
        d = stream_mod.StreamProducer(request.stream).beginProducing(self)
        d.addCallback(self._finish).addErrback(self._error)

    def registerProducer(self, producer, streaming):
        """Register a producer.
        """
        self.transport.registerProducer(producer, streaming)

    def unregisterProducer(self):
        self.transport.unregisterProducer()
        
    def write(self, data):
        if not data:
            return
        elif self.chunkedOut:
            self.transport.writeSequence(("%X\r\n" % len(data), data, "\r\n"))
        else:
            self.transport.write(data)

    def _finish(self, x):
        """We are finished writing data."""
        if self.chunkedOut:
            # write last chunk and closing CRLF
            self.transport.write("0\r\n\r\n")
        
        self.finished = True
        self.channel.requestWriteFinished(self)
        del self.transport

    def _error(self, err):
        self.abortParse()
        self.responseDefer.errback(err)

    def _abortWithError(self, errcode, text):
        self.abortParse()
        self.responseDefer.errback(ProtocolError(text))

    def connectionLost(self, reason):
        ### FIXME!
        pass
    
    def gotInitialLine(self, initialLine):
        parts = initialLine.split(' ', 2)
        
        # Parse the initial request line
        if len(parts) != 3:
            self._abortWithError(responsecode.BAD_REQUEST, 'Bad response line: %s' % initialLine)
            return

        strversion, self.code, message = parts
        
        try:
            protovers = http.parseVersion(strversion)
            if protovers[0] != 'http':
                raise ValueError()
        except ValueError:
            self._abortWithError(responsecode.BAD_REQUEST, "Unknown protocol: %s" % strversion)
            return
        
        self.version = protovers[1:3]

        # Ensure HTTP 0 or HTTP 1.
        if self.version[0] != 1:
            self._abortWithError(responsecode.HTTP_VERSION_NOT_SUPPORTED, 'Only HTTP 1.x is supported.')
            return

    ## FIXME: Actually creates Response, function is badly named!
    def createRequest(self):
        self.stream = stream_mod.ProducerStream()
        self.response = http.Response(self.code, self.inHeaders, self.stream)
        self.stream.registerProducer(self, True)
        
        del self.inHeaders

    ## FIXME: Actually processes Response, function is badly named!
    def processRequest(self):
        self.responseDefer.callback(self.response)
        
    def handleContentChunk(self, data):
        self.stream.write(data)

    def handleContentComplete(self):
        self.stream.finish()

class EmptyHTTPClientManager(object):
    def clientBusy(self, proto):
        pass
    
    def clientIdle(self, proto):
        pass

    def clientPipelining(self, proto):
        pass
    
    def clientGone(self, proto):
        pass
    

class HTTPClientProtocol(basic.LineReceiver, policies.TimeoutMixin, object):
    """A HTTP 1.1 Client with request pipelining support."""
    
    chanRequest = None
    maxHeaderLength = 10240
    firstLine = 1
    readPersistent = PERSIST_NO_PIPELINE
    
    # inputTimeOut should be pending whenever a complete request has
    # been written but the complete response has not yet been
    # received, and be reset every time data is received.
    inputTimeOut = 60 * 4

    def __init__(self, manager=None):
        self.outRequest = None
        self.inRequests = []
        if manager is None:
            manager = EmptyHTTPClientManager()
        self.manager = manager

    def lineReceived(self, line):
        if not self.inRequests:
            # server sending random unrequested data.
            self.transport.loseConnection()
            return

        # If not currently writing this request, set timeout
        if self.inRequests[0] is not self.outRequest:
            self.setTimeout(self.inputTimeOut)
            
        if self.firstLine:
            self.firstLine = 0
            self.inRequests[0].gotInitialLine(line)
        else:
            self.inRequests[0].lineReceived(line)

    def rawDataReceived(self, data):
        if not self.inRequests:
            print "Extra raw data!"
            # server sending random unrequested data.
            self.transport.loseConnection()
            return
        
        # If not currently writing this request, set timeout
        if self.inRequests[0] is not self.outRequest:
            self.setTimeout(self.inputTimeOut)
            
        self.inRequests[0].rawDataReceived(data)
        
    def submitRequest(self, request, closeAfter=True):
        # Assert we're in a valid state to submit more
        assert self.outRequest is None
        assert ((self.readPersistent is PERSIST_NO_PIPELINE and not self.inRequests)
                or self.readPersistent is PERSIST_PIPELINE)
        
        self.manager.clientBusy(self)
        if closeAfter:
            self.readPersistent = False
        
        self.outRequest = chanRequest = HTTPClientChannelRequest(self, request, closeAfter)
        self.inRequests.append(chanRequest)
        
        chanRequest.submit()
        return chanRequest.responseDefer

    def requestWriteFinished(self, request):
        assert request is self.outRequest
        
        self.outRequest = None
        # Tell the manager if more requests can be submitted.
        self.setTimeout(self.inputTimeOut)
        if self.readPersistent is PERSIST_PIPELINE:
            self.manager.clientPipelining(self)

    def requestReadFinished(self, request):
        assert self.inRequests[0] is request
        
        del self.inRequests[0]
        self.firstLine = True
        
        if not self.inRequests:
            if self.readPersistent:
                self.setTimeout(None)
                self.manager.clientIdle(self)
            else:
#                 print "No more requests, closing"
                self.transport.loseConnection()

    def setReadPersistent(self, persist):
        self.readPersistent = persist
        if not persist:
            # Tell all requests but first to abort.
            for request in self.inRequests[1:]:
                request.connectionLost(None)
            del self.inRequests[1:]
    
    def connectionLost(self, reason):
        self.readPersistent = False
        self.setTimeout(None)
        self.manager.clientGone(self)
        # Tell all requests to abort.
        for request in self.inRequests:
            if request is not None:
                request.connectionLost(reason)
    
    #isLastRequest = tracer(isLastRequest)
    #lineReceived = tracer(lineReceived)
    #rawDataReceived = tracer(rawDataReceived)
    #connectionLost = tracer(connectionLost)
    #requestReadFinished = tracer(requestReadFinished)
    #requestWriteFinished = tracer(requestWriteFinished)
    #submitRequest = tracer(submitRequest)
    

def testConn(host):
    from twisted.internet import reactor
    d = protocol.ClientCreator(reactor, HTTPClientProtocol).connectTCP(host, 80)
    def gotResp(resp, num):
        def print_(n):
            print "DATA %s: %r" % (num, n)
        def printdone(n):
            print "DONE %s" % num
        print "GOT RESPONSE %s: %s" % (num, resp)
        stream_mod.readStream(resp.stream, print_).addCallback(printdone)
    def sendReqs(proto):
        proto.submitRequest(ClientRequest("GET", "/", {'Host':host}, None)).addCallback(gotResp, 1)
        proto.submitRequest(ClientRequest("GET", "/foo", {'Host':host}, None)).addCallback(gotResp, 2)
    d.addCallback(sendReqs)
    del d
    reactor.run()

