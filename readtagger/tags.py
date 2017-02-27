from collections import namedtuple
from .cigar import (
    cigartuples_to_cigarstring,
    cigar_tuple_to_cigar_length,
    cigar_to_tuple
)


class BaseTag(object):
    """Generate class template for tags."""

    def __new__(cls, tid_to_reference_name):
        """Return a Tag class that knows how to format a tag."""
        return type('NamedTagTuple', (namedtuple('tag', 'tid reference_start cigar is_reverse mapq qstart qend'),),
                    {'__str__': lambda self: self.tag_str_template % (self.tid_to_reference_name[self.tid],
                                                                      self.reference_start,
                                                                      self.qstart,
                                                                      self.qend,
                                                                      cigartuples_to_cigarstring(self.cigar),
                                                                      'AS' if self.is_reverse else 'S',
                                                                      self.mapq),
                     'tid_to_reference_name': tid_to_reference_name,
                     'tag_str_template': "R:%s,POS:%d,QSTART:%d,QEND:%d,CIGAR:%s,S:%s,MQ:%d"})


class Tag(object):
    """Collect tag attributes and conversion."""

    def __init__(self, reference_start, cigar, is_reverse, mapq=None, qstart=None, qend=None, tid=None, reference_name=None):
        """
        Return new Tag instance from kwds.

        Note that the cigar is always wrt the reference alignment.
        When comparing Tag object by their cigar, one of the cigar needs to be inverted if the
        Tag objects are not in the same orientation.
        """
        self.reference_start = reference_start
        self._cigar = cigar
        self.is_reverse = is_reverse
        self.mapq = mapq
        self.qstart = qstart
        self.qend = qend
        self.tid = tid
        self.reference_name = reference_name

    @property
    def cigar_regions(self):
        """
        Return cigar regions as list of tuples in foim [(start, end), operation].

        >>> Tag(reference_start=0, cigar='20M30S', is_reverse='True', mapq=60, qstart=0, qend=20, tid=5).cigar_regions
        [((0, 20), 0), ((20, 50), 4)]
        """
        if not hasattr(self, '_cigar_regions'):
            self._cigar_regions = cigar_tuple_to_cigar_length(self.cigar)
        return self._cigar_regions

    @property
    def cigar(self):
        """
        Lazily convert cigarstring to tuple if it doesn't exist.

        >>> Tag(reference_start=0, cigar='20M30S', is_reverse='True', mapq=60, qstart=0, qend=20, tid=5).cigar
        [CIGAR(operation=0, length=20), CIGAR(operation=4, length=30)]
        """
        if isinstance(self._cigar, str):
            self._cigar = cigar_to_tuple(self._cigar)
        return self._cigar

    @staticmethod
    def from_read(r):
        """
        Return Tag instance from pysam.AlignedSegment Instance.

        >>> AlignedSegment = namedtuple('AlignedSegment', 'tid reference_start cigar is_reverse mapping_quality qstart qend')
        >>> t = Tag.from_read(AlignedSegment(reference_start=0, cigar='20M30S', is_reverse='True', mapping_quality=60, qstart=0, qend=20, tid=5))
        >>> isinstance(t, Tag)
        True
        """
        return Tag(tid=r.tid,
                   reference_start=r.reference_start,
                   cigar=r.cigar,
                   is_reverse=r.is_reverse,
                   mapq=r.mapping_quality,
                   qstart=r.qstart,
                   qend=r.qend)

    @staticmethod
    def from_tag_str(tag_str):
        """
        Return Tag Instance from tag string.

        >>> t = Tag.from_tag_str('R:FBti0019061_rover_Gypsy,POS:7435,QSTART:0,QEND:34,CIGAR:34M91S,S:S,MQ:60')
        >>> isinstance(t, Tag)
        True
        >>> t.cigar == [(0, 34), (4, 91)]
        True
        >>> t = Tag.from_tag_str('R:FBti0019061_rover_Gypsy,POS:7435,QSTART:0,QEND:34,CIGAR:34M91S,S:AS,MQ:60')
        >>> t.is_reverse
        True
        """
        tag_to_attr = {'R': 'reference_name', 'POS': 'reference_start', 'QSTART': 'qstart', 'QEND': 'qend', 'CIGAR': 'cigar', 'S': 'is_reverse', 'MQ': 'mapq'}
        integers = ['reference_start', 'qstart', 'qend', 'mapq']
        tag_d = {tag_to_attr[k]: v for k, v in dict(item.split(':') for item in tag_str.split(',')).items()}
        if tag_d['is_reverse'] == 'S':
            tag_d['is_reverse'] = False
        else:
            tag_d['is_reverse'] = True
        for integer in integers:
            tag_d[integer] = int(tag_d.get(integer, 0))
        return Tag(**tag_d)

    def to_dict(self):
        """
        Serialize self into dictionary.

        >>> t = Tag.from_tag_str('R:FBti0019061_rover_Gypsy,POS:7435,QSTART:0,QEND:34,CIGAR:34M91S,S:S,MQ:60')
        >>> t.to_dict()['is_reverse']
        False
        """
        return {'reference_start': self.reference_start,
                'cigar': self.cigar,
                'mapq': self.mapq,
                'qstart': self.qstart,
                'qend': self.qend,
                'is_reverse': self.is_reverse,
                'tid': self.tid}  # Improve this by passing tid or reference name

    def to_namedtuple(self, nt):
        """
        Convert self to namedtuple.

        >>> named_tag_tuple = BaseTag(tid_to_reference_name={5:'3R'})
        >>> t = Tag(reference_start=0, cigar='20M30S', is_reverse='True', mapq=60, qstart=0, qend=20, tid=5)
        >>> str(t.to_namedtuple(named_tag_tuple))
        'R:3R,POS:0,QSTART:0,QEND:20,CIGAR:20M30S,S:AS,MQ:60'
        """
        return nt(**self.to_dict())