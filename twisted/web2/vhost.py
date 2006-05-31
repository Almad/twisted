# -*- test-case-name: twisted.web2.test.test_vhost -*-
# Copyright (c) 2001-2004 Twisted Matrix Laboratories.
# See LICENSE for details.

"""I am a virtual hosts implementation.
"""

# System Imports
import urlparse
from zope.interface import implements
import urllib 
import warnings

from twisted.internet import address
from twisted.python import log

# Sibling Imports
from twisted.web2 import resource
from twisted.web2 import responsecode
from twisted.web2 import iweb
from twisted.web2 import http

class NameVirtualHost(resource.Resource):
    """I am a resource which represents named virtual hosts. 
       And these are my obligatory comments
    """
    
    supportNested = True

    def __init__(self, default=None):
        """Initialize. - Do you really need me to tell you that?
        """
        resource.Resource.__init__(self)
        self.hosts = {}
       
        self.default = default
        
    def addHost(self, name, resrc):
        """Add a host to this virtual host. - The Fun Stuff(TM)

        This associates a host named 'name' with a resource 'resrc'::

            nvh.addHost('nevow.com', nevowDirectory)
            nvh.addHost('divmod.org', divmodDirectory)
            nvh.addHost('twistedmatrix.com', twistedMatrixDirectory)

        I told you that was fun.
        """
        self.hosts[name] = resrc

    def removeHost(self, name):
        """Remove a host. :(
        """
        del self.hosts[name]

    def locateChild(self, req, segments):
        """It's a NameVirtualHost, do you know where your children are?
        
        This uses locateChild magic so you don't have to mutate the request.
        """

        host = req.host.lower()
        
        if self.supportNested:
            """ If supportNested is True domain prefixes (the stuff up to the first '.')
            will be chopped off until it's reduced to the tld or a valid domain is 
            found.
            """
            
            while not self.hosts.has_key(host) and len(host.split('.')) > 1:
                host = '.'.join(host.split('.')[1:])

        # Default being None is okay, it'll turn into a 404
        return self.hosts.get(host, self.default), segments


class AutoVHostURIRewrite(object):
    """
    I do request mangling to insure that children know what host they are being
    accessed from behind apache2.

    Usage:

        - Twisted::

            root = MyResource()
            vur = vhost.AutoVHostURIRewrite(root)

        - Apache2::

            <Location /whatever/>
              ProxyPass http://localhost:8538/
              RequestHeader set X-App-Location /whatever/
            </Location>

        If the trailing / is ommitted in the second argument to ProxyPass
        VHostURIRewrite will return a 404 response code.

        If proxying HTTPS, add this to the Apache config::

            RequestHeader set X-App-Scheme https
    """
    implements(iweb.IResource)

    def __init__(self, resource, sendsRealHost=False):
        self.resource=resource
        self.sendsRealHost = sendsRealHost
        
    def renderHTTP(self, req):
        return http.Response(responsecode.NOT_FOUND)

    def locateChild(self, req, segments):
        scheme = req.headers.getRawHeaders('x-app-scheme')

        if self.sendsRealHost:
            host = req.headers.getRawHeaders('host')
        else:
            host = req.headers.getRawHeaders('x-forwarded-host')

        app_location = req.headers.getRawHeaders('x-app-location')
        remote_ip = req.headers.getRawHeaders('x-forwarded-for')

        if not (host and remote_ip):
            if not host:
                warnings.warn(
                    ("No host was obtained either from Host or "
                     "X-Forwarded-Host headers.  If your proxy does not "
                     "send either of these headers use VHostURIRewrite. "
                     "If your proxy sends the real host as the Host header "
                     "use "
                     "AutoVHostURIRewrite(resrc, sendsRealHost=True)"))

            # some header unspecified => Error
            raise http.HTTPError(responsecode.BAD_REQUEST)
        host = host[0]
        remote_ip = remote_ip[0]
        if app_location:
            app_location = app_location[0]
        else:
            app_location = '/'
        if scheme:
            scheme = scheme[0]
        else:
            scheme='http'
        
        req.host, req.port = http.splitHostPort(scheme, host)
        req.scheme = scheme
        
        req.remoteAddr = address.IPv4Address('TCP', remote_ip, 0)
            
        req.prepath = app_location[1:].split('/')[:-1]
        req.path = '/'+('/'.join([urllib.quote(s, '') for s in (req.prepath + segments)]))
        
        return self.resource, segments
        
class VHostURIRewrite(object):
    """
    I do request mangling to insure that children know what host they are being
    accessed from behind mod_proxy.

    Usage:

        - Twisted::

            root = MyResource()
            vur = vhost.VHostURIRewrite(uri='http://hostname:port/path', resource=root)
            server.Site(vur)

        - Apache::

            <VirtualHost hostname:port>
                ProxyPass /path/ http://localhost:8080/
                Servername hostname
            </VirtualHost>

        If the trailing / is ommitted in the second argument to ProxyPass
        VHostURIRewrite will return a 404 response code.

        uri must be a fully specified uri complete with scheme://hostname/path/
    """

    implements(iweb.IResource)

    def __init__(self, uri, resource):
        self.resource = resource
        
        (self.scheme, self.host, self.path,
         params, querystring, fragment) = urlparse.urlparse(uri)
        if params or querystring or fragment:
            raise ValueError("Must not specify params, query args, or fragment to VHostURIRewrite")
        self.path = map(urllib.unquote, self.path[1:].split('/'))[:-1]
        self.host, self.port = http.splitHostPort(self.scheme, self.host)
        
    def renderHTTP(self, req):
        return http.Response(responsecode.NOT_FOUND)

    def locateChild(self, req, segments):
        req.scheme = self.scheme
        req.host = self.host
        req.port = self.port
        req.prepath=self.path[:]
        req.path = '/'+('/'.join([urllib.quote(s, '') for s in (req.prepath + segments)]))
        # print req.prepath, segments, req.postpath, req.path
        
        return self.resource, segments

__all__ = ['VHostURIRewrite', 'AutoVHostURIRewrite', 'NameVirtualHost']
