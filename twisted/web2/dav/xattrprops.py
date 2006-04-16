##
# Copyright (c) 2005 Apple Computer, Inc. All rights reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
# DRI: Wilfredo Sanchez, wsanchez@apple.com
##

"""
DAV Property store using file system extended attributes.

This API is considered private to static.py and is therefore subject to
change.
"""

__all__ = ["xattrPropertyStore"]

import urllib

import xattr


if getattr(xattr, 'xattr', None) is None:
    raise ImportError("wrong xattr package installed")


from twisted.python import log

from twisted.web2.dav import davxml

class xattrPropertyStore (object):
    """

    This implementation uses Bob Ippolito's xattr package, available from:

        http://undefined.org/python/#xattr

    Note that the Bob's xattr package is specific to Linux and Darwin, at least
    presently.
    """
    #
    # Dead properties are stored as extended attributes on disk.  In order to
    # avoid conflicts with other attributes, prefix dead property names.
    #
    deadPropertyXattrPrefix = "WebDAV:"

    def _encode(clazz, name):
        #
        # FIXME: The xattr API in Mac OS 10.4.2 breaks if you have "/" in an
        # attribute name (radar://4202440). We'll quote the strings to get rid
        # of "/" characters for now.
        #
        result = list("{%s}%s" % name)
        for i in range(len(result)):
            c = result[i]
            if c in "%/": result[i] = "%%%02X" % (ord(c),)
        r = clazz.deadPropertyXattrPrefix + ''.join(result)
        return r

    def _decode(clazz, name):
        name = urllib.unquote(name[len(clazz.deadPropertyXattrPrefix):])

        index = name.find("}")
    
        if (index is -1 or not len(name) > index or not name[0] == "{"):
            raise ValueError("Invalid encoded name: %r" % (name,))
    
        return (name[1:index], name[index+1:])

    _encode = classmethod(_encode)
    _decode = classmethod(_decode)

    def __init__(self, resource):
        self.resource = resource
        self.attrs = xattr.xattr(self.resource.fp.path)

    def get(self, qname):
        value = self.attrs[self._encode(qname)]
        doc = davxml.WebDAVDocument.fromString(value)

        return doc.root_element

    def set(self, property):
        log.msg("Writing property %s on file %s"
                % (property.sname(), self.resource.fp.path))

        self.attrs[self._encode(property.qname())] = property.toxml()

        # Update the resource because we've modified it
        self.resource.fp.restat()

    def delete(self, qname):
        log.msg("Deleting property {%s}%s on file %s"
                % (qname[0], qname[1], self.resource.fp.path))

        del(self.attrs[self._encode(qname)])

    def contains(self, qname):
        try:
            return self._encode(qname) in self.attrs
        except TypeError:
            return False

    def list(self):
        prefix     = self.deadPropertyXattrPrefix
        prefix_len = len(prefix)

        return [ self._decode(name) for name in self.attrs if name.startswith(prefix) ]
