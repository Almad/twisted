"""Test win32 shortcut script
"""

from twisted.trial import unittest

import os
if os.name == 'nt':

    from twisted.python import shortcut
    import os.path
    import tempfile
    import sys

    class ShortcutTest(unittest.TestCase):
        def testCreate(self):
            s1=shortcut.Shortcut("test_shortcut.py")
            tempname=tempfile.mktemp('.lnk')
            s1.save(tempname)
            assert os.path.exists(tempname)
            sc=shortcut.open(tempname)
            assert sc.GetPath(0)[0].endswith('test_shortcut.py')
