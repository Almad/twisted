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

"""A web frontend to coil."""

# System Imports
import types
import sys
import string

# Twisted Imports
from twisted.web import widgets
from twisted.python import roots, components, reflect
from twisted.python.plugin import getPlugIns
from twisted.web import widgets, html
from twisted.protocols import http
from twisted.internet import protocol

# Sibling Imports
import coil, app


class ConfigRoot(widgets.Gadget, widgets.Widget):
    """The root of the coil web interface."""

    def __init__(self, application):
        widgets.Gadget.__init__(self)
        self.putWidget("config", AppConfiguratorPage(application))
        self.addFile("images")

    def display(self, request):
        request.setResponseCode(http.FOUND)
        request.setHeader("location",
                          request.prePathURL() + 'config')
        return ['no content']


class PluginLoader(widgets.Form):
    """Form for loading plugins."""

    def __init__(self, appConfig):
        self.appConfig = appConfig

    def getFormFields(self, request):
        plugins = getPlugIns("coil")
        mnuList = []
        for plugin in plugins:
            if not plugin.isLoaded():
                mnuList.append([plugin.module, plugin.name])
            else:
                mnuList.append([plugin.module, plugin.name + ' (already loaded)'])
        return [['menu', 'Plugin to load?', 'pluginToLoad', mnuList]]

    def process(self, write, request, submit, pluginToLoad):
        plugins = getPlugIns('coil')
        for plugin in plugins:
            print plugin.module
            if plugin.module == pluginToLoad:
                write( 'loaded ' + plugin.module + '('+pluginToLoad+')' )
                plugin.load()
                self.appConfig.reloadDispensers()
                break
        else:
            write( 'could not load' + plugin.module )


class AppConfiguratorPage(widgets.Presentation):
    """A web configuration interface for Twisted.

    This configures the toplevel application.
    """

    template = '''
    <center>
    <table width="95%">
    <tr><td width="20%" valign="top">%%%%self.streamCall(self.displayTree, request)%%%%</td>
    <td width="80%" valign="top">%%%%self.configd%%%%</td>
    </tr>
    <tr><td colspan="2">%%%%self.pluginLoader()%%%%</td></tr>
    </table>
    </center>
    '''

    isLeaf = 1


    def __init__(self, application):
        widgets.Presentation.__init__(self)
        self.app = app.ApplicationConfig(application)
        self.reloadDispensers()

    def reloadDispensers(self):
        self.dispensers = coil.DispenserStorage(self.app)

    def pluginLoader(self):
        return PluginLoader(self)

    def displayTree(self, write, request):
        self.displayTreeElement(write,
                                str(self.app),
                                "config",
                                self.app)

    def displayTreeElement(self, write, inName, inPath, collection, indentLevel=0):
        subIndent = indentLevel + 1
        for name, entity in collection.listStaticEntities():
            collection = coil.getCollection(entity)
            configurator = coil.getConfigurator(entity)
            if collection or configurator:
                write('%s + <a href="%s/%s">%s</a> <br>' %
                      (indentLevel * '&nbsp;', inPath, name, name))
                if collection:
                    self.displayTreeElement(write, name, '%s/%s' % (inPath, name), collection, subIndent)
            else:
                write("%s. %s <br>" % (subIndent * '&nbsp;', name))

    def prePresent(self, request):
        self.configd = self.configWidget(request)

    def configWidget(self, request):
        """Render the config part of the widget."""
        path = request.postpath
        if path:
            obj = self.app
            for elem in path:
                if elem:                # '' doesn't count
                    collection = coil.getCollection(obj)
                    if collection is None:
                        obj = None
                    else:
                        obj = collection.getStaticEntity(elem)

                    if obj is None:
                        # no such subobject
                        request.redirect(request.prePathURL())
                        return ['Redirecting...']
        else:
            obj = self.app
        ret = []
        linkfrom = string.join(['config']+request.postpath, '/') + '/'
        cfg = coil.getConfigurator(obj)

        # add a form for configuration if available
        if cfg and cfg.configTypes:
            ret.extend(widgets.TitleBox("Configuration", ConfigForm(self, cfg, linkfrom)).display(request))

        # add a form for a collection of objects
        coll = coil.getCollection(obj)
        if components.implements(coll, coil.IConfigCollection):
            if coll.entityType in (types.StringType, types.IntType, types.FloatType):
                ret.extend(widgets.TitleBox("Delete Items", ImmutableCollectionDeleteForm(self, coll, linkfrom)).display(request))
                colClass = ImmutableCollectionForm
            else:
                colClass = CollectionForm
            ret.extend(widgets.TitleBox("Listing", colClass(self, coll, linkfrom)).display(request))

        ret.append(html.PRE(str(obj)))
        return ret

    def makeConfigMenu(self, interface):
        """Make a menu for adding a new object to a collection."""
        l = []
        if 1:
            for realClass in coil.getImplementors(interface):
                cfgClass = coil.getConfiguratorClass(realClass)
                nm = getattr(cfgClass, 'configName', None) or reflect.qual(realClass)
                l.append(['new '+reflect.qual(realClass), 'new '+nm])
        for t in self.dispensers.getDispensers(interface):
            obj, methodName, desc = t
            l.append(['dis %d' % hash(t), desc])
        return l

    def makeConfigurable(self, cfgInfo, container, name):
        """Create a new configurable to a container, based on input from web form."""
        cmd, args = string.split(cfgInfo, ' ', 1)
        if cmd == "new": # create
            obj = coil.createConfigurable(reflect.namedClass(args), container, name)
        elif cmd == "dis": # dispense
            methodHash = int(args)
            if components.implements(container, coil.IConfigurator) and container.getType(name):
                interface = container.getType(name)
            elif components.implements(container, coil.IConfigCollection):
                interface = container.entityType
            else:
                interface = None
            for t in self.dispensers.getDispensers(interface):
                obj, methodName, desc = t
                if hash(t) == methodHash:
                    cfg = coil.getConfigurator(obj)
                    obj = getattr(cfg, methodName)()
                    print "created %s from dispenser" % obj
                    break
        else:
            raise ValueError, "Unrecognized command %r in cfgInfo %r" % (cmd, cfgInfo)

        self.dispensers.addObject(obj)
        return obj


class ConfigForm(widgets.Form):
    """A form for configuring an object."""

    def __init__(self, configurator, cfgr, linkfrom):
        if not components.implements(cfgr, coil.IConfigurator):
            raise TypeError
        self.configurator = configurator  # this is actually a AppConfiguratorPage
        self.cfgr = cfgr
        self.linkfrom = linkfrom

    submitNames = ['Configure']

    def getFormFields(self, request):
        existing = self.cfgr.getConfiguration()
        allowed = self.cfgr.configTypes
        myFields = []
        for name, (cfgType, prompt, description) in allowed.items():
            current = existing.get(name)
            if isinstance(cfgType, types.ClassType) and issubclass(cfgType, components.Interface):
                inputType = 'menu'
                inputValue = self.configurator.makeConfigMenu(cfgType)
                if current:
                    inputValue.insert(0, ['current', "Current Object"])
            elif cfgType == types.StringType:
                inputType = 'string'
                inputValue = current or ''
            elif cfgType == types.IntType:
                inputType = 'int'
                inputValue = str(current) or '0'
            elif cfgType == 'boolean':
                inputType = 'checkbox'
                inputValue = current
            else:
                inputType = 'string'
                inputValue = "<UNKNOWN>"
            myFields.append([inputType, prompt, name, inputValue, description])
        return myFields

    def process(self, write, request, submit, **values):
        existing = self.cfgr.getConfiguration()
        allowed = self.cfgr.configTypes
        created = {}
        for name, cfgInfo in values.items():
            write(str((name, cfgInfo)) + "<br>")
            if isinstance(allowed[name][0], types.ClassType):
                if cfgInfo == 'current':
                    continue
                created[name] = self.configurator.makeConfigurable(cfgInfo, self.cfgr, name)
                print 'instantiated', created[name]
            else:
                created[name] = cfgInfo
        try:
            self.cfgr.configure(created)
            self.format(self.getFormFields(request), write, request)
        except coil.InvalidConfiguration, ic:
            raise widgets.FormInputError(ic)


class CollectionForm(widgets.Form):
    """Form for a collection of objects - adding, deleting, etc."""

    def __init__(self, configurator, coll, linkfrom):
        self.configurator = configurator # this is actually a AppConfiguratorPage
        self.coll = coll
        self.linkfrom = linkfrom

    submitNames = ['Insert', 'Delete']

    def getFormFields(self, request):
        itemlst = []
        for name, val in self.coll.listStaticEntities():
            itemlst.append([name, '%s: <a href="%s">%s</a>' %
                            (name, self.linkfrom+name,
                             html.escape(repr(val))), 0])
        result = []
        if itemlst:
            result.append(['checkgroup', 'Items in Set<br>(Select to Delete)',
                           'items', itemlst])
        result.append(['string', "%s to Insert" %
                       self.coll.getNameType(), "name", ""])
        result.append(['menu', "%s to Insert" % self.coll.getEntityType(), "type", self.configurator.makeConfigMenu(self.coll.entityType)])
        return widgets.Form.getFormFields(self, request, result)

    def process(self, write, request, submit, name="", type=None, items=()):
        # write(str(('YAY', name, type)))
        # TODO: validation on the name?
        if submit == 'Delete':
            for item in items:
                obj = self.coll.getStaticEntity(item)
                if components.implements(obj, coil.IConfigurator):
                    obj = obj.getInstance()
                self.configurator.dispensers.removeObject(obj)
                self.coll.delEntity(item)
            write("<b>Items Deleted.</b><br>(%s)<br>" % html.escape(repr(items)))
        elif submit == "Insert":
            obj = self.configurator.makeConfigurable(type, self.coll, name)
            self.coll.putEntity(name, obj)
            write("<b>%s created!</b>" % type)
        else:
            raise widgets.FormInputError("Don't know how to %s" % repr(submit))
        self.format(self.getFormFields(request), write, request)


class ImmutableCollectionForm(widgets.Form):
    """A collection of immutable objects such as strings or integers."""

    typeMap = {types.StringType : 'string',
               types.IntType : 'integer',
               types.FloatType : 'float'
              }

    def __init__(self, appcpage, coll, linkfrom):
        self.appcpage = appcpage
        self.collection = coll
        self.linkfrom = linkfrom

    def getFormFields(self, request):
        result = []
        for name, val in self.collection.listStaticEntities():
            result.append(['string', name, 'val_%s' % name, val])
        result.append(['string', "New %s to Insert" % self.collection.getNameType(), "name", ""])
        kind = self.typeMap[self.collection.entityType]
        result.append([kind, "%s to Insert" % self.collection.getEntityType(), "value", ""])
        return widgets.Form.getFormFields(self, request, result)

    def process(self, write, request, submit, name, value, **newitems):
        if name:
            self.collection.putEntity(name, value)
            write("<b>%s created!</b>" % name)
        for key, value in newitems.items():
            if len(key) <= 4 or key[:4] != "val_": continue
            key = key[4:]
            self.collection.putEntity(key, value)
            write("<b>%s changed!</b>" % key)
        self.format(self.getFormFields(request), write, request)


class ImmutableCollectionDeleteForm(widgets.Form):
    """A collection of immutable objects such as strings or integers.

    This form allows you to delete entries.
    """

    submitNames = ["Delete"]

    def __init__(self, appcpage, coll, linkfrom):
        self.appcpage = appcpage
        self.collection = coll
        self.linkfrom = linkfrom

    def getFormFields(self, request):
        itemlst = []
        for name, val in self.collection.listStaticEntities():
            itemlst.append([name, '%s: %s' % (name, html.escape(repr(val))), 0])
        result = []
        if itemlst:
            result.append(['checkgroup', 'Items in Set<br>(Select to Delete)',
                           'items', itemlst])
        return widgets.Form.getFormFields(self, request, result)

    def process(self, write, request, submit, items=()):
        for item in items:
            self.collection.delEntity(item)
        write("<b>Items Deleted.</b><br>(%s)<br>" % html.escape(repr(items)))
        self.format(self.getFormFields(request), write, request)
