from twisted.trial import unittest

from twisted.lore.default import *
from twisted.lore import tree
from twisted.lore import process
from twisted.lore import default

from twisted.python.util import sibpath

from twisted.scripts.lore import getProcessor, getWalker

import os

options = {"template" : sibpath(__file__, "template.tpl"), 'baseurl': '%s', 'ext': '.xhtml' }
d = options

def filenameGenerator(originalFileName, outputExtension):
    return os.path.splitext(originalFileName)[0]+"1"+outputExtension

def filenameGenerator2(originalFileName, outputExtension):
    return os.path.splitext(originalFileName)[0]+"2"+outputExtension


class TestFactory(unittest.TestCase):

    file = sibpath(__file__, 'simple.html')
    linkrel = ""

    def testProcessingFunctionFactory(self):
        htmlGenerator = factory.generate_html(options)
        htmlGenerator(self.file, self.linkrel)
        self.assertEqualFiles('good_simple.xhtml', 'simple.xhtml')

    def testProcessingFunctionFactoryWithFilenameGenerator(self):
        htmlGenerator = factory.generate_html(options, filenameGenerator2)
        htmlGenerator(self.file, self.linkrel)
        self.assertEqualFiles('good_simple.xhtml', 'simple2.xhtml')

    def test_doFile(self):
        templ = microdom.parse(open(d['template']))

        tree.doFile(self.file, self.linkrel, d['ext'], d['baseurl'], templ, d)
        self.assertEqualFiles('good_simple.xhtml', 'simple.xhtml')

    def test_doFile_withFilenameGenerator(self):
        templ = microdom.parse(open(d['template']))

        tree.doFile(self.file, self.linkrel, d['ext'], d['baseurl'], templ, d, filenameGenerator)
        self.assertEqualFiles('good_simple.xhtml', 'simple1.xhtml')

    def test_munge(self):
        doc = microdom.parse(open(self.file))
        templ = microdom.parse(open(d['template']))
        node = templ.cloneNode(1)
        tree.munge(doc, node, self.linkrel,
                   os.path.dirname(self.file),
                   self.file,
                   d['ext'], d['baseurl'], d)
        self.assertEqualsFile('good_internal.xhtml', node.toprettyxml())

    def test_getProcessor(self):
        options = { 'template': sibpath(__file__, 'template.tpl'), 'ext': '.xhtml', 'baseurl': 'burl',
                    'filenameMapping': None }
        p = process.getProcessor(default, "html", options)
        p(sibpath(__file__, 'simple3.html'), self.linkrel)
        self.assertEqualFiles('good_simple.xhtml', 'simple3.xhtml')

    def test_getProcessorWithFilenameGenerator(self):
        options = { 'template': sibpath(__file__, 'template.tpl'),
                    'ext': '.xhtml',
                    'baseurl': 'burl',
                    'filenameMapping': 'addFoo' }
        p = process.getProcessor(default, "html", options)
        p(sibpath(__file__, 'simple4.html'), self.linkrel)
        self.assertEqualFiles('good_simple.xhtml', 'simple4foo.xhtml')

    def test_outputdirGenerator(self):
        inputdir  = os.path.normpath(os.path.join("/", 'home', 'joe'))
        outputdir = os.path.normpath(os.path.join("/", 'away', 'joseph'))
        actual = process.outputdirGenerator(os.path.join("/", 'home', 'joe', "myfile.html"), '.xhtml',
                                            inputdir, outputdir)
        self.assertEquals(os.path.join("/", 'away', 'joseph', 'myfile.xhtml'), actual)
        
    def test_outputdirGeneratorBadInput(self):
        options = {'outputdir': '/away/joseph/', 'inputdir': '/home/joe/' }
        self.assertRaises(ValueError, process.outputdirGenerator, '.html', '.xhtml', **options)
    
    def test_makeSureDirectoryExists(self):
        dirname = os.path.join("tmp", 'nonexistentdir')
        if os.path.exists(dirname):
            os.rmdir(dirname)
        self.failIf(os.path.exists(dirname), "Hey: someone already created the dir")
        filename = os.path.join(dirname, 'newfile')
        tree.makeSureDirectoryExists(filename)
        self.failUnless(os.path.exists(dirname), 'should have created dir')
        os.rmdir(dirname)

    def test_indexAnchorsAdded(self):
        # generate the output file
        templ = microdom.parse(open(d['template']))

        tree.doFile(sibpath(__file__, 'lore_index_test.xhtml'), self.linkrel, '.html', d['baseurl'], templ, d)
        self.assertEqualFiles("lore_index_test_out.html", "lore_index_test.html")

########################################

    def assertEqualFiles(self, exp, act):
        if (exp == act): return True
        fact = open(sibpath(__file__, act))
        self.assertEqualsFile(exp, fact.read())

    def assertEqualsFile(self, exp, act):
        expected = open(sibpath(__file__, exp)).read()
        self.assertEqualsString(expected, act)

    def assertEqualsString(self, expected, act):
        self.assertEquals(len(expected), len(act))
        for i in range(len(expected)):
            e = expected[i]
            a = act[i]
            self.assertEquals(e, a, "differ at %d: %s vs. %s" % (i, e, a))
        self.assertEquals(expected, act)

