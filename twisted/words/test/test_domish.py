# Copyright (c) 2001-2005 Twisted Matrix Laboratories.
# See LICENSE for details.


from twisted.trial import unittest
from twisted.words.xish import domish

class DomishTestCase(unittest.TestCase):
    def testEscaping(self):
        s = "&<>'\""
        self.assertEquals(domish.escapeToXml(s), "&amp;&lt;&gt;'\"")
        self.assertEquals(domish.escapeToXml(s, 1), "&amp;&lt;&gt;&apos;&quot;")

    def testNamespaceObject(self):
        ns = domish.Namespace("testns")
        self.assertEquals(ns.foo, ("testns", "foo"))

    def testElementInit(self):
        e = domish.Element((None, "foo"))
        self.assertEquals(e.name, "foo")
        self.assertEquals(e.uri, None)
        self.assertEquals(e.defaultUri, None)
        self.assertEquals(e.parent, None)

        e = domish.Element(("", "foo"))
        self.assertEquals(e.name, "foo")
        self.assertEquals(e.uri, "")
        self.assertEquals(e.defaultUri, "")
        self.assertEquals(e.parent, None)

        e = domish.Element(("testns", "foo"))
        self.assertEquals(e.name, "foo")
        self.assertEquals(e.uri, "testns")
        self.assertEquals(e.defaultUri, "testns")
        self.assertEquals(e.parent, None)

        e = domish.Element(("testns", "foo"), "test2ns")
        self.assertEquals(e.name, "foo")
        self.assertEquals(e.uri, "testns")
        self.assertEquals(e.defaultUri, "test2ns")

    def testChildOps(self):
        e = domish.Element(("testns", "foo"))
        e.addContent("somecontent")
        b2 = e.addElement(("testns2", "bar2"))
        e["attrib1"] = "value1"
        e[("testns2", "attrib2")] = "value2"
        e.addElement("bar")
        e.addElement("bar")
        e.addContent("abc")
        e.addContent("123")

        # Check content merging
        self.assertEquals(e.children[-1], "abc123")

        # Check str()/content extraction
        self.assertEquals(str(e), "somecontent")

        # Check direct child accessor
        self.assertEquals(e.bar2, b2)
        e.bar2.addContent("subcontent")
        e.bar2["bar2value"] = "somevalue"

        # Check child ops
        self.assertEquals(e.children[1], e.bar2)
        self.assertEquals(e.children[2], e.bar)
        
        # Check attribute ops
        self.assertEquals(e["attrib1"], "value1")
        del e["attrib1"]
        self.assertEquals(e.hasAttribute("attrib1"), 0)
        self.assertEquals(e.hasAttribute("attrib2"), 0)
        self.assertEquals(e[("testns2", "attrib2")], "value2")

class DomishStreamTests:
    def setUp(self):
        self.doc_started = False
        self.doc_ended = False
        self.root = None
        self.elements = []
        self.stream = self.streamClass()
        self.stream.DocumentStartEvent = self._docStarted
        self.stream.ElementEvent = self.elements.append
        self.stream.DocumentEndEvent = self._docEnded

    def _docStarted(self, root):
        self.root = root
        self.doc_started = True

    def _docEnded(self):
        self.doc_ended = True

    def doTest(self, xml):
        self.stream.parse(xml)

    def testHarness(self):
        xml = "<root><child/><child2/></root>"
        self.stream.parse(xml)
        self.assertEquals(self.doc_started, True)
        self.assertEquals(self.root.name, 'root')
        self.assertEquals(self.elements[0].name, 'child')
        self.assertEquals(self.elements[1].name, 'child2')
        self.assertEquals(self.doc_ended, True)

    def testBasic(self):
        xml = "<stream:stream xmlns:stream='etherx' xmlns='jabber'>\n" + \
              "  <message to='bar'>" + \
              "    <x xmlns='xdelay'>some&amp;data&gt;</x>" + \
              "  </message>" + \
              "</stream:stream>"

        self.stream.parse(xml)
        self.assertEquals(self.root.name, 'stream')
        self.assertEquals(self.root.uri, 'etherx')
        self.assertEquals(self.elements[0].name, 'message')
        self.assertEquals(self.elements[0].uri, 'jabber')
        self.assertEquals(self.elements[0]['to'], 'bar')
        self.assertEquals(self.elements[0].x.uri, 'xdelay')
        self.assertEquals(unicode(self.elements[0].x), 'some&data>')

    def testNoRootNS(self):
        xml = "<stream><error xmlns='etherx'/></stream>"

        self.stream.parse(xml)
        self.assertEquals(self.root.uri, '')
        self.assertEquals(self.elements[0].uri, 'etherx')
        
    def testNoDefaultNS(self):
        xml = "<stream:stream xmlns:stream='etherx'><error/></stream:stream>"""

        self.stream.parse(xml)
        self.assertEquals(self.root.uri, 'etherx')
        self.assertEquals(self.root.defaultUri, '')
        self.assertEquals(self.elements[0].uri, '')
        self.assertEquals(self.elements[0].defaultUri, '')

    def testChildDefaultNS(self):
        xml = "<root xmlns='testns'><child/></root>"

        self.stream.parse(xml)
        self.assertEquals(self.root.uri, 'testns')
        self.assertEquals(self.elements[0].uri, 'testns')

    def testEmptyChildNS(self):
        xml = "<root xmlns='testns'><child1><child2 xmlns=''/></child1></root>"

        self.stream.parse(xml)
        self.assertEquals(self.elements[0].child2.uri, '')

    def testChildPrefix(self):
        xml = "<root xmlns='testns' xmlns:foo='testns2'><foo:child/></root>"

        self.stream.parse(xml)
        self.assertEquals(self.root.localPrefixes['foo'], 'testns2')
        self.assertEquals(self.elements[0].uri, 'testns2')

    def testUnclosedElement(self):
        self.assertRaises(domish.ParserError, self.stream.parse, 
                                              "<root><error></root>")

class DomishExpatStreamTestCase(unittest.TestCase, DomishStreamTests):
    def setUp(self):
        DomishStreamTests.setUp(self)

    def setUpClass(self):
        try: 
            import pyexpat
        except ImportError:
            raise unittest.SkipTest, "Skipping ExpatElementStream test, since no expat wrapper is available."

        self.streamClass = domish.ExpatElementStream

class DomishSuxStreamTestCase(unittest.TestCase, DomishStreamTests):
    def setUp(self):
        DomishStreamTests.setUp(self)

    def setUpClass(self):
        if domish.SuxElementStream is None:
            raise unittest.SkipTest, "Skipping SuxElementStream test, since twisted.web is not available."

        self.streamClass = domish.SuxElementStream

class SerializerTests:
    def testNoNamespace(self):
        e = domish.Element((None, "foo"))
        self.assertEquals(e.toXml(), "<foo/>")
        self.assertEquals(e.toXml(closeElement = 0), "<foo>")

    def testDefaultNamespace(self):
        e = domish.Element(("testns", "foo"))
        self.assertEquals(e.toXml(), "<foo xmlns='testns'/>")

    def testOtherNamespace(self):
        e = domish.Element(("testns", "foo"), "testns2")
        self.assertEquals(e.toXml({'testns': 'bar'}),
                          "<bar:foo xmlns:bar='testns' xmlns='testns2'/>")

    def testChildDefaultNamespace(self):
        e = domish.Element(("testns", "foo"))
        e.addElement("bar")
        self.assertEquals(e.toXml(), "<foo xmlns='testns'><bar/></foo>")

    def testChildSameNamespace(self):
        e = domish.Element(("testns", "foo"))
        e.addElement(("testns", "bar"))
        self.assertEquals(e.toXml(), "<foo xmlns='testns'><bar/></foo>")

    def testChildSameDefaultNamespace(self):
        e = domish.Element(("testns", "foo"))
        e.addElement("bar", "testns")
        self.assertEquals(e.toXml(), "<foo xmlns='testns'><bar/></foo>")

    def testChildOtherDefaultNamespace(self):
        e = domish.Element(("testns", "foo"))
        e.addElement(("testns2", "bar"), 'testns2')
        self.assertEquals(e.toXml(), "<foo xmlns='testns'><bar xmlns='testns2'/></foo>")

    def testOnlyChildDefaultNamespace(self):
        e = domish.Element((None, "foo"))
        e.addElement(("ns2", "bar"), 'ns2')
        self.assertEquals(e.toXml(), "<foo><bar xmlns='ns2'/></foo>")
    
    def testOnlyChildDefaultNamespace2(self):
        e = domish.Element((None, "foo"))
        e.addElement("bar")
        self.assertEquals(e.toXml(), "<foo><bar/></foo>")

    def testChildInDefaultNamespace(self):
        e = domish.Element(("testns", "foo"), "testns2")
        e.addElement(("testns2", "bar"))
        self.assertEquals(e.toXml(), "<xn0:foo xmlns:xn0='testns' xmlns='testns2'><bar/></xn0:foo>")

    def testQualifiedAttribute(self):
        e = domish.Element((None, "foo"),
                           attribs = {("testns2", "bar"): "baz"})
        self.assertEquals(e.toXml(), "<foo xmlns:xn0='testns2' xn0:bar='baz'/>")

    def testQualifiedAttributeDefaultNS(self):
        e = domish.Element(("testns", "foo"),
                           attribs = {("testns", "bar"): "baz"})
        self.assertEquals(e.toXml(), "<foo xmlns='testns' xmlns:xn0='testns' xn0:bar='baz'/>")

    def testTwoChilds(self):
        e = domish.Element(('', "foo"))
        child1 = e.addElement(("testns", "bar"), "testns2")
        child1.addElement(('testns2', 'quux'))
        child2 = e.addElement(("testns3", "baz"), "testns4")
        child2.addElement(('testns', 'quux'))
        self.assertEquals(e.toXml(), "<foo><xn0:bar xmlns:xn0='testns' xmlns='testns2'><quux/></xn0:bar><xn1:baz xmlns:xn1='testns3' xmlns='testns4'><xn0:quux xmlns:xn0='testns'/></xn1:baz></foo>")

    def testXMLNamespace(self):
        e = domish.Element((None, "foo"),
                           attribs = {("http://www.w3.org/XML/1998/namespace",
                                       "lang"): "en_US"})
        self.assertEquals(e.toXml(), "<foo xml:lang='en_US'/>")

    def testQualifiedAttributeGivenListOfPrefixes(self):
        e = domish.Element((None, "foo"),
                           attribs = {("testns2", "bar"): "baz"})
        self.assertEquals(e.toXml({"testns2": "qux"}),
                          "<foo xmlns:qux='testns2' qux:bar='baz'/>")

    def testNSPrefix(self):
        e = domish.Element((None, "foo"),
                           attribs = {("testns2", "bar"): "baz"})
        c = e.addElement(("testns2", "qux"))
        c[("testns2", "bar")] = "quux"

        self.assertEquals(e.toXml(), "<foo xmlns:xn0='testns2' xn0:bar='baz'><xn0:qux xn0:bar='quux'/></foo>")

    def testDefaultNSPrefix(self):
        e = domish.Element((None, "foo"),
                           attribs = {("testns2", "bar"): "baz"})
        c = e.addElement(("testns2", "qux"))
        c[("testns2", "bar")] = "quux"
        c.addElement('foo')

        self.assertEquals(e.toXml(), "<foo xmlns:xn0='testns2' xn0:bar='baz'><xn0:qux xn0:bar='quux'><xn0:foo/></xn0:qux></foo>")

    def testPrefixScope(self):
        e = domish.Element(('testns', 'foo'))

        self.assertEquals(e.toXml(prefixes={'testns': 'bar'},
                                  prefixesInScope=['bar']),
                          "<bar:foo/>")

    def testLocalPrefixes(self):
        e = domish.Element(('testns', 'foo'), localPrefixes={'bar': 'testns'})
        self.assertEquals(e.toXml(), "<bar:foo xmlns:bar='testns'/>")

    def testLocalPrefixesWithChild(self):
        e = domish.Element(('testns', 'foo'), localPrefixes={'bar': 'testns'})
        e.addElement('baz')
        self.assertIdentical(e.baz.defaultUri, None)
        self.assertEquals(e.toXml(), "<bar:foo xmlns:bar='testns'><baz/></bar:foo>")

    def testRawXMLSerialization(self):
        e = domish.Element((None, "foo"))
        e.addRawXml("<abc123>")
        # The testcase below should NOT generate valid XML -- that's
        # the whole point of using the raw XML call -- it's the callers
        # responsiblity to ensure that the data inserted is valid
        self.assertEquals(e.toXml(), "<foo><abc123></foo>")

    def testRawXMLWithUnicodeSerialization(self):
        e = domish.Element((None, "foo"))
        e.addRawXml(u"<degree>\u00B0</degree>")
        self.assertEquals(e.toXml(), u"<foo><degree>\u00B0</degree></foo>")

    def testUnicodeSerialization(self):
        e = domish.Element((None, "foo"))
        e["test"] = u"my value\u0221e"
        e.addContent(u"A degree symbol...\u00B0")
        self.assertEquals(e.toXml(),
                          u"<foo test='my value\u0221e'>A degree symbol...\u00B0</foo>")

class DomishTestListSerializer(unittest.TestCase, SerializerTests):
    def setUpClass(self):
        self.__serializerClass = domish.SerializerClass
        domish.SerializerClass = domish._ListSerializer

    def tearDownClass(self):
        domish.SerializerClass = self.__serializerClass

