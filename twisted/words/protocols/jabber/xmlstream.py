# -*- test-case-name: twisted.words.test.test_jabberxmlstream -*-
#
# Copyright (c) 2001-2006 Twisted Matrix Laboratories.
# See LICENSE for details.

"""
XMPP XML Streams

Building blocks for setting up XML Streams, including helping classes for
doing authentication on either client or server side, and working with XML
Stanzas.
"""

from zope.interface import directlyProvides, implements

from twisted.internet import defer
from twisted.internet.error import ConnectionLost
from twisted.python import failure
from twisted.words.protocols.jabber import error, ijabber
from twisted.words.xish import domish, xmlstream
from twisted.words.xish.xmlstream import STREAM_CONNECTED_EVENT
from twisted.words.xish.xmlstream import STREAM_START_EVENT
from twisted.words.xish.xmlstream import STREAM_END_EVENT
from twisted.words.xish.xmlstream import STREAM_ERROR_EVENT

try:
    from twisted.internet import ssl
except ImportError:
    ssl = None
if ssl and not ssl.supported:
    ssl = None

STREAM_AUTHD_EVENT = intern("//event/stream/authd")
INIT_FAILED_EVENT = intern("//event/xmpp/initfailed")

NS_STREAMS = 'http://etherx.jabber.org/streams'
NS_XMPP_TLS = 'urn:ietf:params:xml:ns:xmpp-tls'

Reset = object()

def hashPassword(sid, password):
    """
    Create a SHA1-digest string of a session identifier and password.
    """
    import sha
    return sha.new("%s%s" % (sid, password)).hexdigest()

class Authenticator:
    """
    Base class for business logic of initializing an XmlStream

    Subclass this object to enable an XmlStream to initialize and authenticate
    to different types of stream hosts (such as clients, components, etc.).

    Rules:
      1. The Authenticator MUST dispatch a L{STREAM_AUTHD_EVENT} when the
         stream has been completely initialized.
      2. The Authenticator SHOULD reset all state information when
         L{associateWithStream} is called.
      3. The Authenticator SHOULD override L{streamStarted}, and start
         initialization there.

    @type xmlstream: L{XmlStream}
    @ivar xmlstream: The XmlStream that needs authentication

    @note: the term authenticator is historical. Authenticators perform
           all steps required to prepare the stream for the exchange
           of XML stanzas.
    """

    def __init__(self):
        self.xmlstream = None

    def connectionMade(self):
        """
        Called by the XmlStream when the underlying socket connection is
        in place.

        This allows the Authenticator to send an initial root element, if it's
        connecting, or wait for an inbound root from the peer if it's accepting
        the connection.

        Subclasses can use self.xmlstream.send() to send any initial data to
        the peer.
        """

    def streamStarted(self):
        """
        Called by the XmlStream when the stream has started.

        A stream is considered to have started when the root element has been
        received and, if applicable, the feature set has been received.
        """

    def associateWithStream(self, xmlstream):
        """
        Called by the XmlStreamFactory when a connection has been made
        to the requested peer, and an XmlStream object has been
        instantiated.

        The default implementation just saves a handle to the new
        XmlStream.

        @type xmlstream: L{XmlStream}
        @param xmlstream: The XmlStream that will be passing events to this
                          Authenticator.

        """
        self.xmlstream = xmlstream

class ConnectAuthenticator(Authenticator):
    """
    Authenticator for initiating entities.
    """

    namespace = None

    def __init__(self, otherHost):
        self.otherHost = otherHost

    def connectionMade(self):
        self.xmlstream.namespace = self.namespace
        self.xmlstream.otherHost = self.otherHost
        self.xmlstream.sendHeader()

    def initializeStream(self):
        """
        Perform stream initialization procedures.

        An L{XmlStream} holds a list of initializer objects in its
        C{initializers} attribute. This method calls these initializers in
        order and dispatches the C{STREAM_AUTHD_EVENT} event when the list has
        been successfully processed. Otherwise it dispatches the
        C{INIT_FAILED_EVENT} event with the failure.

        Initializers may return the special L{Reset} object to halt the
        initialization processing. It signals that the current initializer was
        successfully processed, but that the XML Stream has been reset. An
        example is the TLSInitiatingInitializer.
        """

        def remove_first(result):
            self.xmlstream.initializers.pop(0)

            return result

        def do_next(result):
            """
            Take the first initializer and process it.

            On success, the initializer is removed from the list and
            then next initializer will be tried.
            """

            if result is Reset:
                return None

            try:
                init = self.xmlstream.initializers[0]
            except IndexError:
                self.xmlstream.dispatch(self.xmlstream, STREAM_AUTHD_EVENT)
                return None
            else:
                d = defer.maybeDeferred(init.initialize)
                d.addCallback(remove_first)
                d.addCallback(do_next)
                return d

        d = defer.succeed(None)
        d.addCallback(do_next)
        d.addErrback(self.xmlstream.dispatch, INIT_FAILED_EVENT)

    def streamStarted(self):
        self.initializeStream()

class FeatureNotAdvertized(Exception):
    """
    Exception indicating a stream feature was not advertized, while required by
    the initiating entity.
    """

class BaseFeatureInitiatingInitializer(object):
    """
    Base class for initializers with a stream feature.

    This assumes the associated XmlStream represents the initiating entity
    of the connection.

    @cvar feature: tuple of (uri, name) of the stream feature root element.
    @type feature: tuple of (L{str}, L{str})
    @ivar required: whether the stream feature is required to be advertized
                    by the receiving entity.
    @type required: L{bool}
    """

    implements(ijabber.IInitiatingInitializer)

    feature = None
    required = False

    def __init__(self, xs):
        self.xmlstream = xs

    def initialize(self):
        """
        Initiate the initialization.

        Checks if the receiving entity advertizes the stream feature. If it
        does, the initialization is started. If it is not advertized, and the
        C{required} instance variable is L{True}, it raises
        L{FeatureNotAdvertized}. Otherwise, the initialization silently
        succeeds.
        """

        if self.feature in self.xmlstream.features:
            return self.start()
        elif self.required:
            raise FeatureNotAdvertized
        else:
            return None

    def start(self):
        """
        Start the actual initialization.

        May return a deferred for asynchronous initialization.
        """

class TLSError(Exception):
    """
    TLS base exception.
    """

class TLSFailed(TLSError):
    """
    Exception indicating failed TLS negotiation
    """

class TLSRequired(TLSError):
    """
    Exception indicating required TLS negotiation.

    This exception is raised when the receiving entity requires TLS
    negotiation and the initiating does not desire to negotiate TLS.
    """

class TLSNotSupported(TLSError):
    """
    Exception indicating missing TLS support.

    This exception is raised when the initiating entity wants and requires to
    negotiate TLS when the OpenSSL library is not available.
    """

class TLSInitiatingInitializer(BaseFeatureInitiatingInitializer):
    """
    TLS stream initializer for the initiating entity.

    It is strongly required to include this initializer in the list of
    initializers for an XMPP stream. By default it will try to negotiate TLS.
    An XMPP server may indicate that TLS is required. If TLS is not desired,
    set the C{wanted} attribute to False instead of removing it from the list
    of initializers, so a proper exception L{TLSRequired} can be raised.

    @cvar wanted: indicates if TLS negotiation is wanted.
    @type wanted: L{bool}
    """

    feature = (NS_XMPP_TLS, 'starttls')
    wanted = True
    _deferred = None

    def onProceed(self, obj):
        """
        Proceed with TLS negotiation and reset the XML stream.
        """

        self.xmlstream.removeObserver('/failure', self.onFailure)
        ctx = ssl.CertificateOptions()
        self.xmlstream.transport.startTLS(ctx)
        self.xmlstream.reset()
        self.xmlstream.sendHeader()
        self._deferred.callback(Reset)

    def onFailure(self, obj):
        self.xmlstream.removeObserver('/proceed', self.onProceed)
        self._deferred.errback(TLSFailed())

    def start(self):
        """
        Start TLS negotiation.

        This checks if the receiving entity requires TLS, the SSL library is
        available and uses the C{required} and C{wanted} instance variables to
        determine what to do in the various different cases.

        For example, if the SSL library is not available, and wanted and
        required by the user, it raises an exception. However if it is not
        required by both parties, initialization silently succeeds, moving
        on to the next step.
        """
        if self.wanted:
            if ssl is None:
                if self.required:
                    return defer.fail(TLSNotSupported())
                else:
                    return defer.succeed(None)
            else:
                pass
        elif self.xmlstream.features[self.feature].required:
            return defer.fail(TLSRequired())
        else:
            return defer.succeed(None)

        self._deferred = defer.Deferred()
        self.xmlstream.addOnetimeObserver("/proceed", self.onProceed)
        self.xmlstream.addOnetimeObserver("/failure", self.onFailure)
        self.xmlstream.send(domish.Element((NS_XMPP_TLS, "starttls")))
        return self._deferred



class XmlStream(xmlstream.XmlStream):
    """
    XMPP XML Stream protocol handler.

    @ivar version: XML stream version as a tuple (major, minor). Initially,
                   this is set to the minimally supported version. Upon
                   receiving the stream header of the peer, it is set to the
                   minimum of that value and the version on the received
                   header.
    @type version: (L{int}, L{int})
    @ivar namespace: default namespace URI for stream
    @type namespace: L{str}
    @ivar thisHost: hostname of this entity
    @ivar otherHost: hostname of the peer entity
    @ivar sid: session identifier
    @type sid: L{str}
    @ivar initiating: True if this is the initiating stream
    @type initiating: L{bool}
    @ivar features: map of (uri, name) to stream features element received from
                    the receiving entity.
    @type features: L{dict} of (L{str}, L{str}) to L{domish.Element}.
    @ivar prefixes: map of URI to prefixes that are to appear on stream
                    header.
    @type prefixes: L{dict} of L{str} to L{str}
    @ivar initializers: list of stream initializer objects
    @type initializers: L{list} of objects that provide L{IInitializer}
    @ivar authenticator: associated authenticator that uses C{initializers} to
                         initialize the XML stream.
    """

    version = (1, 0)
    namespace = 'invalid'
    thisHost = None
    otherHost = None
    sid = None
    initiating = True
    prefixes = {NS_STREAMS: 'stream'}

    _headerSent = False     # True if the stream header has been sent

    def __init__(self, authenticator):
        xmlstream.XmlStream.__init__(self)

        self.authenticator = authenticator
        self.initializers = []
        self.features = {}

        # Reset the authenticator
        authenticator.associateWithStream(self)

    def _callLater(self, *args, **kwargs):
        from twisted.internet import reactor
        return reactor.callLater(*args, **kwargs)

    def reset(self):
        """
        Reset XML Stream.

        Resets the XML Parser for incoming data. This is to be used after
        successfully negotiating a new layer, e.g. TLS and SASL. Note that
        registered event observers will continue to be in place.
        """
        self._headerSent = False
        self._initializeStream()


    def onStreamError(self, errelem):
        """
        Called when a stream:error element has been received.

        Dispatches a L{STREAM_ERROR_EVENT} event with the error element to
        allow for cleanup actions and drops the connection.

        @param errelem: The received error element.
        @type errelem: L{domish.Element}
        """
        self.dispatch(failure.Failure(error.exceptionFromStreamError(errelem)),
                      STREAM_ERROR_EVENT)
        self.transport.loseConnection()


    def onFeatures(self, features):
        """
        Called when a stream:features element has been received.

        Stores the received features in the C{features} attribute, checks the
        need for initiating TLS and notifies the authenticator of the start of
        the stream.

        @param features: The received features element.
        @type features: L{domish.Element}
        """
        self.features = {}
        for feature in features.elements():
            self.features[(feature.uri, feature.name)] = feature
        self.authenticator.streamStarted()


    def sendHeader(self):
        """
        Send stream header.
        """
        rootElem = domish.Element((NS_STREAMS, 'stream'), self.namespace)

        if self.initiating and self.otherHost:
            rootElem['to'] = self.otherHost
        elif not self.initiating:
            if self.thisHost:
                rootElem['from'] = self.thisHost
            if self.sid:
                rootElem['id'] = self.sid

        if self.version >= (1, 0):
            rootElem['version'] = "%d.%d" % (self.version[0], self.version[1])

        self.rootElem = rootElem

        self.send(rootElem.toXml(prefixes=self.prefixes, closeElement=0))
        self._headerSent = True


    def sendFooter(self):
        """
        Send stream footer.
        """
        self.send('</stream:stream>')


    def sendStreamError(self, streamError):
        """
        Send stream level error.

        If we are the receiving entity, and haven't sent the header yet,
        we sent one first.

        If the given C{failure} is a L{error.StreamError}, it is rendered
        to its XML representation, otherwise a generic C{internal-error}
        stream error is generated.

        After sending the stream error, the stream is closed and the transport
        connection dropped.
        """
        if not self._headerSent and not self.initiating:
            self.sendHeader()

        if self._headerSent:
            self.send(streamError.getElement())
            self.sendFooter()

        self.transport.loseConnection()


    def send(self, obj):
        """
        Send data over the stream.

        This overrides L{xmlstream.Xmlstream.send} to use the default namespace
        of the stream header when serializing L{domish.IElement}s. It is
        assumed that if you pass an object that provides L{domish.IElement},
        it represents a direct child of the stream's root element.
        """
        if domish.IElement.providedBy(obj):
            obj = obj.toXml(prefixes=self.prefixes,
                            defaultUri=self.namespace,
                            prefixesInScope=self.prefixes.values())

        xmlstream.XmlStream.send(self, obj)


    def connectionMade(self):
        """
        Called when a connection is made.

        Notifies the authenticator when a connection has been made.
        """
        xmlstream.XmlStream.connectionMade(self)
        self.authenticator.connectionMade()


    def onDocumentStart(self, rootelem):
        """
        Called when the stream header has been received.

        Extracts the header's C{id} and C{version} attributes from the root
        element. The C{id} attribute is stored in our C{sid} attribute and the
        C{version} attribute is parsed and the minimum of the version we sent
        and the parsed C{version} attribute is stored as a tuple (major, minor)
        in this class' C{version} attribute. If no C{version} attribute was
        present, we assume version 0.0.

        If appropriate (we are the initiating stream and the minimum of our and
        the other party's version is at least 1.0), a one-time observer is
        registered for getting the stream features. The registered function is
        C{onFeatures}.

        Ultimately, the authenticator's C{streamStarted} method will be called.

        @param rootelem: The root element.
        @type rootelem: L{domish.Element}
        """
        xmlstream.XmlStream.onDocumentStart(self, rootelem)

        # Extract stream identifier
        if rootelem.hasAttribute("id"):
            self.sid = rootelem["id"]

        # Extract stream version and take minimum with the version sent
        if rootelem.hasAttribute("version"):
            version = rootelem["version"].split(".")
            try:
                version = (int(version[0]), int(version[1]))
            except IndexError, ValueError:
                version = (0, 0)
        else:
            version = (0, 0)

        self.version = min(self.version, version)

        # Setup observer for stream errors
        self.addOnetimeObserver("/error[@xmlns='%s']" % NS_STREAMS,
                                self.onStreamError)

        # Setup observer for stream features, if applicable
        if self.initiating and self.version >= (1, 0):
            self.addOnetimeObserver('/features[@xmlns="%s"]' % NS_STREAMS,
                                    self.onFeatures)
        else:
            self.authenticator.streamStarted()



class XmlStreamFactory(xmlstream.XmlStreamFactory):
    def __init__(self, authenticator):
        xmlstream.XmlStreamFactory.__init__(self)
        self.authenticator = authenticator


    def buildProtocol(self, _):
        self.resetDelay()
        # Create the stream and register all the bootstrap observers
        xs = XmlStream(self.authenticator)
        xs.factory = self
        for event, fn in self.bootstraps: xs.addObserver(event, fn)
        return xs



class TimeoutError(Exception):
    """
    Exception raised when no IQ response has been received before the
    configured timeout.
    """



def upgradeWithIQResponseTracker(xs):
    """
    Enhances an XmlStream for iq response tracking.

    This makes an L{XmlStream} object provide L{IIQResponseTracker}. When a
    response is an error iq stanza, the deferred has its errback invoked with a
    failure that holds a L{StanzaException<error.StanzaException>} that is
    easier to examine.
    """
    def callback(iq):
        """
        Handle iq response by firing associated deferred.
        """
        if getattr(iq, 'handled', False):
            return

        try:
            d = xs.iqDeferreds[iq["id"]]
        except KeyError:
            pass
        else:
            del xs.iqDeferreds[iq["id"]]
            iq.handled = True
            if iq['type'] == 'error':
                d.errback(error.exceptionFromStanza(iq))
            else:
                d.callback(iq)


    def disconnected(_):
        """
        Make sure deferreds do not linger on after disconnect.

        This errbacks all deferreds of iq's for which no response has been
        received with a L{ConnectionLost} failure. Otherwise, the deferreds
        will never be fired.
        """
        iqDeferreds = xs.iqDeferreds
        xs.iqDeferreds = {}
        for d in iqDeferreds.itervalues():
            d.errback(ConnectionLost())

    xs.iqDeferreds = {}
    xs.iqDefaultTimeout = getattr(xs, 'iqDefaultTimeout', None)
    xs.addObserver(xmlstream.STREAM_END_EVENT, disconnected)
    xs.addObserver('/iq[@type="result"]', callback)
    xs.addObserver('/iq[@type="error"]', callback)
    directlyProvides(xs, ijabber.IIQResponseTracker)



class IQ(domish.Element):
    """
    Wrapper for an iq stanza.

    Iq stanzas are used for communications with a request-response behaviour.
    Each iq request is associated with an XML stream and has its own unique id
    to be able to track the response.

    @ivar timeout: if set, a timeout period after which the deferred returned
                   by C{send} will have its errback called with a
                   L{TimeoutError} failure.
    @type timeout: C{float}
    """

    timeout = None

    def __init__(self, xmlstream, type = "set"):
        """
        @type xmlstream: L{xmlstream.XmlStream}
        @param xmlstream: XmlStream to use for transmission of this IQ

        @type type: L{str}
        @param type: IQ type identifier ('get' or 'set')
        """
        domish.Element.__init__(self, (None, "iq"))
        self.addUniqueId()
        self["type"] = type
        self._xmlstream = xmlstream

    def send(self, to=None):
        """
        Send out this iq.

        Returns a deferred that is fired when an iq response with the same id
        is received. Result responses will be passed to the deferred callback.
        Error responses will be transformed into a
        L{StanzaError<error.StanzaError>} and result in the errback of the
        deferred being invoked.

        @rtype: L{defer.Deferred}
        """
        if to is not None:
            self["to"] = to

        if not ijabber.IIQResponseTracker.providedBy(self._xmlstream):
            upgradeWithIQResponseTracker(self._xmlstream)

        d = defer.Deferred()
        self._xmlstream.iqDeferreds[self['id']] = d

        timeout = self.timeout or self._xmlstream.iqDefaultTimeout
        if timeout is not None:
            def onTimeout():
                del self._xmlstream.iqDeferreds[self['id']]
                d.errback(TimeoutError("IQ timed out"))

            call = self._xmlstream._callLater(timeout, onTimeout)

            def cancelTimeout(result):
                if call.active():
                    call.cancel()

                return result

            d.addBoth(cancelTimeout)

        self._xmlstream.send(self)
        return d
