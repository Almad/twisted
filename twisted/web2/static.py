# -*- test-case-name: twisted.web2.test.test_web -*-
# Copyright (c) 2001-2004 Twisted Matrix Laboratories.
# See LICENSE for details.


"""I deal with static resources.
"""

# System Imports
import os, stat, string
import cStringIO as StringIO
import traceback
import warnings
import types
import urllib
import time

# Sibling Imports
from twisted.web2 import error, http_headers
from twisted.web2 import http, iweb, stream, responsecode

# Twisted Imports
from twisted.python import threadable, components, filepath
from twisted.python.util import InsensitiveDict
from twisted.python.runtime import platformType
from zope.interface import implements

dangerousPathError = error.Error(responsecode.NOT_FOUND, "Invalid request URL.")

def redirectTo(URL, request):
    # FIXME:
    request.code = FOUND
    request.setHeader("location", url)
    return """
<html>
    <head>
        <meta http-equiv=\"refresh\" content=\"0;URL=%(url)s\">
    </head>
    <body bgcolor=\"#FFFFFF\" text=\"#000000\">
    <a href=\"%(url)s\">click here</a>
    </body>
</html>
""" % {'url': URL}


def isDangerous(path):
    return path == '..' or '/' in path or os.sep in path


class Data:
    implements(iweb.IResource)
    
    """
    This is a static, in-memory resource.
    """
    
    def __init__(self, data, type):
        self.data = data
        self.type = type

    def renderHTTP(self, ctx):
        request = iweb.IRequest(ctx)
        request.out_headers.setRawHeaders("content-type", (self.type, ))
        request.out_headers.setHeader("content-length", len(self.data))
        if request.method == "HEAD":
            return ''
        return self.data

components.backwardsCompatImplements(Data)

def addSlash(request):
    return "http%s://%s%s/" % (
        request.isSecure() and 's' or '',
        request.getHeader("host"),
        (string.split(request.uri,'?')[0]))

class Registry(components.Componentized):
    """
    I am a Componentized object that will be made available to internal Twisted
    file-based dynamic web content such as .rpy and .epy scripts.
    """

    def __init__(self):
        components.Componentized.__init__(self)
        self._pathCache = {}

    def cachePath(self, path, rsrc):
        self._pathCache[path] = rsrc

    def getCachedPath(self, path):
        return self._pathCache.get(path)

class UnsatisfiableRangeRequest(Exception):
    pass

def canonicalizeRange(startend, entitySize):
    """Return canonicalized (start, end) or raises UnsatisfiableRangeRequest
    exception. NOTE: end is the last byte *inclusive*, which is not
    the usual convention in python!"""
    
    start,end = startend
    # handle "-500" ranges
    if start is None:
        start = min(0, size-end)
        end = None
    
    if end is None or end >= size:
        end = size - 1

    if start >= size:
        raise UnsatisfiableRangeRequest
    
    return start,end

def loadMimeTypes(mimetype_locations=['/etc/mime.types']):
    """
    Multiple file locations containing mime-types can be passed as a list.
    The files will be sourced in that order, overriding mime-types from the
    files sourced beforehand, but only if a new entry explicitly overrides
    the current entry.
    """
    import mimetypes
    # Grab Python's built-in mimetypes dictionary.
    contentTypes = mimetypes.types_map
    # Update Python's semi-erroneous dictionary with a few of the
    # usual suspects.
    contentTypes.update(
        {
            '.conf':  'text/plain',
            '.diff':  'text/plain',
            '.exe':   'application/x-executable',
            '.flac':  'audio/x-flac',
            '.java':  'text/plain',
            '.ogg':   'application/ogg',
            '.oz':    'text/x-oz',
            '.swf':   'application/x-shockwave-flash',
            '.tgz':   'application/x-gtar',
            '.wml':   'text/vnd.wap.wml',
            '.xul':   'application/vnd.mozilla.xul+xml',
            '.py':    'text/plain',
            '.patch': 'text/plain',
        }
    )
    # Users can override these mime-types by loading them out configuration
    # files (this defaults to ['/etc/mime.types']).
    for location in mimetype_locations:
        if os.path.exists(location):
            contentTypes.update(mimetypes.read_mime_types(location))
            
    return contentTypes

def getTypeAndEncoding(filename, types, encodings, defaultType):
    p, ext = os.path.splitext(filename)
    ext = ext.lower()
    if encodings.has_key(ext):
        enc = encodings[ext]
        ext = os.path.splitext(p)[1].lower()
    else:
        enc = None
    type = types.get(ext, defaultType)
    return type, enc

from twisted.web2 import resource

class File:
    """
    File is a resource that represents a plain non-interpreted file
    (although it can look for an extension like .rpy or .cgi and hand the
    file to a processor for interpretation if you wish). Its constructor
    takes a file path.

    Alternatively, you can give a directory path to the constructor. In this
    case the resource will represent that directory, and its children will
    be files underneath that directory. This provides access to an entire
    filesystem tree with a single Resource.

    If you map the URL 'http://server/FILE' to a resource created as
    File('/tmp'), then http://server/FILE/ will return an HTML-formatted
    listing of the /tmp/ directory, and http://server/FILE/foo/bar.html will
    return the contents of /tmp/foo/bar.html .
    """

    implements(iweb.IResource)
    
    contentTypes = loadMimeTypes()

    contentEncodings = {
        ".gz" : "gzip",
        ".bz2": "bzip2"
        }

    processors = {}

    indexNames = ["index", "index.html", "index.htm", "index.trp", "index.rpy"]

    type = None

    def __init__(self, path, defaultType="text/plain", ignoredExts=(), registry=None, processors=None, indexNames=None):
        """Create a file with the given path.
        """
        self.fp = filepath.FilePath(path)
        # Remove the dots from the path to split
        self.defaultType = defaultType
        self.ignoredExts = list(ignoredExts)
        self.registry = registry or Registry()
        self.children = {}
        if processors is not None:
            self.processors = processors
        if indexNames is not None:
            self.indexNames = indexNames

    def ignoreExt(self, ext):
        """Ignore the given extension.

        Serve file.ext if file is requested
        """
        self.ignoredExts.append(ext)

    def directoryListing(self):
        from twisted.web2 import dirlist
        return dirlist.DirectoryLister(self.fp.path,
                                       self.listNames(),
                                       self.contentTypes,
                                       self.contentEncodings,
                                       self.defaultType)

    def putChild(self, name, child):
        self.children[name] = child
        
    def locateChild(self, request, segments):
        r = self.children.get(segments[0], None)
        if r:
            return r, segments[1:]
        
        path=segments[0]
        
        self.fp.restat()
        
        if not self.fp.isdir():
            return None, ()

        if path:
            fpath = self.fp.child(path)
        else:
            fpath = self.fp.childSearchPreauth(*self.indexNames)
            if fpath is None:
                return self.directoryListing(), segments[1:]

        if not fpath.exists():
            fpath = fpath.siblingExtensionSearch(*self.ignoredExts)
            if fpath is None:
                return None, ()

        # Don't run processors on directories - if someone wants their own
        # customized directory rendering, subclass File instead.
        if fpath.isfile():
            if platformType == "win32":
                # don't want .RPY to be different than .rpy, since that
                # would allow source disclosure.
                processor = InsensitiveDict(self.processors).get(fpath.splitext()[1])
            else:
                processor = self.processors.get(fpath.splitext()[1])
            if processor:
                return (
                    processor(fpath.path, self.registry),
                    segments[1:])

        return self.createSimilarFile(fpath.path), segments[1:]

    def renderHTTP(self, context):
        """You know what you doing."""
        self.fp.restat()
        request = iweb.IRequest(context)
        
        if self.type is None:
            self.type, self.encoding = getTypeAndEncoding(self.fp.basename(),
                                                          self.contentTypes,
                                                          self.contentEncodings,
                                                          self.defaultType)

        if not self.fp.exists():
            return renderer.FourOhFour()

        if self.fp.isdir():
            return self.redirectWithSlash(request)

        request.out_headers.setHeader('accept-ranges',('bytes',))

        if self.type:
            request.out_headers.setRawHeaders('content-type', (self.type,))
        if self.encoding:
            request.out_headers.setHeader('content-encoding', self.encoding)

        try:
            f = self.fp.open()
        except IOError, e:
            import errno
            if e[0] == errno.EACCES:
                return error.ForbiddenResource().render(request)
            else:
                raise

        st = os.fstat(f.fileno())
        
        #for content-length
        start = 0
        size = st.st_size
        
        request.out_headers.setHeader('last-modified', st.st_mtime)
        
        # Mark ETag as weak if it was modified recently, as it could
        # be modified again without changing mtime.
        weak = (time.time() - st.st_mtime <= 1)
        
        etag = http_headers.ETag(
            "%X-%X-%X" % (st.st_ino, st.st_size, st.st_mtime),
            weak=weak)
        
        request.out_headers.setHeader('etag', etag)
        
        request.checkPreconditions()
        
        rangespec = request.in_headers.getHeader('range')

        
        # If file size is 0, don't try to do range stuff.
        if size > 0 and rangespec is not None:
            # Check that we support range requested, and that the If-Range check
            # doesn't fail.
            # TODO: support returning multipart/byteranges for multi-part ranges
            if angespec[0] == 'bytes' and len(rangespec[1]) == 1 and request.checkIfRange():
                # This is a request for partial data...
                try:
                    start,end = canonicalizeRange(rangespec[1][0], size)
                except UnsatisfiableRangeRequest:
                    pass
                else:
                    request.code = http.PARTIAL_CONTENT
                    request.out_headers.setHeader('content-range',('bytes',start, end, size))
                    #content-length should be the actual size of the stuff we're
                    #sending, not the full size of the on-server entity.
                    size = end - start

        request.out_headers.setHeader('content-length', size)
        
        # if this is a "HEAD" request, we shouldn't return any data
        if request.method == "HEAD":
            return ''
        
        # return data
        request.acceptData()
        
        return stream.FileProducer(f, start, size).beginProducing(request)

    def redirectWithSlash(self, request):
        return redirectTo(addSlash(request), request)

    def listNames(self):
        if not self.fp.isdir():
            return []
        directory = self.fp.listdir()
        directory.sort()
        return directory

    def createSimilarFile(self, path):
        return self.__class__(path, self.defaultType, self.ignoredExts, self.registry,
                              self.processors, self.indexNames[:])

"""I contain AsIsProcessor, which serves files 'As Is'
   Inspired by Apache's mod_asis
"""

class ASISProcessor:
    implements(iweb.IResource)
    
    def __init__(self, path, registry=None):
        self.path = path
        self.registry = registry or static.Registry()

    def renderHTTP(self, request):
        request.startedWriting = 1
        return static.File(self.path, self.registry)

    def locateChild(self, request):
        return FourOhFour(), ()

components.backwardsCompatImplements(ASISProcessor)


# Test code
if __name__ == '__builtin__':
    # Running from twistd -y
    from twisted.application import service, strports
    from twisted.web2 import server
    res = File('/')
    application = service.Application("demo")
    s = strports.service('8080', server.Site(res))
    s.setServiceParent(application)
