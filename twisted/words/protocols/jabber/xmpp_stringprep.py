import stringprep
import unicodedata
from encodings import idna

class ILookupTable:
    """ Interface for character lookup classes. """

    def lookup(self, c):
        """ Return whether character is in this table. """

class LookupTableFromFunction:

    __implements__ = ILookupTable

    def __init__(self, in_table_function):
        self.lookup = in_table_function

class LookupTable:

    __implements__ = ILookupTable

    def __init__(self, table):
        self._table = table

    def lookup(self, c):
        return c in self._table

C_11 = LookupTableFromFunction(stringprep.in_table_c11)
C_12 = LookupTableFromFunction(stringprep.in_table_c12)
C_21 = LookupTableFromFunction(stringprep.in_table_c21)
C_22 = LookupTableFromFunction(stringprep.in_table_c22)
C_3 = LookupTableFromFunction(stringprep.in_table_c3)
C_4 = LookupTableFromFunction(stringprep.in_table_c4)
C_5 = LookupTableFromFunction(stringprep.in_table_c5)
C_6 = LookupTableFromFunction(stringprep.in_table_c6)
C_7 = LookupTableFromFunction(stringprep.in_table_c7)
C_8 = LookupTableFromFunction(stringprep.in_table_c8)
C_9 = LookupTableFromFunction(stringprep.in_table_c9)

class IMappingTable:
    """ Interface for character mapping classes. """

    def map(self, c):
        """ Return mapping for character. """

class MappingTableFromFunction:

    __implements__ = IMappingTable

    def __init__(self, map_table_function):
        self.map = map_table_function

class EmptyMappingTable:
    
    __implements__ = IMappingTable

    def map(self, c):
        if stringprep.in_table_b1(c):
            return None
        else:
            return c

B_1 = EmptyMappingTable()
B_2 = MappingTableFromFunction(stringprep.map_table_b2)

class Profile:
    def __init__(self, mappings, prohibiteds):
        self._mappings = mappings
        self._prohibiteds = prohibiteds

    def prepare(self, string):
        result = self.map(string)
        result = unicodedata.normalize("NFKC", result)
        self.check_prohibiteds(result)
        self.check_unassigneds(result)
        self.check_bidirectionals(result)
        return result

    def map(self, string):
        result = []

        for c in string:
            result_c = c

            for mapping in self._mappings:
                result_c = mapping.map(c)
                if result_c != c:
                    break

            if result_c is not None:
                result.append(result_c)

        return u"".join(result)

    def check_prohibiteds(self, string):
        for c in string:
            for table in self._prohibiteds:
                if table.lookup(c):
                    raise UnicodeError, "Invalid character %s" % repr(c)

    def check_unassigneds(self, string):
        for c in string:
            if stringprep.in_table_a1(c):
                raise UnicodeError, "Unassigned code point %s" % repr(c)
    
    def check_bidirectionals(self, string):
        found_LCat = False
        found_RandALCat = False

        for c in string:
            if stringprep.in_table_d1(c):
                found_RandALCat = True
            if stringprep.in_table_d2(c):
                found_LCat = True

        if found_LCat and found_RandALCat:
            raise UnicodeError, "Violation of BIDI Requirement 2"

        if found_RandALCat and not (stringprep.in_table_d1(string[0]) and
                                    stringprep.in_table_d1(string[-1])):
            raise UnicodeError, "Violation of BIDI Requirement 3"


nodeprep = Profile(mappings=[B_1, B_2],
                   prohibiteds=[C_11, C_12, C_21, C_22,
                                C_3, C_4, C_5, C_6, C_7, C_8, C_9,
                                LookupTable([u'"', u'&', u"'", u'/',
                                             u':', u'<', u'>', u'@'])])

resourceprep = Profile(mappings=[B_1,],
                       prohibiteds=[C_12, C_21, C_22,
                                    C_3, C_4, C_5, C_6, C_7, C_8, C_9])

class NamePrep:
    """ Implements nameprep on international domain names.
    
    STD3ASCIIRules is assumed true in this implementation.
    """

    # Prohibited characters.
    _prohibiteds = [unichr(n) for n in range(0x00, 0x2c + 1) +
	                                   range(0x2e, 0x2f + 1) +
									   range(0x3a, 0x40 + 1) +
									   range(0x5b, 0x60 + 1) +
									   range(0x7b, 0x7f + 1) ]

    def prepare(self, string):
        result = []

        labels = idna.dots.split(string)
        if labels and len(labels[-1]) == 0:
            trailing_dot = '.'
            del labels[-1]
        else:
            trailing_dot = ''

        for label in labels:
            result.append(self.nameprep(label))

        return ".".join(result)+trailing_dot

    def check_prohibiteds(self, string):
        for c in string:
           if c in self._prohibiteds:
               raise UnicodeError, "Invalid character %s" % repr(c)

    def nameprep(self, label):
        label = idna.nameprep(label)
        self.check_prohibiteds(label)
        if label[0] == '-':
            raise UnicodeError, "Invalid leading hyphen-minus"
        if label[-1] == '-':
            raise UnicodeError, "Invalid trailing hyphen-minus"
        return label

nameprep = NamePrep()
