# -*- test-case-name: twisted.test.test_asn1 -*-

from record import RecordMixin as Record, Integer

universalTypeTags = {
    'INTEGER': 2,
    'BIT STRING': 3, # string of ones and zeros
    'NULL': 5,
    'OCTET STRING': 4, # string of 8-bit values
    'OBJECT IDENTIFIER': 6, # sequence of integer components
                            # identifying an object
    'SEQUENCE': 16,
    'SET': 17,
    'PrintableString': 19, # string of printable characters
    'T61String': 20, # string of T.61 characters
    'IA5String': 22, # string of ASCII characters
    'UTCTime': 23}


class Identifier(Record):
    UNIVERSAL = 0
    APPLICATION = 1
    CONTEXT_SPECIFIC = 2
    PRIVATE = 3

    def __format__():
        def get(self):
            yield ('tagNumber', Integer(5))
            yield ('primitiveTag', Integer(1))
            yield ('classType', Integer(2))

            if self.tagNumber == 63:
                # High-tag-number form
                byteArray = [255]
                while byteArray[-1] > 127:
                    yield byteArray.append, Integer(8)
                accum = 0
                i = iter(byteArray)
                i.next()
                for byte in i:
                    accum <<= 8
                    accum |= byte
                self.tagNumber = accum
        return get,
    __format__ = property(*__format__())

class Length(Record):
    def __format__():
        def get(self):
            yield "payload", Integer(7)
            yield "form", Integer(1)

            if self.form == 0:
                self.length = self.payload
            else:
                yield "length", Integer(self.payload * 8)
