#!/usr/bin/env python

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

### Twisted Preamble
# This makes sure that users don't have to set up their environment
# specially in order to run these programs from bin/.
import sys,os,string

if string.find(os.path.abspath(sys.argv[0]),'Twisted') != -1:
    sys.path.append(os.path.dirname(
        os.path.dirname(os.path.abspath(sys.argv[0]))))
sys.path.append('.')
### end of preamble

from twisted.protocols import telnet
from twisted.internet import app, tcp
from twisted.python import usage
from twisted.spread import pb
from twisted.manhole import service
manholeService = service
del service

import sys, traceback, os, cPickle, glob

from twisted.python.plugin import getPlugIns

try:
    plugins = getPlugIns("tap")
except IOError:
    print "Couldn't load the plugins file!"
    sys.exit(2)

tapLookup = {}
for plug in plugins:
    if hasattr(plug, 'tapname'):
        shortTapName = plug.tapname
    else:
        shortTapName = string.split(plug.module, '.')[-1]
    tapLookup[shortTapName] = plug

tapMods = tapLookup.keys()


class GeneralOptions(usage.Options):
    synopsis="""\
Usage::

  mktap 'apptype' [application_options]
  mktap --help 'apptype'

'apptype' can be one of: %s
""" % string.join(tapMods)

    optStrings = [['uid', 'u', '0'],
                  ['gid', 'g', '0'],
                  ['append', 'a', None],
                  ['manholeUser', None, 'manhole',
                   "Login username for manhole service."],
                  ['manholePass', None, None,
                   "Password for manhole service."
                   " (If a password is not specified,"
                   " no manhole service will be created.)"],
                  ['manholePort', None, pb.portno]]

    help = 0
    
    def opt_help(self):
        """display this message"""
        # Ugh, we can't print the help now, we need to let getopt
        # finish parsinsg and parseArgs to run.
        self.help = 1

    def parseArgs(self, *args):
        self.args = args

def getModule(type):
    try:
        mod = tapLookup[type].load()
        return mod
    except KeyError:
        print """Please select one of: %s""" % string.join(tapMods)
        sys.exit(2)

options = GeneralOptions()
if hasattr(os, 'getgid'):
    options.uid = os.getuid()
    options.gid = os.getgid()
try:
    options.parseOptions(sys.argv[1:])
except Exception, e:
    print str(e)
    print str(options)
    sys.exit(2)

if options.help or not options.args:
    if options.args:
        mod = getModule(options.args[0])
        config = mod.Options()
        config.opt_help()
        sys.exit()
    else:
        usage.Options.opt_help(options)
        sys.exit()
else:
    mod = getModule(options.args[0])
try:
    config = mod.Options()
    config.parseOptions(options.args[1:])
except usage.error, ue:
    print "Usage Error: %s" % ue
    config.opt_help()
    sys.exit(1)

if not options.append:
    a = app.Application(options.args[0], int(options.uid), int(options.gid))
else:
    a = cPickle.load(open(options.append))

haveBroker = 0
mod.updateApplication(a, config)

# backwards compatible interface
if hasattr(mod, "getPorts"):
    print "The use of getPorts() is deprecated."
    for portno, factory in mod.getPorts():
        a.listenTCP(portno, factory)

# this seems a rather broken mechanism
for proto in a.ports:
    if isinstance(proto, pb.BrokerFactory):
        haveBroker = 1
        break

# Would you like a manhole with that?
if options.manholePass:
    if not haveBroker:
        bkr = pb.BrokerFactory(pb.AuthRoot(a))
        a.listenTCP(options.manholePort, bkr)

    svc = manholeService.Service(application=a)
    p = svc.createPerspective(options.manholeUser)
    p.makeIdentity(options.manholePass)

a.save()
