# -*- test-case-name: twisted.test.test_sibling -*-

# Sibling Server

from twisted.spread.pb import Service, Perspective, Error
from twisted.spread.flavors import Referenceable
from twisted.spread.refpath import PathReferenceDirectory
from twisted.internet import defer
from twisted.python import log

from random import choice

class MotherService(Service, Perspective):
    """A `mother' object, managing many sibling-servers.

    I maintain a list of all "sibling" servers who are connected, so that all
    servers can connect to each other.  I also negotiate which distributed
    objects are owned by which sibling servers, so that if any sibling-server
    needs to locate an object it can be made available.
    """

    def __init__(self, sharedSecret, serviceName, application=None):
        Service.__init__(self, serviceName, application)
        Perspective.__init__(self, "mother")
        self.addPerspective(self)
        # Three states: unlocked, pending lock, locked
        self.pendingResources = {}      # path: deferred, host, port
        self.toLoadOnConnect = []       # [deferred, deferred, ...]
        self.lockedResources = {}       # path: host, port
        self.siblings = []             # [(host, port, reference)]
        self.makeIdentity(sharedSecret)

    def _cbLoadedResource(self, ticket, resourceType, resourceName, host, port, siblingPerspective):
        log.msg( 'mother: loaded resource')
        self.lockedResources[(resourceType, resourceName)] = (host, port, siblingPerspective)
        return (ticket, host, port, siblingPerspective)

    def loadRemoteResource(self, resourceType, resourceName, generateTicket, *args):
        """Request a sibling-server to load a resource.

        NOTE: caching of ticket resources could be an issue... do we cache tickets??

        Return a Deferred which will fire with (ticket, host, port), that will
        describe where and how a resource can be located.
        """

        if self.lockedResources.has_key( (resourceType, resourceName) ):
            (host,port, siblingPerspective)= self.lockedResources[(resourceType, resourceName)]
            return defer.succeed( (None, host, port, siblingPerspective) )

        log.msg( 'mother: loading resource (%s)'  % self.siblings)
        if not self.siblings:
            defr = defer.Deferred()
            self.toLoadOnConnect.append((resourceType, resourceName, generateTicket, args, defr))
            return defr

        #TODO: better selection mechanism for sibling server
        (host, port, siblingPerspective) = choice(self.siblings)

        d = siblingPerspective.callRemote("loadResource", resourceType, resourceName, generateTicket, *args)
        d.addCallback(self._cbLoadedResource, resourceType, resourceName, host, port, siblingPerspective)
        return d

    def loadRemoteResourceFor(self, siblingPerspective, resourceType, resourceName, generateTicket, *args):
        """Use to load a remote resource on a specified sibling
        service. Dont load it if already loaded on a sibling.
        """
        # lookup sibling info in siblings
        found = 0
        for host, port, sibling in self.siblings:
            if sibling == siblingPerspective:
                found = 1
                break

        if not found:
            raise ("Attempt to load resource for no-existent sibling")

        if self.lockedResources.has_key( (resourceType, resourceName) ):
            raise ("resource %s:%s already loaded on a sibling" % (resourceName, resourceType) )

        d = siblingPerspective.callRemote("loadResource", resourceType, resourceName, generateTicket, *args)
        d.addCallback(self._cbLoadedResource, resourceType, resourceName, host, port, siblingPerspective)
        return d



    def perspective_unloadResource(self, resourceType, resourceName):
        """This is called by sibling services to unload a resource
        """
        log.msg( "mother: unloading %s/%s" %( resourceType, resourceName ) )
        data = self.lockedResources.get( (resourceType, resourceName) )
        if not data:
            raise "Unable to unload not-loaded resource."
        (host, port, perspective) = data
        del self.lockedResources[ (resourceType, resourceName) ]

    def perspective_publishIP(self, host, port, clientRef):
        """called by sibling to set the host and port to publish for clients.
        """
        log.msg( "sibling attached: %s:%s" % (host, port ) )
        self.siblings.append((host, port,clientRef) )
        for resourceType, resourceName, generateTicket, args, deferred in self.toLoadOnConnect:
            self.loadRemoteResource(resourceType, resourceName, generateTicket, *args).chainDeferred(deferred)
        self.toLoadOnConnect = []

    def perspective_callDistributed(self, srcResourceType, srcResourceName, destResourceType, destResourceName, methodName, *args, **kw):
        """Call a remote method on a resources that is managed by the system.
        """
        data = self.lockedResources.get( (destResourceType, destResourceName) )
        if not data:
            raise "Unable to find not-loaded resource."
        (host, port, perspective) = data
        print "Calling distributed method <%s> for %s:%s" % (methodName, destResourceType, destResourceName)
        return perspective.callRemote('callDistributed', srcResourceType, srcResourceName, destResourceType, destResourceName, methodName, args, kw)

    def detached(self, client, identity):
        for path, (host, port, clientRef) in self.lockedResources.items():
            if client == clientRef:
                del self.lockedResources[path]
        log.msg( "sibling detached: %s" % client)
        return Perspective.detached(self, client, identity)
