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

"""Telnet-based shell."""

# twisted imports
from twisted.protocols import telnet
from twisted.internet import protocol
from twisted.python import log, failure

# system imports
import string, copy, sys
from cStringIO import StringIO


class Shell(telnet.Telnet):
    """A Python command-line shell."""
    
    def connectionMade(self):
        telnet.Telnet.connectionMade(self)
        self.lineBuffer = []
    
    def loggedIn(self):
        self.transport.write(">>> ")
    
    def checkUserAndPass(self, username, password):
        return ((self.factory.username == username) and (password == self.factory.password))

    def write(self, data):
        """Write some data to the transport.
        """
        self.transport.write(data)

    def telnet_Command(self, cmd):
        if self.lineBuffer:
            if not cmd:
                cmd = string.join(self.lineBuffer, '\n') + '\n\n\n'
                self.doCommand(cmd)
                self.lineBuffer = []
                return "Command"
            else:
                self.lineBuffer.append(cmd)
                self.transport.write("... ")
                return "Command"
        else:
            self.doCommand(cmd)
            return "Command"
    
    def doCommand(self, cmd):

        # TODO -- refactor this, Reality.author.Author, and the manhole shell
        #to use common functionality (perhaps a twisted.python.code module?)
        fn = '$telnet$'
        result = None
        try:
            out = sys.stdout
            sys.stdout = self
            try:
                code = compile(cmd,fn,'eval')
                result = eval(code, self.factory.namespace)
            except:
                try:
                    code = compile(cmd, fn, 'exec')
                    exec code in self.factory.namespace
                except SyntaxError, e:
                    if not self.lineBuffer and str(e)[:14] == "unexpected EOF":
                        self.lineBuffer.append(cmd)
                        self.transport.write("... ")
                        return
                    else:
                        failure.Failure().printTraceback(file=self)
                        log.deferr()
                        self.write('\r\n>>> ')
                        return
                except:
                    io = StringIO()
                    failure.Failure().printTraceback(file=self)
                    log.deferr()
                    self.write('\r\n>>> ')
                    return
        finally:
            sys.stdout = out
        
        self.factory.namespace['_'] = result
        if result is not None:
            self.transport.write(repr(result))
            self.transport.write('\r\n')
        self.transport.write(">>> ")



class ShellFactory(protocol.Factory):
    username = "admin"
    password = "admin"
    protocol = Shell

    def __init__(self):
        self.namespace = {}

    def __getstate__(self):
        """This returns the persistent state of this shell factory.
        """
        dict = self.__dict__
        ns = copy.copy(dict['namespace'])
        dict['namespace'] = ns
        if ns.has_key('__builtins__'):
            del ns['__builtins__']
        return dict
