# -*- test-case-name: twisted.test.test_world -*-
#
# Twisted, the Framework of Your Internet
# Copyright (C) 2001-2002 Matthew W. Lefkowitz
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
#

from __future__ import generators

# System Imports
import os
opj = os.path.join
import weakref
import operator
from struct import pack, unpack
import md5
import time
import cPickle

# Twisted Imports
from twisted.python import reflect

# Sibling Imports
from twisted.world import hashless
from twisted.world.structfile import FixedSizeString, StructuredFile
from twisted.world.storable import Storable, _currentVersion
from twisted.world.typemap import getMapper

class Table:
    def __init__(self, db, classname, version=None):
        self.classname = classname
        self._class = None
        self._kwmapcache = None
        self._mapcache = None
        self.db = db
        self.colNameToId = {}
        self.structArgs = []
        lowColId = 0
        if version is None:
            version = _currentVersion(self.getClass())
        self.version = version
        self._makeSchema()

        for mapper, nam in self.getSchema():
            lowcols = mapper.getLowColumns(nam)
            self.structArgs.extend(lowcols)
            for typ, nam in lowcols:
                self.colNameToId[nam] = lowColId
                lowColId += 1
        self.instanceData = db.structured("%s-%s.data" % (self.classname,
                                                          self.version),
                                          *self.structArgs)

    def close(self):
        self.instanceData.close()

    def getClass(self):
        if self._class is None:
            self._class = reflect.namedClass(self.classname)
        return self._class

    def _makeSchema(self):
        mapCacheFileName = opj(self.db.dirname,
                               "%s-%s.schema" % (self.classname,
                                                 self.version) )
        self.isCurrent = (self.version == _currentVersion(self.getClass()))
        if self.isCurrent:
            clazz = self.getClass()
            self._mapcache = tuple(
                [(getMapper(clazz.__schema__[name]), name)
                 for name in clazz._schema_storeorder]
                )
            if os.path.exists(mapCacheFileName):
                # load it
                f = open(mapCacheFileName, "rb")
                o = cPickle.load(f)
                f.close()
                one = [(x.toTuple(), n) for x,n in o]
                two = [(x.toTuple(), n) for x,n in self._mapcache]
                assert one == two, "%s != %s" % (str(one), str(two))
            else:
                # what the heck, let's pickle it
                f = open(mapCacheFileName, "wb")
                cPickle.dump(self._mapcache, f)
                f.flush()
                f.close()
        else:
            assert os.path.exists(mapCacheFileName), \
                   "I'm not deleting the schema cache anywhere yet, so this shouldn't happen."
            f = open(mapCacheFileName, "rb")
            self._mapcache = cPickle.load(f)
            f.close()
        self._kwmapcache = d = {}
        for v, k in self._mapcache:
            d[k] = v

    def getSchema(self):
        return self._mapcache

    def setDataFor(self, inst, name, value):
        offt = self.db.oidsFile.getAt(inst._inmem_oid, "offset")
        self._kwmapcache[name].lowDataToRow(offt, name, self.db, self.instanceData, value)

    def addInstanceWithUID(self, inst, oid, genhash):
##         if reflect.qual(inst.__class__) == 'twisted.test.test_world.TwoTuples':
##             import pdb
##             pdb.set_trace()
        # populate crap data
        assert inst._schema_table is None, "caching is broken"
        inst._inmem_oid = oid
        inst._schema_oid = oid
        inst._inmem_genhash = genhash
        inst._schema_genhash = genhash
        inst._inmem_fromdb = False
        inst._schema_table = self
        offset = len(self.instanceData)
        self.instanceData.expand(1)
        if self.db._superchatty:
            self.db.dumpstep()

        # XXX: Speed this up
        for mapper, nam in self.getSchema():
            mapper.lowDataToRow(offset, nam, self.db, self.instanceData,

            ## XXX weird but (apparently?) harmless behavior: this 'getattr'
            ## will, in cases where the attribute didn't exist before the
            ## object was inserted, go all the way to the database - now that
            ## the _schema_table attribute is set, the object is considered
            ## 'stored' and will seek to its offset.

                                getattr(inst, nam))

        return offset

    def loadInstance(self, offset, oid, genhash):
        # Make sure we're in a consistent state with the OID index.
        sanitycheck_oid = self.instanceData.getAt(offset, TABLE_OID)
        sanitycheck_genhash = self.instanceData.getAt(offset, TABLE_GENHASH)
        if (sanitycheck_oid != oid) or (sanitycheck_genhash != genhash):
            # import pdb; pdb.set_trace()
            raise AssertionError(
                "Sanity Check Failed: %s ~ %s,  %s ~ %s" %
                (oid, sanitycheck_oid, genhash, sanitycheck_genhash))
        obj = self.getClass().fromDB(self, oid, genhash)
        if not self.isCurrent:
            # we need to upgrade
            currentTable = self.db.registerClass(self.getClass())
            firstInput = {}
            # get the old data
            for mapper, name in self.getSchema():
                firstInput[name] = mapper.highDataFromRow(
                    self.db.oidsFile.getAt(oid, "offset"),
                    name, self.db, self.instanceData)
            # convert the data to the new data
            output = obj._upgradeFrom(self.version, firstInput)
            # sprinkle it with pixie dust
            output['_schema_oid'] = oid
            output['_schema_genhash'] = genhash
            # move the new data to the new table
            # XXX TODO - I AM LEAKING A ROW HERE - Correct thing to do is
            # decref, then incref.
            offset = len(currentTable.instanceData)
            currentTable.instanceData.expand(1)
            for mapper, name in currentTable.getSchema():
                mapper.lowDataToRow(offset, name, self.db,
                                    currentTable.instanceData,
                                    output.get(name))
            self.db.oidsFile.setAt(oid, "classId", self.db.classToClassId[self.classname])
            self.db.oidsFile.setAt(oid, "offset", offset)
            obj._schema_table = currentTable
        return obj

TABLE_OID = "_schema_oid"
TABLE_GENHASH = "_schema_genhash"
##         for mapper, nam in self.getSchema():
##             recTup = []
##             for lowType, lowName in mapper.getLowColumns(nam):
##                 recTup.append(self.instanceData.getAt(offset, lowName))
##             highCol = mapper.lowToHigh(self.db, tuple(recTup))



class Database:
    def __init__(self, dirname):
        self.dirname = dirname
        if not os.path.exists(dirname):
            os.mkdir(dirname)
        self.identityToUID = hashless.HashlessWeakKeyDictionary()
        self.uidToIdentity = weakref.WeakValueDictionary()
        self.classes = self.structured("classes",
                                       (int, "version"),
                                       (FixedSizeString(512), "classname"))
        self.oidsFile = self.structured("objects",
                                        (int, "hash"),
                                        (bool, "root"),
                                        (int, "refcount"),
                                        (int, "offset"),
                                        (int, "classId"))
        if len(self.oidsFile) == 0:
            self.oidsFile.append((0, 0, 0, 0, 0))
        if len(self.classes) == 0:
            self.classes.append((0, ''))
        self.classToClassId = {}
        self.tables = []
        mapFile = opj(self.dirname, "mappers")
        if os.path.exists(mapFile):
            self.typeMapperKeyToMapper = cPickle.load(open(mapFile))
            self.typeMapperTupToKey = {}
            for k, v in self.typeMapperKeyToMapper.iteritems():
                self.typeMapperTupToKey[v.toTuple()] = k
        else:
            self.typeMapperTupToKey = {}
            self.typeMapperKeyToMapper = {}
        c = 0
        self.tables.append(None)
        for version, cn in self.classes:
            #classname = cn.strip('\x00')
            # strip(arg) is in 2.2.2, but not 2.2.0 or 2.2.1
            classname = cn
            while len(classname) and classname[-1] == '\x00':
                classname = classname[:-1]
            if classname:
                currentClass = reflect.namedClass(classname)
                currentVersion = getattr(currentClass, "schemaVersion", 1)
                if currentVersion == version:
                    self.tables.append(Table(self, classname))
                    self.classToClassId[classname] = c
                elif currentVersion < version:
                    assert False, "I can't open this database because it has newer data than I know how to read."
                else:
                    self.tables.append(Table(self, classname, version))
            c += 1

    def mapperToKey(self, mapper):
        mtup = mapper.toTuple()
        if not self.typeMapperTupToKey.has_key(mtup):
            self.typeMapperTupToKey[mtup] = len(self.typeMapperTupToKey) + 1
            self.typeMapperKeyToMapper[self.typeMapperTupToKey[mtup]] = mapper
            if self._superchatty:
                print 'assigning', mapper, 'key', self.typeMapperTupToKey[mtup]
            f = open(opj(self.dirname,"mappers"),"wb")
            cPickle.dump(self.typeMapperKeyToMapper, f)
            f.flush(); f.close()
        return self.typeMapperTupToKey[mtup]

    def keyToMapper(self, key):
        return self.typeMapperKeyToMapper[key]

    def close(self):
        for table in self.tables:
            if table is not None:
                table.close()
        self.classes.close()
        self.oidsFile.close()
        del self.tables
        del self.classes
        del self.oidsFile

    def queryClassSelect(self, klass, _cond=None, **kw):
        for t in self.tables[1:]:
            if t.getClass() != klass:
                continue
            scma = t.getSchema()
            idx_OID = t.instanceData.getColumnIndex(TABLE_OID)
            idx_GENHASH = t.instanceData.getColumnIndex(TABLE_GENHASH)
            for val in t.instanceData:
                oid, genhash = val[idx_OID], val[idx_GENHASH]
                o = self.retrieveOID(oid, genhash)
                if (_cond is not None) and (not _cond(o)):
                    continue
                if kw:
                    continueOuter = False
                    for v, k in scma:
                        if k in kw:
                            if getattr(o, k, None) != kw[k]:
                                continueOuter = True
                                break
                    if continueOuter:
                        continue
                yield o

    def sanityCheck(self):
        rv = 1
        for ff in self.queryClassSelect(FragmentFile):
            rv = rv and ff.overlapSanityCheck()
        return rv

    _superchatty = False

    def insert(self, obj):

        """Insert an object into the database, returning the OID it can be
        retrieved with.

        @rtype: str
        @return: An OID to the object that is being inserted, that it can be
            retrieved with.
        """
        oid, genhash = self._insert(obj, True)
        return pack("!ii", oid, genhash).encode("hex")

    def _insert(self, obj, root):
        """Actually insert an object.

        @type obj:  L{Storable}
        @param obj: the L{Storable} to store.
        @type root: boolean
        @param root: should this reference be treated as a `root' reference?
            i.e. is this a top-level reference added by the user, to which this
            database should be treated as a container?

        @rtype: str
        @return: similar to self.insert
        """
        assert isinstance(obj, Storable), "%r is not Storable" % (obj,)
        if obj in self.identityToUID:
            return self.identityToUID[obj]
        clz = obj.__class__
        tabl = self.registerClass(clz)
        oid, genhash = self._genUIDTup()
        self.oidsFile.setAt(oid, "classId", self.classToClassId[reflect.qual(clz)])
        self.oidsFile.setAt(oid, "root", root)
        # TODO: currently the refcount of a given object is hard-coded at 1 or 2 depending on whether it's a root.  we need an actual incref/decref,
        self.oidsFile.setAt(oid, "refcount", root+1)
        self.cacheInstance(obj, (oid, genhash))
        offset = tabl.addInstanceWithUID(obj, oid, genhash)
        self.oidsFile.setAt(oid, "offset", offset)
        obj._clearcache()
        return oid, genhash


    def _genUIDTup(self):
        # TODO: actually take refcount into account; recycle OIDs
        oid = len(self.oidsFile)        # OID - location in OID file
        self.oidsFile.append((0, 0, 0, 0, 0))
        genhash = reduce(operator.xor, unpack("!iiii", md5.new(str(time.time())).digest()))
        # generation hash - garbage data to preserve UID uniqueness
        self.oidsFile.setAt(oid, "hash", genhash)
        return (oid, genhash)


    def retrieve(self, uid):
        """Retrieve an object from the database by UID.

        @type uid: str
        @param uid: The UID to a particular storable, as returned by
            L{Database.insert} or L{Storable.getUID}

        @raise KeyError: the UID was not found.
        """
        oid, genhash = unpack("!ii", uid.decode("hex"))
        return self.retrieveOID(oid, genhash, uid)

    def retrieveOID(self, oid, genhash, uid=None):
        if uid is None:
            uid = pack("!ii", oid, genhash).encode('hex')
        uidt = oid, genhash
        if oid == 0:
            # This assert can go away once I'm done testing a few apps; it's
            # not _really_ illegal
            assert genhash == 0, "Insaaane!  You shouldn't ever have an ID like this."
            return None
        if uidt in self.uidToIdentity:
            return self.uidToIdentity[uidt]
        if oid >= len(self.oidsFile):
            raise KeyError("Invalid OID %s (too large)" % (uid))
        (stored_genhash, stored_root, stored_refcount,
         stored_offset, stored_classId) = self.oidsFile[oid]
        if stored_genhash != genhash:
            raise KeyError("Invalid Generation Hash for %s (This OID was deleted and re-used)" % (uid))
        if stored_refcount == 0:
            raise KeyError("Invalid OID %s (deleted)" % uid)

        # BEGIN LOADING INSTANCE DATA
        tabl = self.tables[stored_classId]
        inst = tabl.loadInstance(stored_offset, oid, stored_genhash)
        self.cacheInstance(inst, (oid, genhash))
        inst.__awake__()
        return inst

    def cacheInstance(self, inst, uidt):
        self.uidToIdentity[uidt] = inst
        self.identityToUID[inst] = uidt

    def structured(self, name, *fields):
        """Return
        """
        retval = StructuredFile(opj(self.dirname, name),*fields)
        return retval

    def registerClass(self, klass):
        """
        @rtype: Table
        @return: a table that will store instances of this class
        """
        cn = reflect.qual(klass)
        if cn not in self.classToClassId:
            assert len(self.classes)
            self.classToClassId[cn] = len(self.classes)
            self.classes.append((_currentVersion(klass), cn))
            self.tables.append(Table(self, cn))
        return self.tables[self.classToClassId[cn]]

    def dumpHTML(self, f):
        f.write("""
        <html><head><title>Data dump of %s</title></head>
        <body>
        """ % self.dirname)
        self.dumpHTMLData(f)
        f.write('</body></html>')

    def dumpHTMLData(self, f):
        f.write("<h1>OIDs</h1>")
        self.oidsFile.dumpHTML(f)
        for table in self.tables[1:]:
            f.write('<h2>'+table.classname+'</h2>')
            table.instanceData.dumpHTML(f)

    _logcount = 0

    def dumpstep(self):
        self._logcount += 1
        f = open(os.path.join(self.dirname, "step-%s.html" % self._logcount), 'w')
        f.write("""<html><head><title>Data dump of %s</title></head>
        <body>
        <a href='step-%s.html'>previous</a> <a href='step-%s.html'>next</a>
        """ % (self.dirname, self._logcount-1, self._logcount+1))
        self.dumpHTMLData(f)
        f.write("</body></html")
        f.flush()
        f.close()
