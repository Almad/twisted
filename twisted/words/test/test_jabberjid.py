#
# Copyright (c) 2001-2004 Twisted Matrix Laboratories.
# See LICENSE for details.


import sys, os
from twisted.trial import unittest

from twisted.words.protocols.jabber import jid

class JIDParsingTest(unittest.TestCase):
    def testParse(self):
        # Basic forms
        self.assertEquals(jid.parse("user@host/resource"),
                          ("user", "host", "resource"))
        self.assertEquals(jid.parse("user@host"),
                          ("user", "host", None))
        self.assertEquals(jid.parse("host"),
                          (None, "host", None))
        self.assertEquals(jid.parse("host/resource"),
                          (None, "host", "resource"))

        # More interesting forms
        self.assertEquals(jid.parse("foo/bar@baz"),
                          (None, "foo", "bar@baz"))
        self.assertEquals(jid.parse("boo@foo/bar@baz"),
                          ("boo", "foo", "bar@baz"))
        self.assertEquals(jid.parse("boo@foo/bar/baz"),
                          ("boo", "foo", "bar/baz"))
        self.assertEquals(jid.parse("boo/foo@bar@baz"),
                          (None, "boo", "foo@bar@baz"))
        self.assertEquals(jid.parse("boo/foo/bar"),
                          (None, "boo", "foo/bar"))
        self.assertEquals(jid.parse("boo//foo"),
                          (None, "boo", "/foo"))
        
    def testInvalid(self):
        # No host
        try:
            jid.parse("user@")
            assert 0
        except jid.InvalidFormat:
            assert 1

        # Double @@
        try:
            jid.parse("user@@host")
            assert 0
        except jid.InvalidFormat:
            assert 1

        # Multiple @
        try:
            jid.parse("user@host@host")
            assert 0
        except jid.InvalidFormat:
            assert 1
            

class JIDClassTest(unittest.TestCase):
    def testBasic(self):
        j = jid.intern("user@host")
        self.assertEquals(j.userhost(), "user@host")
        self.assertEquals(j.user, "user")
        self.assertEquals(j.host, "host")
        self.assertEquals(j.resource, None)

        j2 = jid.intern("user@host")
        self.assertEquals(id(j), id(j2))

        j_uhj = j.userhostJID()
        self.assertEquals(id(j), id(j_uhj))
