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

import re, os, cStringIO, time, cgi, string, urlparse
from twisted import copyright
from twisted.python import htmlizer, text
from twisted.web import microdom, domhelpers
import process, latex

# relative links to html files
def fixLinks(document, ext):
    supported_schemes=['http', 'https', 'ftp', 'mailto']
    for node in domhelpers.findElementsWithAttribute(document, 'href'):
        href = node.getAttribute("href")
        
        if urlparse.urlparse(href)[0] in supported_schemes:
            continue
        if node.getAttribute("class", "") == "absolute":
            continue

        # This is a relative link, so it should be munged.
        if href.endswith('.html') or href[:href.rfind('#')].endswith('.html'):
            fname, fext = os.path.splitext(href)
            fext = fext.replace('.html', ext) 
            node.setAttribute("href", fname + fext)


def addMtime(document, fullpath):
    for node in domhelpers.findElementsWithAttribute(document, "class","mtime"):
        node.appendChild(microdom.Text(time.ctime(os.path.getmtime(fullpath))))

def _getAPI(node):
    base = ""
    if node.hasAttribute("base"):
        base = node.getAttribute("base") + "."
    return base+node.childNodes[0].nodeValue

def fixAPI(document, url):
    # API references
    for node in domhelpers.findElementsWithAttribute(document, "class", "API"):
        fullname = _getAPI(node)
        node2 = microdom.Element('a', {'href': url%fullname, 'title': fullname})
        node2.childNodes = node.childNodes
        node.childNodes = [node2]
        node.removeAttribute('base')

def fontifyPython(document):
    def matcher(n):
        return (n.nodeName == 'pre' and n.hasAttribute('class') and
                n.getAttribute('class') == 'python')
    for node in domhelpers.findElements(document, matcher):
        fontifyPythonNode(node)

def fontifyPythonNode(node):
    oldio = cStringIO.StringIO()
    latex.getLatexText(node, oldio.write,
                       entities={'lt': '<', 'gt': '>', 'amp': '&'})
    oldio = cStringIO.StringIO(oldio.getvalue().strip()+'\n')
    newio = cStringIO.StringIO()
    htmlizer.filter(oldio, newio)
    newio.seek(0)
    newel = microdom.parse(newio).documentElement
    newel.setAttribute("class", "python")
    node.parentNode.replaceChild(newel, node)


def addPyListings(document, d):
    for node in domhelpers.findElementsWithAttribute(document, "class",
                                                     "py-listing"):
        fn = node.getAttribute("href")
        outfile = cStringIO.StringIO()
        lines = map(string.rstrip, open(os.path.join(d, fn)).readlines())
        data = '\n'.join(lines[int(node.getAttribute('skipLines', 0)):])
        data = cStringIO.StringIO(text.removeLeadingTrailingBlanks(data))
        htmlizer.filter(data, outfile)
        val = outfile.getvalue()
        _replaceWithListing(node, val, fn)


def _replaceWithListing(node, val, fn):
    caption = domhelpers.getNodeText(node)
    if caption == os.path.basename(fn):
        caption = 'Source listing'
    text = ('<div class="py-listing">%s<div class="py-caption">%s - '
            '<a href="%s"><span class="py-filename">%s</span></a></div></div>' %
            (val, caption, fn, fn))
    newnode = microdom.parseString(text).documentElement
    node.parentNode.replaceChild(newnode, node)


def addHTMLListings(document, d):
    for node in domhelpers.findElementsWithAttribute(document, "class",
                                                     "html-listing"):
        fn = node.getAttribute("href")
        val = ('<pre class="htmlsource">\n%s</pre>' %
               cgi.escape(open(os.path.join(d, fn)).read()))
        _replaceWithListing(node, val, fn)

def getHeaders(document):
    return domhelpers.findElements(document, 
                           lambda n,m=re.compile('h[23]$').match:m(n.nodeName))

def generateToC(document):
    toc, level, id = '\n<ol>\n', 0, 0
    for element in getHeaders(document):
        elementLevel = int(element.tagName[1])-2
        toc += (level-elementLevel)*'</ul>\n'
        toc += (elementLevel-level)*'<ul>'
        toc += '<li><a href="#auto%d">' % id
        toc += domhelpers.getNodeText(element)
        toc += '</a></li>\n'
        level = elementLevel
        name = microdom.parseString('<a name="auto%d" />' % id).documentElement
        element.childNodes.append(name)
        id += 1
    toc += '</ul>\n' * level
    toc += '</ol>\n'
    return microdom.parseString(toc).documentElement


def putInToC(document, toc):
    tocOrig = domhelpers.findElementsWithAttribute(document, 'class', 'toc')
    if tocOrig:
        tocOrig= tocOrig[0]
        tocOrig.childNodes = [toc]

def removeH1(document):
    h1 = domhelpers.findNodesNamed(document, 'h1')
    empty = microdom.Element('span')
    for node in h1:
        node.parentNode.replaceChild(empty, node)

def footnotes(document):
    footnotes = domhelpers.findElementsWithAttribute(document, "class",
                                                     "footnote")
    if not footnotes:
        return
    footnoteElement = microdom.Element('ol')
    id = 1
    for footnote in footnotes:
        href = microdom.parseString('<a href="#footnote-%(id)d">'
                                    '<super>%(id)d</super></a>'
                                    % vars()).documentElement
        text = ' '.join(domhelpers.getNodeText(footnote).split())
        href.setAttribute('title', text)
        target = microdom.Element('a', attributes={'name': 'footnote-%d' % id})
        target.childNodes = [footnote]
        footnoteContent = microdom.Element('li')
        footnoteContent.childNodes = [target]
        footnoteElement.childNodes.append(footnoteContent)
        footnote.parentNode.replaceChild(href, footnote)
        id += 1
    body = domhelpers.findNodesNamed(document, "body")[0]
    header = microdom.parseString('<h2>Footnotes</h2>').documentElement
    body.childNodes.append(header)
    body.childNodes.append(footnoteElement)

def notes(document):
    notes = domhelpers.findElementsWithAttribute(document, "class", "note")
    notePrefix = microdom.parseString('<strong>Note: </strong>').documentElement
    for note in notes:
        note.childNodes.insert(0, notePrefix)

def fixRelativeLinks(document, linkrel):
    for attr in 'src', 'href':
        for node in domhelpers.findElementsWithAttribute(document, attr):
            href = node.getAttribute(attr)
            if not href.startswith('http'):
                node.setAttribute(attr, linkrel+node.getAttribute(attr))

def setTitle(template, title):
    for nodeList in (domhelpers.findNodesNamed(template, "title"),
                     domhelpers.findElementsWithAttribute(template, "class",
                                                          'title')):
        if nodeList:
            nodeList[0].childNodes.extend(title)

def setAuthors(template, authors):
    # First, similarly to setTitle, insert text into an <div class="authors">
    text = ''
    for name, href in authors:
        # FIXME: Do proper quoting/escaping (is it ok to use
        # xml.sax.saxutils.{escape,quoteattr}?)
        anchor = '<a href="%s">%s</a>' % (href, name)
        if (name, href) == authors[-1]:
            if len(authors) == 1:
                text = anchor
            else:
                text += 'and ' + anchor
        else:
            text += anchor + ','

    childNodes = microdom.parseString('<span>' + text +'</span>').childNodes

    for node in domhelpers.findElementsWithAttribute(template, 
                                                     "class", 'authors'):
        node.childNodes.extend(childNodes) 

    # Second, add appropriate <link rel="author" ...> tags to the <head>.
    head = domhelpers.findNodesNamed(template, 'head')[0]
    authors = [microdom.parseString('<link rel="author" href="%s" title="%s"/>'
                                    % (href, name)).childNodes[0]
               for name, href in authors]
    head.childNodes.extend(authors)

def munge(document, template, linkrel, d, fullpath, ext, url, config):
    fixRelativeLinks(template, linkrel)
    addMtime(template, fullpath)
    removeH1(document)
    fixAPI(document, url)
    fontifyPython(document)
    addPyListings(document, d)
    addHTMLListings(document, d)
    fixLinks(document, ext)
    putInToC(template, generateToC(document))
    footnotes(document)
    notes(document)

    # Insert the document into the template
    title = domhelpers.findNodesNamed(document, 'title')[0].childNodes
    setTitle(template, title)

    authors = domhelpers.findNodesNamed(document, 'link')
    authors = [(n.getAttribute('title',''), n.getAttribute('href', ''))
               for n in authors if n.getAttribute('rel', '') == 'author']
    setAuthors(template, authors)

    body = domhelpers.findNodesNamed(document, "body")[0]
    tmplbody = domhelpers.findElementsWithAttribute(template, "class",
                                                              "body")[0]
    tmplbody.childNodes = body.childNodes
    tmplbody.setAttribute("class", "content")


def parseFileAndReport(fn):
    try:
        return microdom.parse(open(fn))
    except microdom.MismatchedTags, e:
        raise process.ProcessingFailure(
              "%s:%s: begin mismatched tags <%s>/</%s>" %
               (e.begLine, e.begCol, e.got, e.expect),
              "%s:%s: end mismatched tags <%s>/</%s>" %
               (e.endLine, e.endCol, e.got, e.expect))
    except microdom.ParseError, e:
        raise process.ProcessingFailure("%s:%s:%s" % (e.line, e.col, e.message))
    except IOError, e:
        raise process.ProcessingFailure(e.strerror)

def doFile(fn, linkrel, ext, url, templ, d=None):
    d = d or {}
    doc = parseFileAndReport(fn)
    cn = templ.cloneNode(1)
    munge(doc, cn, linkrel, os.path.dirname(fn), fn, ext, url, d)
    cn.writexml(open(os.path.splitext(fn)[0]+ext, 'wb'))
