
from sys import stdout
from twisted.python import log
log.discardLogs()
from twisted.internet import reactor
from twisted.spread import pb

def connected(perspective):
    perspective.callRemote('nextQuote').addCallbacks(success, failure)

def success(quote):
    stdout.write(quote + "\n")
    reactor.stop()

def failure(error):
    stdout.write("Failed to obtain quote.\n")
    reactor.stop()

factory = pb.PBClientFactory()
reactor.connectTCP(
    "localhost", # host name
    pb.portno, # port number
    factory, # factory
    )
factory.getPerspective(
    "guest", # identity name
    "guest", # password
    "twisted.quotes", # service name
    "guest", # perspective name (usually same as identity)
    None, # client reference, used to initiate server->client calls
    ).addCallbacks(connected, # what to do when we get connected
                   failure) # and what to do when we can't

reactor.run() # start the main loop

