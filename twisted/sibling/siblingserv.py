# -*- test-case-name: twisted.test.test_sibling -*-

from twisted.spread.pb import Service, Perspective, Error
from twisted.spread.sturdy import PerspectiveConnector
from twisted.spread.flavors import Referenceable
from twisted.spread.refpath import PathReferenceDirectory

from twisted.internet import defer
from twisted.python import log
from twisted.python.failure import Failure
from twisted.cred.util import challenge

from twisted.cred.authorizer import DefaultAuthorizer
from twisted.cred.identity import Identity


class TicketAuthorizer(DefaultAuthorizer):

    def loadIdentity(self, identityName, keys):
        log.msg( "loading identity: %s:%s " %(identityName, keys))
        ticket = challenge()
        ident = Identity(identityName, self.application)
        ident.setPassword(ticket)
        for serviceName, perspectiveName in keys:
            ident.addKeyByString( serviceName, perspectiveName)
        ident.save()
        return ticket

True = 1
False = 0


class SiblingMotherClient(Referenceable):
    def __init__(self, siblingsrv):
        self.siblingsrv = siblingsrv

    def remote_loadResource(self, resourceType, resourceName, *args):
        return self.siblingsrv.loadResource(resourceType, resourceName, args)

    def remote_callDistributed(self, srcResourceType, srcResourceName, destResourceType, destResourceName, methodName, args, kw):
        """invoked to call a method on a distributed object.
        """
        resource = self.siblingsrv.ownedResources.get( (destResourceType, destResourceName), None)
        if not resource:
            return defer.fail("Sibling does not own this resource")
        method = getattr(resource, "sibling_%s" % methodName)
        fullArgs = (srcResourceType, srcResourceName) + args
        return method(*fullArgs, **kw)

class SiblingService(Service, Perspective):
    """A 'sibling' object, managed by a mother server

    I am one of a set of siblings managed by a mother server.  I use the
    mother server as a central manager of distributed objects, and as a
    mechanism for communicating to other sibling servers.

    Distributed login into me is handled by passing identity resources - which
    I have a special loader and authorizer for.
    """

    def __init__(self, motherHost, motherPort, motherService, publishHost, localPort,
                 serviceName="twisted.sibling", sharedSecret="shhh!", application=None):
        """Initialize me.

        (Application's authorizer must be a TicketAuthorizer, otherwise
        login won't work.)
        """
        Service.__init__(self, serviceName, application)
        Perspective.__init__(self, "sibling")
        self.addPerspective(self)
        self.ownedResources = {}
        self.remoteResources = {}
        self.resourceLoaders = {}
        self.localPort = localPort
        self.siblingMother = SiblingMotherClient(self)
        self.motherRef = PerspectiveConnector(
            motherHost, motherPort, "mother", sharedSecret,
            motherService, client = self.siblingMother)
        self.makeIdentity(sharedSecret)
        self.application.authorizer.siblingService = self
        ## identities are a special kind of resource
        self.registerResourceLoader("identity", self.application.authorizer.loadIdentity)

        # this will be the first method called on the mother connection once it is setup
        self.motherRef.callRemote('publishIP', publishHost, self.localPort, self.siblingMother)

    def startService(self):
        log.msg( 'starting sibling, woo')

    def __getstate__(self):
        d = Service.__getstate__(self)
        d['ownedResources'] = {}
        d['remoteResources'] = {}
        return d

    # XXX I know what these mean, don't delete them -glyph
    def _cbLocked(self, result, path):
        if result is None:
            obj = func(*args, **kw)
            self.ownedResources[path] = obj
            return (True, obj)
        else:
            self.remoteResources[path] = result
            return (False, result)

    def _ebLocked(self, error, path):
        log.msg('not locked, panicking')
        raise error

    # OK now on to the real code

    def ownResource(self, resourceObject, resourceType, resourceName):
        log.msg('sibling: owning resource %s/%s' % (resourceType, resourceName))
        self.ownedResources[resourceType, resourceName] = resourceObject
        return resourceObject

    def loadResource(self, resourceType, resourceName, args):
        """Returns a Deferred when the resource is loaded.
        This deferred may yield some data that is returned to the caller.
        """
        log.msg( 'sibling: loading resource %s/%s' %(resourceType, resourceName))
        value = self.resourceLoaders[resourceType](resourceName, *args)
        if isinstance(value, defer.Deferred):
            dvalue = value
        else:
            dvalue = defer.succeed(value)
        dvalue.addCallback(self.ownResource, resourceType, resourceName)
        return dvalue

    def registerResourceLoader(self, resourceType, resourceLoader):
        """Register a callable object to generate resources.

        The callable object may return Deferreds or synchronous values.
        """
        log.msg( 'sibling: registering resource loader %s:%s' % (resourceType, repr(resourceLoader)))
        self.resourceLoaders[resourceType] = resourceLoader

    def unloadResource(self, resourceType, resourceName):
        print "sibling: unloading (%s:%s)" %(resourceType, resourceName)
        del self.ownedResources[ (resourceType, resourceName) ]
        return self.motherRef.callRemote("unloadResource", resourceType, resourceName).addCallback(self._cbUnload)

    def _cbUnload(self, data):
        log.msg( "Unloaded resource: %s" % data)

    def callDistributed(self, caller, destResourceType, destResourceName, methodName, *args, **kw):
        """Call a distributed method on a resource managed by the sibling
        network. This will call the method 'getResourceInfo' on the calling
        object which must return its resourceType and resourceName to be
        identified by.  The final method being called will have 'sibling_'
        prepended to its name and have the calling objects resourceType and
        resourceName as the first arguments.

        NOTE: this method of identifying the calling object is temporary..
        need to establish a better way which includes allowing the calling
        object to expose some data and/or functionality to the caller.
        """
        (srcResourceType, srcResourceName) = caller.getResourceInfo()
        if not self.ownedResources.has_key((srcResourceType,srcResourceName)):
            raise "sibling does not own this resource!"
        fullArgs = ('callDistributed', srcResourceType, srcResourceName,
                    destResourceType, destResourceName, methodName) + args
        return self.motherRef.callRemote(*fullArgs, **kw)


    def removeIdentity(self, identityName):
        self.application.authorizer.removeIdentity(identityName)
        self.unloadResource("identity", identityName)
