
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
#
# $Id: mktap.py,v 1.30 2003/03/14 05:35:01 exarkun Exp $

""" Implementation module for the `mktap` command.
"""

from twisted.protocols import telnet
from twisted.internet import app
from twisted.python import usage, util
from twisted.spread import pb

import sys, traceback, os, cPickle, glob
try:
    import pwd
except ImportError:
    pwd = None
try:
    import grp
except ImportError:
    grp = None


from twisted.python.plugin import getPlugIns


# !!! This code should be refactored; also,
# I bet that it shares a lot with other scripts
# (i.e. is badly cut'n'pasted).

def findAGoodName(x):
    return getattr(x, 'tapname', getattr(x, 'name', getattr(x, 'module')))

def loadPlugins(debug = 0, progress = 0):
    try:
        plugins = getPlugIns("tap", debug, progress)
    except IOError:
        print "Couldn't load the plugins file!"
        sys.exit(2)

    tapLookup = {}
    for plug in plugins:
        if hasattr(plug, 'tapname'):
            shortTapName = plug.tapname
        else:
            shortTapName = plug.module.split('.')[-1]
        tapLookup[shortTapName] = plug

    return tapLookup


def getModule(tapLookup, type):
    try:
        mod = tapLookup[type].load()
        return mod
    except KeyError:
        print """Please select one of: %s""" % ' '.join(tapLookup.keys())
        sys.exit(2)

class GeneralOptions(usage.Options):
    synopsis = """Usage:    mktap [options] <command> [command options]
 """

    optParameters = [['uid', 'u', None, "The uid to run as."],
                  ['gid', 'g', None, "The gid to run as."],
                  ['append', 'a', None,   "An existing .tap file to append the plugin to, rather than creating a new one."],
                  ['type', 't', 'pickle', "The output format to use; this can be 'pickle', 'xml', or 'source'."],
                  ['appname', 'n', None, "The process name to use for this application."]]

    optFlags = [['xml', 'x',       "DEPRECATED: same as --type=xml"],
                ['source', 's',    "DEPRECATED: same as --type=source"],
                ['encrypted', 'e', "Encrypt file before writing"],
                ['progress', 'p',  "Show progress of plugin loading"],
                ['debug', 'd',     "Show debug information for plugin loading"]]


    def __init__(self, tapLookup):
        usage.Options.__init__(self)
        self.subCommands = []
        for (x, y) in tapLookup.items():
            self.subCommands.append(
                [x, None, (lambda obj = y: obj.load().Options()), getattr(y, 'description', '')]
             )
        self.subCommands.sort()
        self['help'] = 0 # default

    def opt_help(self):
        """display this message"""
        # Ugh, we can't print the help now, we need to let getopt
        # finish parsinsg and parseArgs to run.
        self['help'] = 1

    def postOptions(self):
        self['progress'] = int(self['progress'])
        self['debug'] = int(self['debug'])

        # backwards compatibility for old --xml and --source options
        if self['xml']:
            self['type'] = 'xml'
        if self['source']:
            self['type'] = 'source'

    def parseArgs(self, *args):
        self.args = args


# Rest of code in "run"

def run():
    tapLookup = loadPlugins()
    options = GeneralOptions(tapLookup)
    if hasattr(os, 'getgid'):
        options['uid'] = os.getuid()
        options['gid'] = os.getgid()
    try:
        options.parseOptions(sys.argv[1:])
        # XXX - Yea, this is FILTH FILTH FILTH
        if options['debug'] or options['progress']:
            from twisted.python import log
            log.startLogging(sys.stdout)
            tapLookup = loadPlugins(options['debug'], options['progress'])
    except SystemExit:
        # We don't really want to catch this at all...
        raise
    except Exception, e:
        # XXX: While developing, I find myself frequently disabling
        # this except block when I want to see what screwed up code
        # caused my updateApplication crash.  That probably means
        # we're not doing something right here.  - KMT
        print str(sys.exc_value)
        print str(options)
        sys.exit(2)

    if options['help'] or not hasattr(options, 'subOptions'):
        if hasattr(options, 'subOptions'):
            options.subOptions.opt_help()
        usage.Options.opt_help(options)
        sys.exit()

    mod = getModule(tapLookup, options.subCommand)

    if options['uid'] is not None:
        try:
            options['uid'] = int(options['uid'])
        except ValueError:
            if not pwd:
                raise
            options['uid'] = pwd.getpwnam(options['uid'])[2]
    if options['gid'] is not None:
        try:
            options['gid'] = int(options['gid'])
        except ValueError:
            if not grp:
                raise
            options['gid'] = grp.getgrnam(options['gid'])[2]

    if not options['append']:
        a = app.Application(options.subCommand, options['uid'], options['gid'])
    else:
        if os.path.exists(options['append']):
            a = cPickle.load(open(options['append'], 'rb'))
        else:
            a = app.Application(options.subCommand, int(options['uid']), int(options['gid']))

    try:
        mod.updateApplication(a, options.subOptions)
    except usage.error, ue:
        print "Usage Error: %s" % ue
        options.subOptions.opt_help()
        sys.exit(1)

    if options['appname']:
        a.processName = options['appname']

    # backwards compatible interface
    if hasattr(mod, "getPorts"):
        print "The use of getPorts() is deprecated."
        for portno, factory in mod.getPorts():
            a.listenTCP(portno, factory)

    a.persistStyle = ({'xml': 'xml',
                       'source': 'aot',
                       'pickle': 'pickle'}
                       [options['type']])
    if options['encrypted']:
        try:
            import Crypto
            a.save(passphrase=util.getPassword("Encryption passphrase: "))
        except ImportError:
            print "The --encrypt flag requires the PyCrypto module, no file written."
    elif options['append']:
        a.save(filename=options['append'])
    else:
        a.save()

# Make it script-callable for testing purposes
if __name__ == "__main__":
    run()
