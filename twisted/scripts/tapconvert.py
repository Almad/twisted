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

from twisted.python import log, usage, util
from twisted.persisted import styles

# System imports
import os, sys
try:
    import cPickle as pickle
except ImportError:
    import pickle

try:
    import cStringIO as StringIO
except ImportError:
    import StringIO


mainMod = sys.modules['__main__']

# Functions from twistd/mktap

class EverythingEphemeral(styles.Ephemeral):
    def __getattr__(self, key):
        try:
            return getattr(mainMod, key)
        except AttributeError:
            log.msg("Warning!  Loading from __main__: %s" % key)
            return styles.Ephemeral()


class LoaderCommon:
    """Simple logic for loading persisted data"""

    loadmessage = "Loading %s..."

    def __init__(self, filename, encrypted=None, passphrase=None):
        self.filename = filename
        self.encrypted = encrypted
        self.passphrase = passphrase

    def load(self):
        "Returns the application"
        log.msg(self.loadmessage % self.filename)
        if self.encrypted:
            self.data = open(self.filename, 'r').read()
            self.decrypt()
        else:
            self.read()
        return self.decode()       
        
    def read(self):
        self.data = open(self.filename, 'r').read()
        
    def decrypt(self):
        try:
            import md5
            from Crypto.Cipher import AES
            self.data = AES.new(md5.new(self.passphrase).digest()[:16]).decrypt(self.data)
        except ImportError:
            print "The --decrypt flag requires the PyCrypto module, no file written."
            
    def decode(self):
        pass


class LoaderXML(LoaderCommon):

    loadmessage = '<Loading file="%s" />' 

    def decode(self):
        from twisted.persisted.marmalade import unjellyFromXML
        sys.modules['__main__'] = EverythingEphemeral()
        application = unjellyFromXML(StringIO.StringIO(self.data))
        sys.modules['__main__'] = mainMod
        styles.doUpgrade()
        return application


class LoaderPython(LoaderCommon):

    def read(self):
        pass

    def decrypt(self):
        log.msg("Python files are never encrypted")

    def decode(self):
        pyfile = os.path.abspath(self.filename)
        d = {'__file__': self.filename}
        execfile(pyfile, d, d)
        try:
            application = d['application']
        except KeyError:
            log.msg("Error - python file %s must set a variable named 'application', an instance of twisted.internet.app.Application. No such variable was found!" % repr(self.filename))
            sys.exit()
        return application


class LoaderSource(LoaderCommon):

    def decode(self):
        from twisted.persisted.aot import unjellyFromSource
        sys.modules['__main__'] = EverythingEphemeral()
        application = unjellyFromSource(StringIO.StringIO(self.data))
        application.persistStyle = "aot"
        sys.modules['__main__'] = mainMod
        styles.doUpgrade()
        return application


class LoaderTap(LoaderCommon):

    def decode(self):
        sys.modules['__main__'] = EverythingEphemeral()
        application = pickle.load(StringIO.StringIO(self.data))
        sys.modules['__main__'] = mainMod
        styles.doUpgrade()
        return application


loaders = {'python': LoaderPython,
           'xml': LoaderXML,
           'source': LoaderSource,
           'pickle': LoaderTap}


def loadPersisted(filename, kind, encrypted, passphrase):
    "Loads filename, of the specified kind and returns an application"
    Loader = loaders[kind]
    l = Loader(filename, encrypted, passphrase)
    application = l.load()
    return application


def savePersisted(app, filename, encrypted):
    if encrypted:
        try:
            import Crypto
            app.save(filename=filename, passphrase=util.getPassword("Encryption passphrase: "))
        except ImportError:
            print "The --encrypt flag requires the PyCrypto module, no file written."
    else:
        app.save(filename=filename)


class ConvertOptions(usage.Options):
    synopsis = "Usage: tapconvert [options]"
    optParameters = [
        ['in',      'i', None,     "The filename of the tap to read from"],
        ['out',     'o', None,     "A filename to write the tap to"],
        ['typein',  'f', 'guess',  "The  format to use; this can be 'guess', 'python', 'pickle', 'xml', or 'source'."],
        ['typeout', 't', 'source', "The output format to use; this can be 'pickle', 'xml', or 'source'."],
        ['decrypt', 'd', None,     "The specified tap/aos/xml file is encrypted."],
        ['encrypt', 'e', None,     "Encrypt file before writing"]]
    
    
    def postOptions(self):
        if self['in'] is None:
            self.opt_help()
            raise usage.UsageError("You must specify the input filename.")


def guessType(filename):
    ext = os.path.splitext(filename)[1]
    try:
        return {
            '.py':  'python',
            '.tap': 'pickle',
            '.tas': 'source',
            '.tax': 'xml'
        }[ext]
    except KeyError:
        raise usage.UsageError("Could not guess type for '%s'" % (filename,))


def run():
    options = ConvertOptions()
    try:
        options.parseOptions(sys.argv[1:])
    except usage.UsageError, e:
        print e
        return

    passphrase = None
    if options.opts['decrypt']:
        import getpass
        passphrase = getpass.getpass('Passphrase: ')

    if options["typein"] == "guess":
        options["typein"] = guessType(options["in"])

    a = loadPersisted(options["in"], options["typein"], options["decrypt"], passphrase)
    try:
        a.persistStyle = ({'xml': 'xml',
                           'source': 'aot', 
                           'pickle': 'pickle'}
                          [options["typeout"]])
    except KeyError:
        print "Error: Unsupported output type."
    else:
        savePersisted(a, filename=options["out"], encrypted=options["encrypt"])

if __name__ == '__main__':
    run()

