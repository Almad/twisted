# -*- test-case-name: twisted.web2.test.test_server -*-
# Copyright (c) 2001-2004 Twisted Matrix Laboratories.
# See LICENSE for details.


"""This is a web-sever which integrates with the twisted.internet
infrastructure.
"""

# System Imports
import cStringIO as StringIO

import cgi, time, urlparse
from urllib import unquote
from urlparse import urlsplit

import weakref

from zope.interface import implements
# Twisted Imports
from twisted.internet import defer
from twisted.python import log, failure

# Sibling Imports
from twisted.web2 import http, iweb, fileupload, responsecode
from twisted.web2 import http_headers
from twisted.web2.filter.range import rangefilter
from twisted.web2 import error

from twisted.web2 import version as web2_version
from twisted import __version__ as twisted_version

VERSION = "Twisted/%s TwistedWeb/%s" % (twisted_version, web2_version)
_errorMarker = object()


def defaultHeadersFilter(request, response):
    if not response.headers.hasHeader('server'):
        response.headers.setHeader('server', VERSION)
    if not response.headers.hasHeader('date'):
        response.headers.setHeader('date', time.time())
    return response
defaultHeadersFilter.handleErrors = True

def preconditionfilter(request, response):
    if request.method in ("GET", "HEAD"):
        http.checkPreconditions(request, response)
    return response

def doTrace(request):
    request = iweb.IRequest(request)
    txt = "%s %s HTTP/%d.%d\r\n" % (request.method, request.uri,
                                    request.clientproto[0], request.clientproto[1])

    l=[]
    for name, valuelist in request.headers.getAllRawHeaders():
        for value in valuelist:
            l.append("%s: %s\r\n" % (name, value))
    txt += ''.join(l)

    return http.Response(
        responsecode.OK,
        {'content-type': http_headers.MimeType('message', 'http')}, 
        txt)

def parsePOSTData(request):
    if request.stream.length == 0:
        return defer.succeed(None)
    
    parser = None
    ctype = request.headers.getHeader('content-type')

    if ctype is None:
        return defer.succeed(None)

    def updateArgs(data):
        args = data
        request.args.update(args)

    def updateArgsAndFiles(data):
        args, files = data
        request.args.update(args)
        request.files.update(files)

    def error(f):
        f.trap(fileupload.MimeFormatError)
        raise http.HTTPError(responsecode.BAD_REQUEST)
    
    if ctype.mediaType == 'application' and ctype.mediaSubtype == 'x-www-form-urlencoded':
        d = fileupload.parse_urlencoded(request.stream)
        d.addCallbacks(updateArgs, error)
        return d
    elif ctype.mediaType == 'multipart' and ctype.mediaSubtype == 'form-data':
        boundary = ctype.params.get('boundary')
        if boundary is None:
            return failure.Failure(fileupload.MimeFormatError("Boundary not specified in Content-Type."))
        d = fileupload.parseMultipartFormData(request.stream, boundary)
        d.addCallbacks(updateArgsAndFiles, error)
        return d
    else:
        raise http.HTTPError(responsecode.BAD_REQUEST)

class StopTraversal(object):
    """
    Indicates to Request._handleSegment that it should stop handling
    path segments.
    """
    pass


class Request(http.Request):
    """
    vars:
    site

    remoteAddr
    
    scheme
    host
    port
    path
    params
    querystring
    
    args
    files
    
    prepath
    postpath

    @ivar path: The path only (arguments not included).
    @ivar args: All of the arguments, including URL and POST arguments.
    @type args: A mapping of strings (the argument names) to lists of values.
                i.e., ?foo=bar&foo=baz&quux=spam results in
                {'foo': ['bar', 'baz'], 'quux': ['spam']}.

    """
    implements(iweb.IRequest)
    
    site = None
    _initialprepath = None
    responseFilters = [rangefilter, preconditionfilter,
                       error.defaultErrorHandler, defaultHeadersFilter]
    
    def __init__(self, *args, **kw):
        if kw.has_key('site'):
            self.site = kw['site']
            del kw['site']
        if kw.has_key('prepathuri'):
            self._initialprepath = kw['prepathuri']
            del kw['prepathuri']

        # Copy response filters from the class
        self.responseFilters = self.responseFilters[:]
        self.files = {}
        self.resources = []
        http.Request.__init__(self, *args, **kw)

    def addResponseFilter(self, f, atEnd=False):
        if atEnd:
            self.responseFilters.append(f)
        else:
            self.responseFilters.insert(0, f)

    def unparseURL(self, scheme=None, host=None, port=None,
                   path=None, params=None, querystring=None, fragment=None):
        """Turn the request path into a url string. For any pieces of
        the url that are not specified, use the value from the
        request. The arguments have the same meaning as the same named
        attributes of Request."""
        
        if scheme is None: scheme = self.scheme
        if host is None: host = self.host
        if port is None: port = self.port
        if path is None: path = self.path
        if params is None: params = self.params
        if querystring is None: query = self.querystring
        if fragment is None: fragment = ''
        
        if port == http.defaultPortForScheme.get(scheme, 0):
            hostport = host
        else:
            hostport = host + ':' + str(port)
        
        return urlparse.urlunparse((
            scheme, hostport, path,
            params, querystring, fragment))

    def _parseURL(self):
        if self.uri[0] == '/':
            # Can't use urlparse for request_uri because urlparse
            # wants to be given an absolute or relative URI, not just
            # an abs_path, and thus gets '//foo' wrong.
            self.scheme = self.host = self.path = self.params = self.querystring = ''
            if '?' in self.uri:
                self.path, self.querystring = self.uri.split('?', 1)
            else:
                self.path = self.uri
            if ';' in self.path:
                self.path, self.params = self.path.split(';', 1)
        else:
            # It is an absolute uri, use standard urlparse
            (self.scheme, self.host, self.path,
             self.params, self.querystring, fragment) = urlparse.urlparse(self.uri)

        if self.querystring:
            self.args = cgi.parse_qs(self.querystring, True)
        else:
            self.args = {}
        
        path = map(unquote, self.path[1:].split('/'))
        if self._initialprepath:
            # We were given an initial prepath -- this is for supporting
            # CGI-ish applications where part of the path has already
            # been processed
            prepath = map(unquote, self._initialprepath[1:].split('/'))
            
            if path[:len(prepath)] == prepath:
                self.prepath = prepath
                self.postpath = path[len(prepath):]
            else:
                self.prepath = []
                self.postpath = path
        else:
            self.prepath = []
            self.postpath = path
        #print "_parseURL", self.uri, (self.uri, self.scheme, self.host, self.path, self.params, self.querystring)

    def _fixupURLParts(self):
        hostaddr, secure = self.chanRequest.getHostInfo()
        if not self.scheme:
            self.scheme = ('http', 'https')[secure]
            
        if self.host:
            self.host, self.port = http.splitHostPort(self.scheme, self.host)
        else:
            # If GET line wasn't an absolute URL
            host = self.headers.getHeader('host')
            if host:
                self.host, self.port = http.splitHostPort(self.scheme, host)
            else:
                # When no hostname specified anywhere, either raise an
                # error, or use the interface hostname, depending on
                # protocol version
                if self.clientproto >= (1,1):
                    raise http.HTTPError(responsecode.BAD_REQUEST)
                self.host = hostaddr.host
                self.port = hostaddr.port


    def process(self):
        "Process a request."
        try:
            self.checkExpect()
            resp = self.preprocessRequest()
            if resp is not None:
                self._cbFinishRender(resp).addErrback(self._processingFailed)
                return
            self._parseURL()
            self._fixupURLParts()
            self.remoteAddr = self.chanRequest.getRemoteHost()
        except:
            failedDeferred = self._processingFailed(failure.Failure())
            return
        
        d = defer.Deferred()
        d.addCallback(self._getChild, self.site.resource, self.postpath)
        d.addCallback(lambda res, req: res.renderHTTP(req), self)
        d.addCallback(self._cbFinishRender)
        d.addErrback(self._processingFailed)
        d.callback(None)

    def preprocessRequest(self):
        """Do any request processing that doesn't follow the normal
        resource lookup procedure. "OPTIONS *" is handled here, for
        example. This would also be the place to do any CONNECT
        processing."""
        
        if self.method == "OPTIONS" and self.uri == "*":
            response = http.Response(responsecode.OK)
            response.headers.setHeader('allow', ('GET', 'HEAD', 'OPTIONS', 'TRACE'))
            return response
        # This is where CONNECT would go if we wanted it
        return None
    
    def _getChild(self, _, res, path, updatepaths=True):
        """Call res.locateChild, and pass the result on to _handleSegment."""

        self.resources.append(res)

        if not path:
            return res

        result = res.locateChild(self, path)
        if isinstance(result, defer.Deferred):
            return result.addCallback(self._handleSegment, res, path, updatepaths)
        else:
            return self._handleSegment(result, res, path, updatepaths)

    def _handleSegment(self, result, res, path, updatepaths):
        """Handle the result of a locateChild call done in _getChild."""

        newres, newpath = result
        # If the child resource is None then display a error page
        if newres is None:
            raise http.HTTPError(responsecode.NOT_FOUND)

        # If we got a deferred then we need to call back later, once the
        # child is actually available.
        if isinstance(newres, defer.Deferred):
            return newres.addCallback(
                lambda actualRes: self._handleSegment(
                    (actualRes, newpath), res, path, updatepaths)
                )

        if newpath is StopTraversal:
            # We need to rethink how to do this.
            #if newres is res:
                self._rememberURLForResource(path, res)
                return res
            #else:
            #    raise ValueError("locateChild must not return StopTraversal with a resource other than self.")

        newres = iweb.IResource(newres)
        if newres is res:
            assert not newpath is path, "URL traversal cycle detected when attempting to locateChild %r from resource %r." % (path, res)
            assert len(newpath) < len(path), "Infinite loop impending..."

        if path:
            if newpath:
                url = "/" + "/".join(path[:-len(newpath)])
            else:
                url = "/" + "/".join(path)
        else:
            url = "/"

        if updatepaths:
            # We found a Resource... update the request.prepath and postpath
            for x in xrange(len(path) - len(newpath)):
                self.prepath.append(self.postpath.pop(0))

        child = self._getChild(None, newres, newpath)
        self._rememberURLForResource(url, child)

        return child

    _resourcesByURL = weakref.WeakKeyDictionary()

    def _rememberURLForResource(self, url, resource):
        """
        Remember the URL of visited resources.
        """
        self._resourcesByURL[resource] = url

    def urlForResource(self, resource):
        """
        Looks up the URL of the given resource if this resource was found while
        processing this request.  Specifically, this includes the requested
        resource, and resources looked up via L{locateResource}.

        Note that a resource may be found at multiple URIs; if the same resource
        is visited at more than one location while processing this request,
        this method will return one of those URLs, but which one is not defined,
        nor whether the same URL is returned in subsequent calls.

        @return: the URL of C{resource} if known, otherwise C{None}.
        """
        try:
            return self._resourcesByURL[resource]
        except KeyError:
            return None

    def locateResource(self, url):
        """
        Looks up the resource with the given URL.
        @param uri: The URL of the desired resource.
        @return: a L{Deferred} resulting in the L{IResource} at the
            given URL or C{None} if no such resource can be located.
        @raise HTTPError: If C{url} is not a URL on the site that this
            request is being applied to.  The contained response will
            have a status code of L{responsecode.BAD_GATEWAY}.
        @raise HTTPError: If C{url} contains a query or fragment.
            The contained response will have a status code of
            L{responsecode.BAD_REQUEST}.
        """
        if url is None: return None

        #
        # Parse the URL
        #
        (scheme, host, path, query, fragment) = urlsplit(url)
    
        if query or fragment:
            raise http.HTTPError(http.StatusResponse(
                responsecode.BAD_REQUEST,
                "URL may not contain a query or fragment: %s" % (url,)
            ))

        # The caller shouldn't be asking a request on one server to lookup a
        # resource on some other server.
        if (scheme and scheme != self.scheme) or (host and host != self.headers.getHeader("host")):
            raise http.HTTPError(http.StatusResponse(
                responsecode.BAD_GATEWAY,
                "URL is not on this site (%s://%s/): %s" % (scheme, self.headers.getHeader("host"), url)
            ))

        segments = path.split("/")
        assert segments[0] == "", "URL path didn't begin with '/': %s" % (path,)
        segments = segments[1:]

        def notFound(f):
            f.trap(http.HTTPError)
            if f.response.code != responsecode.NOT_FOUND:
                raise f
            return None

        return defer.maybeDeferred(self._getChild, None, self.site.resource, segments, updatepaths=False)

    def _processingFailed(self, reason):
        if reason.check(http.HTTPError) is not None:
            # If the exception was an HTTPError, leave it alone
            d = defer.succeed(reason.value.response)
        else:
            # Otherwise, it was a random exception, so give a
            # ICanHandleException implementer a chance to render the page.
            def _processingFailed_inner(reason):
                handler = iweb.ICanHandleException(self, self)
                return handler.renderHTTP_exception(self, reason)
            d = defer.maybeDeferred(_processingFailed_inner, reason)
        
        d.addCallback(self._cbFinishRender)
        d.addErrback(self._processingReallyFailed, reason)
        return d
    
    def _processingReallyFailed(self, reason, origReason):
        log.msg("Exception rendering error page:", isErr=1)
        log.err(reason)
        log.msg("Original exception:", isErr=1)
        log.err(origReason)
        
        body = ("<html><head><title>Internal Server Error</title></head>"
                "<body><h1>Internal Server Error</h1>An error occurred rendering the requested page. Additionally, an error occured rendering the error page.</body></html>")
        
        response = http.Response(
            responsecode.INTERNAL_SERVER_ERROR,
            {'content-type': http_headers.MimeType('text','html')},
            body)
        self.writeResponse(response)

    def _cbFinishRender(self, result):
        def filterit(response, f):
            if (hasattr(f, 'handleErrors') or
                (response.code >= 200 and response.code < 300 and response.code != 204)):
                return f(self, response)
            else:
                return response

        response = iweb.IResponse(result, None)
        if response:
            d = defer.Deferred()
            for f in self.responseFilters:
                d.addCallback(filterit, f)
            d.addCallback(self.writeResponse)
            d.callback(response)
            return d

        resource = iweb.IResource(result, None)
        if resource:
            self.resources.append(resource)
            d = defer.maybeDeferred(resource.renderHTTP, self)
            d.addCallback(self._cbFinishRender)
            return d

        raise TypeError("html is not a resource or a response")

    def renderHTTP_exception(self, req, reason):
        log.msg("Exception rendering:", isErr=1)
        log.err(reason)
        
        body = ("<html><head><title>Internal Server Error</title></head>"
                "<body><h1>Internal Server Error</h1>An error occurred rendering the requested page. More information is available in the server log.</body></html>")
        
        return http.Response(
            responsecode.INTERNAL_SERVER_ERROR,
            {'content-type': http_headers.MimeType('text','html')},
            body)

class Site(object):
    def __init__(self, resource):
        """Initialize.
        """
        self.resource = iweb.IResource(resource)

    def __call__(self, *args, **kwargs):
        return Request(site=self, *args, **kwargs)


__all__ = ['Request', 'Site', 'StopTraversal', 'VERSION', 'defaultHeadersFilter', 'doTrace', 'parsePOSTData', 'preconditionfilter']
