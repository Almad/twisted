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

from twisted.trial import unittest

from twisted.python import util
from twisted.python.runtime import platformType
import os.path, sys
import shutil

class UtilTestCase(unittest.TestCase):

    def testUniq(self):
        l = ["a", 1, "ab", "a", 3, 4, 1, 2, 2, 4, 6]
        self.assertEquals(util.uniquify(l), ["a", 1, "ab", 3, 4, 2, 6])

    def testRaises(self):
        self.failUnless(util.raises(ZeroDivisionError, divmod, 1, 0))
        self.failIf(util.raises(ZeroDivisionError, divmod, 0, 1))

        try:
            util.raises(TypeError, divmod, 1, 0)
        except ZeroDivisionError:
            pass
        else:
            raise unittest.FailTest, "util.raises didn't raise when it should have"

class OrderedDictTest(unittest.TestCase):
    def testOrderedDict(self):
        d = util.OrderedDict()
        d['a'] = 'b'
        d['b'] = 'a'
        d[3] = 12
        d[1234] = 4321
        self.assertEquals(repr(d), "{'a': 'b', 'b': 'a', 3: 12, 1234: 4321}")
        self.assertEquals(d.values(), ['b', 'a', 12, 4321])
        del d[3]
        self.assertEquals(repr(d), "{'a': 'b', 'b': 'a', 1234: 4321}")
        self.assertEquals(d, {'a': 'b', 'b': 'a', 1234:4321})
        self.assertEquals(d.keys(), ['a', 'b', 1234])
        item = d.popitem()
        self.assertEquals(item, (1234, 4321))

    def testInitialization(self):
        d = util.OrderedDict({'monkey': 'ook',
                              'apple': 'red'})
        self.failUnless(d._order)

class InsensitiveDictTest(unittest.TestCase):
    def testPreserve(self):
        InsensitiveDict=util.InsensitiveDict
        dct=InsensitiveDict({'Foo':'bar', 1:2, 'fnz':{1:2}}, preserve=1)
        self.assertEquals(dct['fnz'], {1:2})
        self.assertEquals(dct['foo'], 'bar')
        self.assertEquals(dct.copy(), dct)
        self.assertEquals(dct['foo'], dct.get('Foo'))
        assert 1 in dct and 'foo' in dct
        self.assertEquals(eval(repr(dct)), dct)
        keys=['Foo', 'fnz', 1]
        for x in keys:
            assert x in dct.keys()
            assert (x, dct[x]) in dct.items()
        self.assertEquals(len(keys), len(dct))
        del dct[1]
        del dct['foo']

    def testNoPreserve(self):
        InsensitiveDict=util.InsensitiveDict
        dct=InsensitiveDict({'Foo':'bar', 1:2, 'fnz':{1:2}}, preserve=0)
        keys=['foo', 'fnz', 1]
        for x in keys:
            assert x in dct.keys()
            assert (x, dct[x]) in dct.items()
        self.assertEquals(len(keys), len(dct))
        del dct[1]
        del dct['foo']




def reversePassword():
    password = util.getPassword()
    return reverseString(password)

def reverseString(s):
    s = list(s)
    s.reverse()
    s = ''.join(s)
    return s

class GetPasswordTest(unittest.TestCase):
    def testStdIn(self):
        """Making sure getPassword accepts a password from standard input.
        """
        from os import path
        import twisted
        # Fun path games because for my sub-process, 'import twisted'
        # doesn't always point to the package containing this test
        # module.
        script = """\
import sys
sys.path.insert(0, \"%(dir)s\")
from twisted.test import test_util
print test_util.util.__version__
print test_util.reversePassword()
""" % {'dir': path.dirname(path.dirname(twisted.__file__))}
        cmd_in, cmd_out, cmd_err = os.popen3("%(python)s -c '%(script)s'" %
                                             {'python': sys.executable,
                                              'script': script})
        cmd_in.write("secret\n")
        cmd_in.close()
        try:
            errors = cmd_err.read()
        except IOError, e:
            # XXX: Improper kludge to appease buildbot!  I'm not really sure
            # why this happens, and without that knowledge, I SHOULDN'T be
            # just catching and discarding this error.
            import errno
            if e.errno == errno.EINTR:
                errors = ''
            else:
                raise
        self.failIf(errors, errors)
        uversion = cmd_out.readline()[:-1]
        self.failUnlessEqual(uversion, util.__version__,
                             "I want to test module version %r, "
                             "but the subprocess is using version %r." %
                             (util.__version__, uversion))
        # stripping print's trailing newline.
        secret = cmd_out.read()[:-1]
        # The reversing trick it so make sure that there's not some weird echo
        # thing just sending back what we type in.
        self.failUnlessEqual(reverseString(secret), "secret")

    if platformType != "posix":
        testStdIn.skip = "unix only"


class SearchUpwardsTest(unittest.TestCase):
    def testSearchupwards(self):
        os.makedirs('searchupwards/a/b/c')
        file('searchupwards/foo.txt', 'w').close()
        file('searchupwards/a/foo.txt', 'w').close()
        file('searchupwards/a/b/c/foo.txt', 'w').close()
        os.mkdir('searchupwards/bar')
        os.mkdir('searchupwards/bam')
        os.mkdir('searchupwards/a/bar')
        os.mkdir('searchupwards/a/b/bam')
        actual=util.searchupwards('searchupwards/a/b/c', 
                                  files=['foo.txt'], 
                                  dirs=['bar', 'bam'])
        expected=os.path.abspath('searchupwards') + os.sep
        self.assertEqual(actual, expected)
        shutil.rmtree('searchupwards')
        actual=util.searchupwards('searchupwards/a/b/c', 
                                  files=['foo.txt'], 
                                  dirs=['bar', 'bam'])
        expected=None
        self.assertEqual(actual, expected)
