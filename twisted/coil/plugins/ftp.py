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

"""Coil plugin for FTP server."""

# Twisted Imports
from twisted.coil import coil
from twisted.protocols import ftp
from twisted.python import roots

# System Imports
import types, os


# XXX fix me - passwords are stored in a subdict, not as the values
#
#class UserCollection(roots.Homogenous):
#    """A username/password collection."""
#    
#    entityType = types.StringType
#    
#    def __init__(self, factory):
#        roots.Homogenous.__init__(self, factory.userdict)
#
#    def getEntityType(self):
#        return "Password"
#    
#    def getNameType(self):
#        return "Username"


class FTPConfigurator(coil.Configurator, roots.Locked):

    configurableClass = ftp.FTPFactory
    
    configTypes = {"anonymous": ["boolean", "Allow Anonymous Logins", ""],
                   "useranonymous": [types.StringType, "Anonymous Username", "Username for anonymous users, typically 'anonymous'."],
                   "otp": ["boolean", "OTP", "Use One Time Passwords."],
                   "root": [types.StringType, "Root", "The root folder for the FTP server."],
                   "thirdparty": ["boolean", "Allow 3rd-party Transfers", "Allow A to forward data to B. May be a security risk."],
                   }

    configName = 'FTP Server'

    def __init__(self, instance):
        roots.Locked.__init__(self)
        coil.Configurator.__init__(self, instance)
        #self.putEntity("users", UserCollection(self.instance))
        self.lock()
    
    def config_root(self, root):
        if not os.path.exists(root):
            raise coil.InvalidConfiguration("No such path: %s" % root)
        elif not os.access(root, os.O_RDONLY):
            raise coil.InvalidConfiguration("No permission to read path: %s" % root)
        else:
            self.instance.root = root


def factory(container, name):
    return ftp.FTPFactory()


coil.registerConfigurator(FTPConfigurator, factory)
