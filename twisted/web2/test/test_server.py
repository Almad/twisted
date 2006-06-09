"""
A test harness for the twisted.web2 server.
"""

from zope.interface import implements
from twisted.web2 import http, http_headers, iweb, server
from twisted.web2 import resource, stream
from twisted.trial import unittest, util
from twisted.internet import reactor, defer, address, error as ti_error

class SimpleRequest(server.Request):
    """I can be used in cases where a Request object is necessary
    but it is benificial to bypass the chanRequest
    """

    clientproto = (1,1)
    
    def __init__(self, site, method, uri, headers=None, content=None):
        if not headers:
            headers = http_headers.Headers(headers)
            
        super(SimpleRequest, self).__init__(
            site=site,
            chanRequest=None,
            command=method,
            path=uri,
            version=self.clientproto,
            contentLength=len(content or ''),
            headers=headers)

        self.stream = stream.MemoryStream(content or '')

        self.remoteAddr = address.IPv4Address('TCP', '127.0.0.1', 0)
        self._parseURL()
        self.host = 'localhost'
        self.port = 8080

    def writeResponse(response):
        pass


class TestChanRequest:
    implements(iweb.IChanRequest)

    hostInfo = address.IPv4Address('TCP', 'host', 80), False
    remoteHost = address.IPv4Address('TCP', 'remotehost', 34567)

    
    def __init__(self, site, method, prepath, uri, length=None,
                 headers=None, version=(1,1), content=None):
        self.site = site
        self.method = method
        self.prepath = prepath
        self.uri = uri
        if headers is None:
            headers = http_headers.Headers()
        self.headers = headers
        self.http_version = version
        # Anything below here we do not pass as arguments
        self.request = server.Request(self,
                                      self.method,
                                      self.uri,
                                      self.http_version,
                                      length,
                                      self.headers,
                                      site=self.site,
                                      prepathuri=self.prepath)
        
        if content is not None:
            self.request.handleContentChunk(content)
            self.request.handleContentComplete()
            
        self.code = None
        self.responseHeaders = None
        self.data = ''
        self.deferredFinish = defer.Deferred()

    def writeIntermediateResponse(code, headers=None):
        pass
    
    def writeHeaders(self, code, headers):
        self.responseHeaders = headers
        self.code = code
        
    def write(self, data):
        self.data += data

    def finish(self, failed=False):
        result = self.code, self.responseHeaders, self.data, failed
        self.finished = True
        self.deferredFinish.callback(result)

    def abortConnection(self):
        self.finish(failed=True)
        
    def registerProducer(self, producer, streaming):
        pass

    def unregisterProducer(self):
        pass

    def getHostInfo(self):
        return self.hostInfo

    def getRemoteHost(self):
        return self.remoteHost
    

class BaseTestResource(resource.Resource):
    responseCode = 200
    responseText = 'This is a fake resource.'
    responseHeaders = {}
    addSlash = False
    
    def __init__(self, children=[]):
        """
        @type children: C{list} of C{tuple}
        @param children: a list of ('path', resource) tuples
        """
        for i in children:
            self.putChild(i[0], i[1])

    def render(self, req):
        return http.Response(self.responseCode, headers=self.responseHeaders,
                             stream=self.responseStream())

    def responseStream(self):
        return stream.MemoryStream(self.responseText)

_unset = object()
class BaseCase(unittest.TestCase):
    """
    Base class for test cases that involve testing the result
    of arbitrary HTTP(S) queries.
    """
    
    method = 'GET'
    version = (1, 1)
    wait_timeout = 5.0
    
    def chanrequest(self, root, uri, length, headers, method, version, prepath, content):
        site = server.Site(root)
        return TestChanRequest(site, method, prepath, uri, length, headers, version, content)

    def getResponseFor(self, root, uri, headers={},
                       method=None, version=None, prepath='', content=None, length=_unset):
        if not isinstance(headers, http_headers.Headers):
            headers = http_headers.Headers(headers)
        if length is _unset:
            if content is not None:
                length = len(content)
            else:
                length = 0
            
        if method is None:
            method = self.method
        if version is None:
            version = self.version

        cr = self.chanrequest(root, uri, length, headers, method, version, prepath, content)
        cr.request.process()
        return cr.deferredFinish

    def assertResponse(self, request_data, expected_response, failure=False):
        """
        @type request_data: C{tuple}
        @type expected_response: C{tuple}
        @param request_data: A tuple of arguments to pass to L{getResponseFor}:
                             (root, uri, headers, method, version, prepath).
                             Root resource and requested URI are required,
                             and everything else is optional.
        @param expected_response: A 3-tuple of the expected response:
                                  (responseCode, headers, htmlData)
        """
        d = self.getResponseFor(*request_data)
        d.addCallback(self._cbGotResponse, expected_response, failure)
        
        return d

    def _cbGotResponse(self, (code, headers, data, failed), expected_response, expectedfailure=False):
        expected_code, expected_headers, expected_data = expected_response
        self.assertEquals(code, expected_code)
        if expected_data is not None:
            self.assertEquals(data, expected_data)
        for key, value in expected_headers.iteritems():
            self.assertEquals(headers.getHeader(key), value)
        self.assertEquals(failed, expectedfailure)

class SampleWebTest(BaseCase):
    class SampleTestResource(BaseTestResource):
        addSlash = True
        def child_validChild(self, req):
            f = BaseTestResource()
            f.responseCode = 200
            f.responseText = 'This is a valid child resource.'
            return f

        def child_missingChild(self, req):
            f = BaseTestResource()
            f.responseCode = 404
            f.responseStream = lambda self: None
            return f

        def child_remoteAddr(self, req):
            f = BaseTestResource()
            f.responseCode = 200
            f.responseText = 'Remote Addr: %r' % req.remoteAddr.host
            return f

    def setUp(self):
        self.root = self.SampleTestResource()

    def test_root(self):
        return self.assertResponse(
            (self.root, 'http://host/'),
            (200, {}, 'This is a fake resource.'))

    def test_validChild(self):
        return self.assertResponse(
            (self.root, 'http://host/validChild'),
            (200, {}, 'This is a valid child resource.'))

    def test_invalidChild(self):
        return self.assertResponse(
            (self.root, 'http://host/invalidChild'),
            (404, {}, None))

    def test_remoteAddrExposure(self):
        return self.assertResponse(
            (self.root, 'http://host/remoteAddr'),
            (200, {}, "Remote Addr: 'remotehost'"))

    def test_leafresource(self):
        class TestResource(resource.LeafResource):
            def render(self, req):
                return http.Response(stream="prepath:%s postpath:%s" % (
                        req.prepath,
                        req.postpath))

        return self.assertResponse(
            (TestResource(), 'http://host/consumed/path/segments'),
            (200, {}, "prepath:[] postpath:['consumed', 'path', 'segments']"))

    def test_redirectResource(self):
        redirectResource = resource.RedirectResource(scheme='https',
                                                     host='localhost',
                                                     port=443,
                                                     path='/foo',
                                                     querystring='bar=baz')

        return self.assertResponse(
            (redirectResource, 'http://localhost/'),
            (301, {'location': 'https://localhost/foo?bar=baz'}, None))
    

class URLParsingTest(BaseCase):
    class TestResource(resource.LeafResource):
        def render(self, req):
            return http.Response(stream="Host:%s, Path:%s"%(req.host, req.path))
            
    def setUp(self):
        self.root = self.TestResource()

    def test_normal(self):
        return self.assertResponse(
            (self.root, '/path', {'Host':'host'}),
            (200, {}, 'Host:host, Path:/path'))

    def test_fullurl(self):
        return self.assertResponse(
            (self.root, 'http://host/path'),
            (200, {}, 'Host:host, Path:/path'))

    def test_strangepath(self):
        # Ensure that the double slashes don't confuse it
        return self.assertResponse(
            (self.root, '//path', {'Host':'host'}),
            (200, {}, 'Host:host, Path://path'))

    def test_strangepathfull(self):
        return self.assertResponse(
            (self.root, 'http://host//path'),
            (200, {}, 'Host:host, Path://path'))

class TestDeferredRendering(BaseCase):
    class ResourceWithDeferreds(BaseTestResource):
        addSlash=True
        responseText = 'I should be wrapped in a Deferred.'
        def render(self, req):
            d = defer.Deferred()
            reactor.callLater(
                0, d.callback, BaseTestResource.render(self, req))
            return d

        def child_deferred(self, req):
            d = defer.Deferred()
            reactor.callLater(0, d.callback, BaseTestResource())
            return d
        
    def test_deferredRootResource(self):
        return self.assertResponse(
            (self.ResourceWithDeferreds(), 'http://host/'),
            (200, {}, 'I should be wrapped in a Deferred.'))

    def test_deferredChild(self):
        return self.assertResponse(
            (self.ResourceWithDeferreds(), 'http://host/deferred'),
            (200, {}, 'This is a fake resource.'))

class RedirectResourceTest(BaseCase):
    def html(url):
        return "<html><head><title>Moved Permanently</title></head><body><h1>Moved Permanently</h1><p>Document moved to %s.</p></body></html>" % (url,)
    html = staticmethod(html)

    def test_noRedirect(self):
        # This is useless, since it's a loop, but hey
        ds = []
        for url in ("http://host/", "http://host/foo"):
            ds.append(self.assertResponse(
                (resource.RedirectResource(), url),
                (301, {"location": url}, self.html(url))
            ))
        return defer.DeferredList(ds)

    def test_hostRedirect(self):
        ds = []
        for url1, url2 in (
            ("http://host/", "http://other/"),
            ("http://host/foo", "http://other/foo"),
        ):
            ds.append(self.assertResponse(
                (resource.RedirectResource(host="other"), url1),
                (301, {"location": url2}, self.html(url2))
            ))
        return defer.DeferredList(ds)

    def test_pathRedirect(self):
        root = BaseTestResource()
        redirect = resource.RedirectResource(path="/other")
        root.putChild("r", redirect)

        ds = []
        for url1, url2 in (
            ("http://host/r", "http://host/other"),
            ("http://host/r/foo", "http://host/other"),
        ):
            ds.append(self.assertResponse(
                (resource.RedirectResource(path="/other"), url1),
                (301, {"location": url2}, self.html(url2))
            ))
        return defer.DeferredList(ds)

class RememberURIs(BaseCase):
    def test_requestedResource(self):
        class EmptyResource(resource.Resource):
            def __init__(self, test):
                self.test = test

            def render(self, request):
                self.test.assertEquals(request.urlForResource(self), self.expectedURI)
                return 201

        root = EmptyResource(self)
        root.expectedURI = "/"

        child = EmptyResource(self)
        child.expectedURI = "/foo"

        root.putChild("foo", child)

        request = SimpleRequest(server.Site(root), "GET", "/foo")

        self.getResponseFor(root, "/foo")

    def test_locateResource(self):
        root = resource.Resource()
        child = resource.Resource()
        root.putChild("foo", child)

        request = SimpleRequest(server.Site(root), "GET", "/foo")

        def _foundCb(found):
            self.assertEquals("/foo", request.urlForResource(found))

        d = defer.maybeDeferred(request.locateResource, "/foo")
        d.addCallback(_foundCb)

    def test_deferredLocateChild(self):
        class DeferredLocateChild(resource.Resource):
            def locateChild(self, req, segments):
                return defer.maybeDeferred(
                    super(DeferredLocateChild, self).locateChild,
                    req, segments
                )

        root = DeferredLocateChild()
        child = resource.Resource()
        root.putChild("foo", child)

        request = SimpleRequest(server.Site(root), "GET", "/foo")

        def _foundCb(found):
            self.assertEquals("/foo", request.urlForResource(found))

        d = request.locateResource("/foo")
        d.addCallback(_foundCb)
        
