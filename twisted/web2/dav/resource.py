##
# Copyright (c) 2005 Apple Computer, Inc. All rights reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
# DRI: Wilfredo Sanchez, wsanchez@apple.com
##

"""
WebDAV resources.
"""

__all__ = [
    "DAVPropertyMixIn",
    "DAVResource",
    "DAVLeafResource"
]

import urllib

from zope.interface import implements
from twisted.python import log
from twisted.internet.defer import maybeDeferred
from twisted.web2 import responsecode
from twisted.web2.http import HTTPError, RedirectResponse, StatusResponse
from twisted.web2.http_headers import generateContentType
from twisted.web2.iweb import IResponse
from twisted.web2.resource import LeafResource
from twisted.web2.static import MetaDataMixin, StaticRenderMixin
from twisted.web2.dav import davxml
from twisted.web2.dav.davxml import dav_namespace, lookupElement
from twisted.web2.dav.idav import IDAVResource
from twisted.web2.dav.util import unimplemented

twisted_dav_namespace = "http://twistedmatrix.com/xml_namespace/dav/"

class DAVPropertyMixIn (MetaDataMixin):
    """
    Mix-in class which implements the DAV property access API in
    L{IDAVResource}.
    """
    #
    # Live properties which are always present and computed (not kept in the
    # dead property store).
    # Live properties which are not always defined don't belong in this list
    # (such as properties which are verified by the server, but kept in the
    # dead property store).
    # This list is used by hasProperty() and listProperties() to make sure that
    # they are included.
    #
    liveProperties = (
        (dav_namespace, "resourcetype"            ),
        (dav_namespace, "getetag"                 ),
        (dav_namespace, "getcontenttype"          ),
        (dav_namespace, "getcontentlength"        ),
        (dav_namespace, "getlastmodified"         ),
        (dav_namespace, "creationdate"            ),
        (dav_namespace, "displayname"             ),
        (dav_namespace, "supportedlock"           ),
        (dav_namespace, "supported-privilege-set" ),
        (dav_namespace, "acl"                     ),
        (dav_namespace, "principal-collection-set"),

        (twisted_dav_namespace, "resource-class"),
    )

    def deadProperties(self):
        """
        Provides internal access to the WebDAV dead property store.  You
        probably shouldn't be calling this directly if you can use the property
        accessors in the L{IDAVResource} API instead.  However, a subclass must
        override this method to provide it's own dead property store.

        This implementation raises L{NotImplementedError}.

        @return: a dict-like object from which one can read and to which one can
            write dead properties.  Keys are qname tuples (ie. C{(namespace, name)})
            as returned by L{davxml.WebDAVElement.qname()} and values are
            L{davxml.WebDAVElement} instances.
        """
        unimplemented(self)

    def hasProperty(self, property, request):
        """
        See L{IDAVResource.hasProperty}.
        """
        if type(property) is tuple:
            qname = property
        else:
            qname = property.qname()

        return qname in self.liveProperties or self.deadProperties().contains(qname)

    def readProperty(self, property, request):
        """
        See L{IDAVResource.readProperty}.
        """
        if type(property) is tuple:
            qname = property
            sname = "{%s}%s" % property
        else:
            qname = property.qname()
            sname = property.sname()

        namespace, name = qname

        if namespace == dav_namespace:
            if name == "resourcetype":
                # Allow live property to be overriden by dead property
                if self.deadProperties().contains(qname):
                    return self.deadProperties().get(qname)
                if self.isCollection():
                    return davxml.ResourceType.collection
                return davxml.ResourceType.empty
    
            if name == "getetag":
                return davxml.GETETag(self.etag().generate())
    
            if name == "getcontenttype":
                mimeType = self.contentType()
                mimeType.params = None # WebDAV getcontenttype property does not include parameters
                return davxml.GETContentType(generateContentType(mimeType))
        
            if name == "getcontentlength":
                return davxml.GETContentLength(str(self.contentLength()))

            if name == "getlastmodified":
                return davxml.GETLastModified.fromDate(self.lastModified())

            if name == "creationdate":
                return davxml.CreationDate.fromDate(self.creationDate())

            if name == "displayname":
                return davxml.DisplayName(self.displayName())

            if name == "supportedlock":
                return davxml.SupportedLock(
                    davxml.LockEntry(davxml.LockScope.exclusive, davxml.LockType.write),
                    davxml.LockEntry(davxml.LockScope.shared   , davxml.LockType.write),
                )

            if name == "supported-privilege-set":
                return self.supportedPrivileges()

            if name == "acl":
                return self.accessControlList()

            if name == "principal-collection-set":
                return davxml.PrincipalCollectionSet(*[davxml.HRef(u) for u in self.principalCollections()])

        if namespace == twisted_dav_namespace:
            if name == "resource-class":
                class ResourceClass (davxml.WebDAVTextElement):
                    namespace = twisted_dav_namespace
                    name = "resource-class"
                    hidden = False
                return ResourceClass(self.__class__.__name__)

        return self.deadProperties().get(qname)

    def writeProperty(self, property, request):
        """
        See L{IDAVResource.writeProperty}.
        """
        assert isinstance(property, davxml.WebDAVElement)

        if property.protected:
            raise HTTPError(StatusResponse(responsecode.FORBIDDEN, "Protected property %s may not be set." % (property.sname(),)))

        self.deadProperties().set(property)

    def removeProperty(self, property, request):
        """
        See L{IDAVResource.removeProperty}.
        """
        if type(property) is tuple:
            qname = property
        else:
            qname = property.qname()

        if qname in self.liveProperties:
            raise HTTPError(StatusResponse(responsecode.FORBIDDEN, "Live property %s cannot be deleted." % (property.sname(),)))

        self.deadProperties().delete(qname)

    def listProperties(self, request):
        """
        See L{IDAVResource.listProperties}.
        """
        # FIXME: A set would be better here, that that's a python 2.4+ feature.

        qnames = list(self.liveProperties)

        for qname in self.deadProperties().list():
            if qname not in qnames:
                qnames.append(qname)

        return qnames

    def listAllprop(self, request):
        """
        Some DAV properties should not be returned to a C{DAV:allprop} query.
        RFC 3253 defines several such properties.  This method computes a subset
        of the property qnames returned by L{listProperties} by filtering out
        elements whose class have the C{.hidden} attribute set to C{True}.
        @return: a list of qnames of properties which are defined and are
            appropriate for use in response to a C{DAV:allprop} query.   
        """
        qnames = []

        for qname in self.listProperties(request):
            try:
                if not lookupElement(qname).hidden:
                    qnames.append(qname)
            except KeyError:
                # Unknown element
                qnames.append(qname)

        return qnames

    def hasDeadProperty(self, property):
        """
        Same as L{hasProperty}, but bypasses the live property store and checks
        directly from the dead property store.
        """
        if type(property) is tuple:
            qname = property
        else:
            qname = property.qname()

        return self.deadProperties().contains(qname)

    def readDeadProperty(self, property):
        """
        Same as L{readProperty}, but bypasses the live property store and reads
        directly from the dead property store.
        """
        if type(property) is tuple:
            qname = property
        else:
            qname = property.qname()

        return self.deadProperties().get(qname)

    def writeDeadProperty(self, property):
        """
        Same as L{writeProperty}, but bypasses the live property store and
        writes directly to the dead property store.
        Note that this should not be used unless you know that you are writing
        to an overrideable live property, as this bypasses the logic which
        protects protected properties.  The result of writing to a
        non-overrideable live property with this method is undefined; the value
        in the dead property store may or may not be ignored when reading the
        property with L{readProperty}.
        """
        self.deadProperties().set(property)

    #
    # Overrides some methods in MetaDataMixin in order to allow DAV properties
    # to override the values of some HTTP metadata.
    #
    def contentType(self):
        if self.hasDeadProperty((davxml.dav_namespace, "getcontenttype")):
            return self.readDeadProperty((davxml.dav_namespace, "getcontenttype")).mimeType()
        else:
            return super(DAVPropertyMixIn, self).contentType()

    def displayName(self):
        if self.hasDeadProperty((davxml.dav_namespace, "displayname")):
            return str(self.readDeadProperty((davxml.dav_namespace, "displayname")))
        else:
            return super(DAVPropertyMixIn, self).displayName()

class DAVResource (DAVPropertyMixIn, StaticRenderMixin):
    implements(IDAVResource)

    ##
    # DAV
    ##

    def davComplianceClasses(self):
        """
        This implementation raises L{NotImplementedError}.
        @return: a sequence of strings denoting WebDAV compliance classes.  For
            example, a DAV level 2 server might return ("1", "2").
        """
        unimplemented(self)

    def isCollection(self):
        """
        See L{IDAVResource.isCollection}.

        This implementation raises L{NotImplementedError}; a subclass must
        override this method.
        """
        unimplemented(self)

    def findChildren(self, depth):
        """
        See L{IDAVResource.findChildren}.

        This implementation raises returns C{()} if C{depth} is C{0} and this
        resource is a collection.  Otherwise, it raises L{NotImplementedError};
        a subclass must override this method.
        """
        assert depth in ("0", "1", "infinity"), "Invalid depth: %s" % (depth,)
        if depth == "0" or not self.isCollection():
            return ()
        else:
            unimplemented(self)

    ##
    # ACL
    ##

    def principalCollections(self):
        """
        See L{IDAVResource.principalCollections}.

        This implementation returns C{()}.
        """
        return ()

    def accessControlList(self):
        """
        See L{IDAVResource.accessControlList}.

        This implementation returns an ACL granting all privileges to all
        principals.
        """
        return allACL

    def supportedPrivileges(self):
        """
        See L{IDAVResource.supportedPrivileges}.

        This implementation returns a supported privilege set containing only
        the DAV:all privilege.
        """
        return allPrivilegeSet

    ##
    # HTTP
    ##

    def renderHTTP(self, request):

        # FIXME: This is for testing with litmus; comment out when not in use
        #litmus = request.headers.getRawHeaders("x-litmus")
        #if litmus: log.msg("*** Litmus test: %s ***" % (litmus,))

        # FIXME: Learn how to use twisted logging facility, wsanchez
        protocol = "HTTP/%s.%s" % request.clientproto
        log.msg("%s %s %s" % (request.method, urllib.unquote(request.uri), protocol))

        #
        # If this is a collection and the URI doesn't end in "/", redirect.
        #
        if self.isCollection() and request.uri[-1:] != "/":
            return RedirectResponse(request.uri + "/")

        def setHeaders(response):
            response = IResponse(response)

            response.headers.setHeader("dav", self.davComplianceClasses())

            #
            # If this is a collection and the URI doesn't end in "/", add a
            # Content-Location header.  This is needed even if we redirect such
            # requests (as above) in the event that this resource was created or
            # modified by the request.
            #
            if self.isCollection() and request.uri[-1:] != "/":
                response.headers.setHeader("content-location", request.uri + "/")

            return response

        def onError(f):
            # If we get an HTTPError, run its response through setHeaders() as
            # well.
            f.trap(HTTPError)
            return setHeaders(f.value.response)

        d = maybeDeferred(super(DAVResource, self).renderHTTP, request)
        return d.addCallbacks(setHeaders, onError)

class DAVLeafResource (DAVResource, LeafResource):
    """
    DAV resource with no children.
    """
    def findChildren(self, depth):
        return ()

##
# Utilities
##

allACL = davxml.ACL(
    davxml.ACE(
        davxml.Principal(davxml.All()),
        davxml.Grant(davxml.Privilege(davxml.All())),
        davxml.Protected()
    )
)

allPrivilegeSet = davxml.SupportedPrivilegeSet(
    davxml.SupportedPrivilege(
        davxml.Privilege(davxml.All()),
        davxml.Description("all privileges", **{"xml:lang": "en"})
    )
)
