#! /usr/bin/env python

# Copyright (c) 2001-2004 Twisted Matrix Laboratories.
# See LICENSE for details.


"""
Package installer for Twisted

Copyright (C) 2001 Matthew W. Lefkowitz
All rights reserved, see LICENSE for details.

$Id: setup.py,v 1.153 2004/02/28 21:36:57 davep Exp $
"""

import distutils, os, sys, string
from glob import glob

from distutils.core import setup, Extension
from distutils.command.build_scripts import build_scripts
from distutils.command.install_data import install_data
from distutils.ccompiler import new_compiler
from distutils.errors import CompileError
from distutils.command.build_ext import build_ext
from distutils import sysconfig

if sys.version_info<(2,2):
    print >>sys.stderr, "You must use at least Python 2.2 for Twisted"
    sys.exit(3)

from twisted import copyright

#############################################################################
### Helpers and distutil tweaks
#############################################################################

class build_scripts_twisted(build_scripts):
    """Renames scripts so they end with '.py' on Windows."""

    def run(self):
        build_scripts.run(self)
        if os.name == "nt":
            for f in os.listdir(self.build_dir):
                fpath=os.path.join(self.build_dir, f)
                if not fpath.endswith(".py"):
                    try:
                        os.unlink(fpath + ".py")
                    except EnvironmentError, e:
                        if e.args[1]=='No such file or directory':
                            pass
                    os.rename(fpath, fpath + ".py")


# make sure data files are installed in twisted package
# this is evil.
class install_data_twisted(install_data):
    def finalize_options (self):
        self.set_undefined_options('install',
            ('install_lib', 'install_dir')
        )
        install_data.finalize_options(self)


# Custom build_ext command simlar to the one in Python2.1/setup.py.  This
# allows us to detect (only at build time) what extentions we want to build.

class build_ext_twisted(build_ext):
    def build_extensions(self):
        """
        Override the build_ext build_extensions method to call our
        module detection function before it trys to build the extensions.
        """
        self._detect_modules()
        build_ext.build_extensions(self)

    def _remove_conftest(self):
        for filename in ("conftest.c", "conftest.o", "conftest.obj"):
            try:
                os.unlink(filename)
            except EnvironmentError:
                pass

    def _compile_helper(self, content):
        conftest = open("conftest.c", "w")
        try:
            conftest.write(content)
            conftest.close()

            try:
                self.compiler.compile(["conftest.c"], output_dir='')
            except CompileError:
                return False
            return True
        finally:
            self._remove_conftest()

    def _check_define(self, include_files, define_name):
        """
        Check if the given name has been #define'd by trying to compile a
        file that #includes the given files and uses #ifndef to test for the
        name.
        """
        self.compiler.announce("checking for %s..." % define_name, 0)
        return self._compile_helper("""\
%s
#ifndef %s
#error %s is not defined
#endif
""" % ('\n'.join(['#include <%s>' % n for n in include_files]),
       define_name, define_name))

    def _check_header(self, header_name):
        """
        Check if the given header can be included by trying to compile a file
        that contains only an #include line.
        """
        self.compiler.announce("checking for %s ..." % header_name, 0)
        return self._compile_helper("#include <%s>\n" % header_name)

    def _check_struct_member(self, include_files, struct, member):
        """
        Check that given member is present in the given struct when the
        specified headers are included.
        """
        self.compiler.announce(
            "checking for %s in struct %s..." % (member, struct), 0)
        return self._compile_helper("""\
%s
int main(int argc, char **argv)
{ struct %s foo;  (void)foo.%s;  return(0); }
""" % ('\n'.join(['#include <%s>' % n for n in include_files]), struct, member))
    
    def _detect_modules(self):
        """
        Determine which extension modules we should build on this system.
        """

        # always define WIN32 under Windows
        if os.name == 'nt':
            define_macros = [("WIN32", 1)]
        else:
            define_macros = []

        print "Checking if C extensions can be compiled, don't be alarmed if a few compile errors are printed."
        
        if not self._compile_helper("#define X 1\n"):
            print "Compiler not found, skipping C extensions."
            self.extensions = []
            return
        
        # Extension modules to build.
        exts = [
            Extension("twisted.spread.cBanana",
                      ["twisted/spread/cBanana.c"],
                      define_macros=define_macros),
            ]

        # The portmap module (for inetd)
        if self._check_header("rpc/rpc.h"):
            exts.append( Extension("twisted.runner.portmap",
                                    ["twisted/runner/portmap.c"],
                                    define_macros=define_macros) )
        else:
            self.announce("Sun-RPC portmap support is unavailable on this system (but that's OK, you probably don't need it anyway).")

        # urllib.unquote accelerator
        exts.append( Extension("twisted.protocols._c_urlarg",
                                ["twisted/protocols/_c_urlarg.c"],
                                define_macros=define_macros) )

        if sys.platform == 'darwin':
            exts.append( Extension("twisted.internet.cfsupport",
                                    ["twisted/internet/cfsupport/cfsupport.c"],
                                    extra_compile_args=['-w'],
                                    extra_link_args=['-framework','CoreFoundation','-framework','CoreServices','-framework','Carbon'],
                                    define_macros=define_macros))

        if sys.platform == 'win32':
            exts.append( Extension("twisted.internet.iocpreactor._iocp",
                                    ["twisted/internet/iocpreactor/_iocp.c"],
                                    libraries=["ws2_32", "mswsock"],
                                    define_macros=define_macros))
        
        self.extensions.extend(exts)

#############################################################################
### Call setup()
#############################################################################

ver = string.replace(copyright.version, '-', '_') #RPM doesn't like '-'
setup_args = {
    'name': "Twisted",
    'version': ver,
    'description': "Twisted %s is a framework to build frameworks" % ver,
    'author': "Twisted Matrix Laboratories",
    'author_email': "twisted-python@twistedmatrix.com",
    'maintainer': "Glyph Lefkowitz",
    'maintainer_email': "glyph@twistedmatrix.com",
    'url': "http://twistedmatrix.com/",
    'license': "GNU LGPL",
    'long_description': """\
Twisted is a framework to build frameworks. It is expected that one
day the project will expanded to the point that the framework will
seamlessly integrate with mail, web, DNS, netnews, IRC, RDBMSs,
desktop environments, and your toaster.
""",
    'packages': [
        "twisted",
        "twisted.application",
        "twisted.conch",
        "twisted.conch.client",
        "twisted.conch.openssh_compat",
        "twisted.conch.ssh",
        "twisted.conch.ui",
        "twisted.conch.insults",
        "twisted.conch.test",
        "twisted.conch.scripts",
        "twisted.cred",
        "twisted.enterprise",
        "twisted.flow",
        "twisted.flow.test",
        "twisted.internet",
        "twisted.internet.iocpreactor",
        "twisted.internet.serialport",
        "twisted.lore",
        "twisted.lore.scripts",
        "twisted.lore.test",
        "twisted.mail",
        "twisted.mail.test",
        "twisted.mail.scripts",
        "twisted.manhole",
        "twisted.manhole.ui",
        "twisted.names",
        "twisted.names.test",
        "twisted.news",
        "twisted.news.test",
        "twisted.pair",
        "twisted.pair.test",
        "twisted.persisted",
        "twisted.persisted.journal",
        "twisted.protocols",
        "twisted.protocols.gps",
        "twisted.protocols.mice",
        "twisted.python",
        "twisted.runner",
        "twisted.scripts",
        "twisted.spread",
        "twisted.spread.ui",
        "twisted.tap",
        "twisted.test",
        "twisted.trial",
        "twisted.web",
        "twisted.web.test",
        "twisted.web.scripts",
        "twisted.web.woven",
        "twisted.words",
        "twisted.words.protocols",
        "twisted.words.protocols.jabber",
        "twisted.words.test",
        "twisted.words.scripts",
        "twisted.words.im",
        "twisted.xish",
    ],
    'scripts' : [
        'bin/manhole', 'bin/mktap', 'bin/twistd',
        'bin/im', 'bin/t-im', 'bin/tap2deb', 'bin/tap2rpm',
        'bin/tapconvert', 'bin/websetroot',
        'bin/lore/lore',
        'bin/tkmktap', 'bin/conch/conch', 'bin/conch/ckeygen',
        'bin/conch/tkconch', 'bin/trial', 'bin/mail/mailmail'
    ],
    'cmdclass': {
        'build_scripts': build_scripts_twisted,
        'install_data': install_data_twisted,
        'build_ext' : build_ext_twisted,
    },
}

# Apple distributes a nasty version of Python 2.2 w/ all release builds of
# OS X 10.2 and OS X Server 10.2
BROKEN_CONFIG = '2.2 (#1, 07/14/02, 23:25:09) \n[GCC Apple cpp-precomp 6.14]'
if sys.platform == 'darwin' and sys.version == BROKEN_CONFIG:
    # change this to 1 if you have some need to compile
    # with -flat_namespace as opposed to -bundle_loader
    FLAT_NAMESPACE = 0
    BROKEN_ARCH = '-arch i386'
    BROKEN_NAMESPACE = '-flat_namespace -undefined_suppress'
    import distutils.sysconfig
    distutils.sysconfig.get_config_vars()
    x = distutils.sysconfig._config_vars['LDSHARED']
    y = x.replace(BROKEN_ARCH, '')
    if not FLAT_NAMESPACE:
        e = os.path.realpath(sys.executable)
        y = y.replace(BROKEN_NAMESPACE, '-bundle_loader ' + e)
    if y != x:
        print "Fixing some of Apple's compiler flag mistakes..."
        distutils.sysconfig._config_vars['LDSHARED'] = y

if os.name=='nt':
    setup_args['scripts'].append('win32/twisted_postinstall.py')

if hasattr(distutils.dist.DistributionMetadata, 'get_keywords'):
    setup_args['keywords'] = "internet www tcp framework games"

if hasattr(distutils.dist.DistributionMetadata, 'get_platforms'):
    setup_args['platforms'] = "win32 posix"

imPath = os.path.join('twisted', 'im')
pbuiPath = os.path.join('twisted','spread','ui')
baremanPath = os.path.join('twisted','manhole')
manuiPath = os.path.join(baremanPath, 'ui')
lorePath = os.path.join("twisted", 'lore')

mailTestPath = os.path.join('twisted', 'mail', 'test')
mailTestFiles = ['rfc822.message', 'process.alias.sh']

loreTestPath = os.path.join('twisted', 'lore', 'test')
loreTestFiles = ['template.tpl']

testPath = os.path.join('twisted', 'test')
testFiles = ['server.pem']

wovenPath = os.path.join('twisted', 'web', 'woven')
wovenFiles = ['FlashConduitGlue.html', 'WebConduitGlue.html',
              'FlashConduit.fla', 'WebConduit2_mozilla.js',
              'FlashConduit.swf', 'WebConduit2_msie.js']
internetPath = os.path.join("twisted", "internet")

setup_args['data_files']=[
    (imPath, [os.path.join(imPath, 'instancemessenger.glade')]),
    (pbuiPath, [os.path.join(pbuiPath, 'login2.glade')]),
    (manuiPath, [os.path.join(manuiPath, 'gtk2manhole.glade')]),
    (lorePath, [os.path.join(lorePath, "template.mgp")]),
    ('twisted', [os.path.join('twisted', 'plugins.tml')]),
    (baremanPath, [os.path.join(baremanPath, 'gladereactor.glade')]),
    (baremanPath, [os.path.join(baremanPath, 'inspectro.glade')]),
    (baremanPath, [os.path.join(baremanPath, 'logview.glade')]),
    ]

for pathname, filenames in [(wovenPath, wovenFiles),
                            (loreTestPath, loreTestFiles),
                            (testPath, testFiles),
                            (mailTestPath, mailTestFiles)]:
    setup_args['data_files'].extend(
        [(pathname, [os.path.join(pathname, filename)])
            for filename in filenames])

# always define WIN32 under Windows
if os.name == 'nt':
    define_macros = [("WIN32", 1)]
else:
    define_macros = []

# Include all extension modules here, whether they are built or not.
# The custom built_ext command will wipe out this list anyway, but it
# is required for sdist to work.

#X-platform:
if not (sys.argv.count("bdist_wininst") and os.name != 'nt'):
    setup_args['ext_modules'] = [
        Extension("twisted.spread.cBanana",
                  ["twisted/spread/cBanana.c"],
                  define_macros=define_macros),
    ]
else:
    setup_args['ext_modules'] = []

if __name__ == '__main__':
    setup(**setup_args)

