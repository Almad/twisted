from twisted.protocols.protocol import Protocol, Factory

### Protocol Implementation

# This is just about the simplest possible protocol

class Echo(Protocol):
    def dataReceived(self, data):
        "As soon as any data is received, write it back."
        self.transport.write(data)

### Persistent Application Builder

# This builds a .spl file

if __name__ == '__main__':
    # Since this is persistent, it's important to get the module naming right
    # (If we just used Echo, then it would be __main__.Echo when it attempted
    # to unpickle)
    import echoserv
    import cPickle, string
    from twisted.internet.main import Application
    factory = Factory()
    factory.protocol = echoserv.Echo
    app = Application("echo")
    app.listenOn(8000,factory)
    app.save("start")
