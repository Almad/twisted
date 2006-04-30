# -*- test-case-name: twisted.words.test.test_xmlstream -*-
#
# Copyright (c) 2001-2005 Twisted Matrix Laboratories.
# See LICENSE for details.

""" XML Stream processing.

An XML Stream is defined as a connection over which two XML documents are
exchanged during the lifetime of the connection, one for each direction. The
unit of interaction is a direct child element of the root element (stanza).

The most prominent use of XML Streams is Jabber, but this module is generically
usable. See Twisted Words for Jabber specific protocol support.

Maintainer: U{Ralph Meijer<mailto:twisted@ralphm.ik.nu>}
"""

from twisted.internet import protocol
from twisted.words.xish import domish, utility

STREAM_CONNECTED_EVENT = intern("//event/stream/connected")
STREAM_START_EVENT = intern("//event/stream/start")
STREAM_END_EVENT = intern("//event/stream/end")
STREAM_ERROR_EVENT = intern("//event/stream/error")

class XmlStream(protocol.Protocol, utility.EventDispatcher):
    """ Generic Streaming XML protocol handler.

    This protocol handler will parse incoming data as XML and dispatch events
    accordingly. Incoming stanzas can be handled by registering observers using
    XPath-like expressions that are matched against each stanza. See
    L{utility.EventDispatcher} for details.
    """
    def __init__(self):
        utility.EventDispatcher.__init__(self)
        self.stream = None
        self.rawDataOutFn = None
        self.rawDataInFn = None

    def _initializeStream(self):
        """ Sets up XML Parser. """
        self.stream = domish.elementStream()
        self.stream.DocumentStartEvent = self.onDocumentStart
        self.stream.ElementEvent = self.onElement
        self.stream.DocumentEndEvent = self.onDocumentEnd

    ### --------------------------------------------------------------
    ###
    ### Protocol events
    ###
    ### --------------------------------------------------------------

    def connectionMade(self):
        """ Called when a connection is made.

        Sets up the XML parser and dispatches the L{STREAM_CONNECTED_EVENT}
        event indicating the connection has been established.
        """
        self._initializeStream()
        self.dispatch(self, STREAM_CONNECTED_EVENT)

    def dataReceived(self, data):
        """ Called whenever data is received.

        Passes the data to the XML parser. This can result in calls to the
        DOM handlers. If a parse error occurs, the L{STREAM_ERROR_EVENT} event
        is called to allow for cleanup actions, followed by dropping the
        connection.
        """
        try:
            if self.rawDataInFn: self.rawDataInFn(data)
            self.stream.parse(data)
        except domish.ParserError:
            self.dispatch(self, STREAM_ERROR_EVENT)
            self.transport.loseConnection()

    def connectionLost(self, reason):
        """ Called when the connection is shut down.

        Dispatches the L{STREAM_END_EVENT}.
        """
        self.dispatch(self, STREAM_END_EVENT)
        self.stream = None
        
    ### --------------------------------------------------------------
    ###
    ### DOM events
    ###
    ### --------------------------------------------------------------

    def onDocumentStart(self, rootelem):
        """ Called whenever the start tag of a root element has been received.

        Dispatches the L{STREAM_START_EVENT}.
        """
        self.dispatch(self, STREAM_START_EVENT)    

    def onElement(self, element):
        """ Called whenever a direct child element of the root element has
        been received.

        Dispatches the received element.
        """
        self.dispatch(element)

    def onDocumentEnd(self):
        """ Called whenever the end tag of the root element has been received.

        Closes the connection. This causes C{connectionLost} being called.
        """
        self.transport.loseConnection()

    def setDispatchFn(self, fn):
        """ Set another function to handle elements. """
        self.stream.ElementEvent = fn

    def resetDispatchFn(self):
        """ Set the default function (C{onElement}) to handle elements. """
        self.stream.ElementEvent = self.onElement

    def send(self, obj):
        """ Send data over the stream.

        Sends the given C{obj} over the connection. C{obj} may be instances of
        L{domish.Element}, L{unicode} and L{str}. The first two will be
        properly serialized and/or encoded. L{str} objects must be in UTF-8
        encoding.

        Note: because it is easy to make mistakes in maintaining a properly
        encoded L{str} object, it is advised to use L{unicode} objects
        everywhere when dealing with XML Streams.

        @param obj: Object to be sent over the stream.
        @type obj: L{domish.Element}, L{domish} or L{str}

        """
        if domish.IElement.providedBy(obj):
            obj = obj.toXml()
            
        if isinstance(obj, unicode):
            obj = obj.encode('utf-8')
            
        if self.rawDataOutFn:
            self.rawDataOutFn(obj)
            
        self.transport.write(obj)


class XmlStreamFactory(protocol.ReconnectingClientFactory):
    """ Factory for XmlStream protocol objects as a reconnection client.
    
    This factory generates XmlStream objects when a connection has been
    established. To make sure certain event observers are set up before
    incoming data is processed, you can set up bootstrap event observers using
    C{addBootstrap}.
    """

    def __init__(self):
        self.bootstraps = []

    def buildProtocol(self, addr):
        """ Create an instance of XmlStream.

        The returned instance will have bootstrap event observers registered
        and will proceed to handle input on an incoming connection.
        """
        self.resetDelay()
        xs = XmlStream()
        xs.factory = self
        for event, fn in self.bootstraps: xs.addObserver(event, fn)
        return xs

    def addBootstrap(self, event, fn):
        """ Add a bootstrap event handler. """
        self.bootstraps.append((event, fn))

    def removeBootstrap(self, event, fn):
        """ Remove a bootstrap event handler. """
        self.bootstraps.remove((event, fn))
