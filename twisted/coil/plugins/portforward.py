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

"""Coil plugin for telnet shell."""

# Twisted Imports
from twisted.coil import coil
from twisted.protocols import portforward

# System Imports
import types


class ProxyConfigurator(coil.Configurator):

    configurableClass = portforward.ProxyFactory
    
    configTypes = {'host': [types.StringType, "Remote Host", "Host to forward to, e.g. 'www.yahoo.com'."],
                   'port': [types.IntType, "Remote Port", "Port to forward to, e.g. 80."]
                  }


    configName = 'TCP Port Forwarder'

    def config_port(self, port):
        if not (65536 > port > 0):
            raise ValueError, "not a valid IP port"
        self.instance.port = port


def factory(container, name):
    return portforward.ProxyFactory("localhost", 80)


coil.registerConfigurator(ProxyConfigurator, factory)
