# -*- test-case-name: twisted.test.test_web -*-
#
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

"""I hold the lowest-level Resource class."""


# System Imports
from twisted.internet import defer
from twisted.python import roots, components, reflect
from twisted.coil import coil

class IResource(components.Interface):
    """A web resource."""

    ## Signal if this IResource implementor is a "leaf node" or not.
    ## If True, getChildWithDefault will not be called on this Resource.
    isLeaf = 0

    def getChildWithDefault(self, name, request):
        """Return a child with the given name for the given request.
        This is the external interface used by the Resource publishing
        machinery. If implementing IResource without subclassing
        Resource, it must be provided. However, if subclassing Resource,
        getChild overridden instead.
        """

    def putChild(self, path, child):
        """Put a child IResource implementor at the given path.
        """

    def render(self, request):
        """Render a request. This is called on the leaf resource for
        a request. Render must return either a string, which will
        be sent to the browser as the HTML for the request, or
        server.NOT_DONE_YET. If NOT_DONE_YET is returned,
        at some point later (in a Deferred callback, usually)
        call request.write("<html>") to write data to the request,
        and request.finish() to send the data to the browser.
        """


class Resource(coil.ConfigCollection):
    """I define a web-accessible resource.

    I serve 2 main purposes; one is to provide a standard representation for
    what HTTP specification calls an 'entity', and the other is to provide an
    abstract directory structure for URL retrieval.
    """

    __implements__ = (IResource, coil.IConfigCollection)

    entityType = IResource

    server = None

    def __init__(self):
        """Initialize.
        """
        self.children = {}

    isLeaf = 0

    ### Abstract Collection Interface

    def listStaticNames(self):
        return self.children.keys()

    def listStaticEntities(self):
        return self.children.items()

    def listNames(self):
        return self.listStaticNames() + self.listDynamicNames()

    def listEntities(self):
        return self.listStaticEntities() + self.listDynamicEntities()

    def listDynamicNames(self):
        return []

    def listDynamicEntities(self, request=None):
        return []

    def getStaticEntity(self, name):
        return self.children.get(name)

    def getDynamicEntity(self, name, request):
        if not self.children.has_key(name):
            return self.getChild(name, request)
        else:
            return None

    def delEntity(self, name):
        del self.children[name]

    def reallyPutEntity(self, name, entity):
        self.children[name] = entity

    # Concrete HTTP interface

    def getChild(self, path, request):
        """Retrieve a 'child' resource from me.

        Implement this to create dynamic resource generation -- resources which
        are always available may be registered with self.putChild().

        This will not be called if the class-level variable 'isLeaf' is set in
        your subclass; instead, the 'postpath' attribute of the request will be
        left as a list of the remaining path elements.

        For example, the URL /foo/bar/baz will normally be::

          | site.resource.getChild('foo').getChild('bar').getChild('baz').

        However, if the resource returned by 'bar' has isLeaf set to true, then
        the getChild call will never be made on it.

        @param path: a string, describing the child

        @param request: a twisted.web.server.Request specifying meta-information
                        about the request that is being made for this child.
        """
        return error.NoResource("No such child resource.")

    def getChildWithDefault(self, path, request):
        """Retrieve a static or dynamically generated child resource from me.

        First checks if a resource was added manually by putChild, and then
        call getChild to check for dynamic resources. Only override if you want
        to affect behaviour of all child lookups, rather than just dynamic
        ones.

        This will check to see if I have a pre-registered child resource of the
        given name, and call getChild if I do not.
        """
        if self.children.has_key(path):
            return self.children[path]

        return self.getChild(path, request)

    def getChildForRequest(self, request):
        """(internal) Get a child of mine dependant on a particular request.

        This will be called on me as a top-level resource of a site in order to
        retrieve my appropriate child or grandchild to display.
        """
        res = self
        while request.postpath and not res.isLeaf:
            pathElement = request.postpath.pop(0)
            request.acqpath.append(pathElement)
            request.prepath.append(pathElement)
            res = res.getChildWithDefault(pathElement, request)
        return res


    def putChild(self, path, child):
        """Register a static child.
        """
        self.children[path] = child
        child.server = self.server

    def render(self, request):
        """Render a given resource.

        This must be implemented in all subclasses of Resource.

        The return value of this method will be the rendered page, unless the
        return value is twisted.web.server.NOT_DONE_YET, in which case it is
        this class's responsibility to write the results to
        request.write(data), then call request.finish().
        """
        raise NotImplementedError("%s.render called" %
                                  reflect.qual(self.__class__))


#t.w imports
#This is ugly, I know, but since error.py directly access resource.Resource
#during import-time (it subclasses it), the Resource class must be defined
#by the time error is imported.
import error
