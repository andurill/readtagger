"""Organize a cluster of interest."""
from collections import Counter
import warnings
from .cap3 import Cap3Assembly
from .tags import Tag

MAX_TSD_SIZE = 50


class TagCluster(object):
    """
    Take a cluster of reads and figure out how to organize clustered reads.

    First attempts to find the Target Site Duplication (TSD). Then tries to get the breakpoint,
    and if we get the breakpoint we can extract the sequences left and right of the insertion and
    all sequences pointing into the insertion to assemble the putative inserted sequence, for the left and right side.
    """

    def __init__(self, cluster):
        """Cluster is an iterable of pysam.AlignedSegment objects."""
        self.cluster = cluster
        self.tsd = TargetSiteDuplication(self.cluster)
        self.five_p_breakpoint, self.three_p_breakpoint = self.find_breakpoint()
        # TODO: Implement looking up what TE the insert(s) best match to
        # TODO: Sum read support:
        #   - how many reads support TSD?
        #   - how many fragments cover any part of the insertion?
        #   - how many reads support the left side, how many reads support the right side

    @property
    def left_insert(self):
        """Return insert sequence as assembled from the left side."""
        if not hasattr(self, '_left_insert'):
            if self.left_sequences:
                self._left_insert = Cap3Assembly(self.left_sequences)
            else:
                self._left_insert = None
        return self._left_insert

    @property
    def right_insert(self):
        """Return insert sequence as assembled from the right side."""
        if not hasattr(self, '_right_insert'):
            if self.right_sequences:
                self._right_insert = Cap3Assembly(self.right_sequences)
            else:
                self._right_insert = None
        return self._right_insert

    @property
    def joint_insert(self):
        """Return joint insert sequence."""
        if not hasattr(self, '_joint_insert'):
            if self.right_sequences and self.left_sequences:
                self._joint_insert = Cap3Assembly.join_assemblies([self.left_insert, self.right_insert])
            elif self.right_sequences:
                self._joint_insert = self._right_insert
            elif self._left_sequences:
                self._joint_insert = self._left_insert
            else:
                self._joint_insert = None
        return self._joint_insert

    def find_breakpoint(self):
        """
        Find the breakpoint of a potential insertion.

        We know that informative reads on the left of a insertion that don't overlap the insertion (i.e that are not split)
        must always be sense. Inversely, reads that are on the right of an insertion must always be antisense.
        Reads that are split should have their split region pointing into the insertion.

        Genome:                     |012345678901234567890
        Insertion:                  |----------vv----------
        Read left, Mate in TE:      |>>>>>>>>>>
        Read left, split in TE:     |    >>>>>>>>XX
        Target Site Duplication TSD:|          TT
        Read right, split in TE:    |        XX<<<<<<<<
        Read right, Mate in TE:     |           <<<<<<<<<<

        We have multiple options to find the insertion breakpoint.
         - We can identify the Target Site Duplication.
         - We can determine the closest read pairs before the sense of the aligned mates switches.
         - We can cluster the split and informative mates and then infer from the 2 (or more ...) clusters that are generated
           where the insertion should be placed.
        If we rely on TSD detection we may loose some information we can get from mate pairs.
        The last option will work for long read sequencing while potentially keeping the paired end information.
        """
        # Start by finding reads with informative splits
        if not self.tsd.is_valid:
            # Need to determine the break more closely.
            # If 3' or 5' of breakpoint has been identified -- use that.
            # TODO: Could eventually be improved by looking for softclipped positions without AD,
            # but then I would need to look at reads that are not marked to be in the cluster.
            # I could look at the BD tagged reads though and scan for softclipping ... .
            if self.tsd.five_p and not self.tsd.three_p:
                return self.tsd.five_p, self.infer_three_p_from_mates()
            elif self.tsd.three_p and not self.tsd.five_p:
                return self.infer_five_p_from_mates(), self.tsd.three_p
            elif not self.tsd.five_p and not self.tsd.three_p:
                return self.infer_five_p_from_mates(), self.infer_three_p_from_mates()
            elif self.tsd.five_p and self.tsd.three_p:
                # An invalid TSD was found, probably because the inferred TSD is too long.
                # This could be two close-by insertions that each have support from one side,
                # and/or --less likely-- a pre-existing duplication of that sequence?
                # Is that even a single insertion? Perhaps check that evidence
                # points to the same TE? Should I split the cluster? Maybe I should just dump
                # the cluster reads as a BAM file and inspect them to see what should be done.
                warn = "Found a cluster with 5p and 3p evidence for TSD, but reads are spaced too far apart.\n"
                warn += "The custer coordinates are tid: %s, start:%s, end%s" % (self.cluster[0].tid, self.cluster[0].pos, self.cluster[-1].reference_end)
                warnings.warn(warn)
                return self.tsd.five_p, self.tsd.three_p
        return self.tsd.five_p, self.tsd.three_p

    def infer_five_p_from_mates(self):
        """Return rightmost reference end for sense reads with BD tag."""
        five_p_reads = [r.reference_end for r in self.cluster if not r.is_reverse and r.has_tag('BD')]
        if five_p_reads:
            return max(five_p_reads)
        else:
            return None

    def infer_three_p_from_mates(self):
        """Return leftmost reference start for antisense reads with BD tag."""
        three_p_reads = [r.pos for r in self.cluster if r.is_reverse and r.has_tag('BD')]
        if three_p_reads:
            return min(three_p_reads)
        else:
            return None

    @property
    def left_sequences(self):
        """
        Find reads left of a breakpoint.

        These reads need to be sense oriented if they have a BD tag, and reads with an
        AD tag should support that particular TSD end (5p for left reads).
        """
        # TODO: extend this to also return quality values
        if not hasattr(self, '_left_sequences'):
            self._left_sequences = {}
            for r in self.cluster:
                if r.has_tag('BD'):
                    if not r.is_reverse:
                        if r.is_read1:
                            qname = "%s.1" % r.query_name
                        else:
                            qname = "%s.2" % r.query_name
                        self._left_sequences[qname] = r.get_tag('MS')
                if r.has_tag('AD') and r.query_name in self.tsd.five_p_support:
                    if r.is_reverse:
                        self._left_sequences[r.query_name] = r.query_sequence[:r.query_alignment_start]
                    else:
                        self._left_sequences[r.query_name] = r.query_sequence[r.query_alignment_end:]
        return self._left_sequences

    @property
    def right_sequences(self):
        """
        Find reads right of a breakpoint.

        These reads need to be antisense oriented if they have a BD tag, and reads with an
        AD tag should support that particular TSD end (3p for right reads).
        """
        # TODO: extend this to also return quality values
        if not hasattr(self, '_right_sequences'):
            self._right_sequences = {}
            for r in self.cluster:
                if r.has_tag('BD'):
                    if r.is_reverse:
                        if r.is_read1:
                            qname = "%s.1" % r.query_name
                        else:
                            qname = "%s.2" % r.query_name
                        self._right_sequences[qname] = r.get_tag('MS')
                if r.has_tag('AD') and r.query_name in self.tsd.three_p_support:
                    if r.is_reverse:
                        self._right_sequences[r.query_name] = r.query_sequence[:r.query_alignment_start]
                    else:
                        self._right_sequences[r.query_name] = r.query_sequence[r.query_alignment_end:]
        return self._right_sequences


class TargetSiteDuplication(object):
    """Collect Target Site Duplication methods and data."""

    def __init__(self, cluster, include_duplicates=False):
        """Return TargetSiteDuplication object for reads in cluster."""
        self.cluster = cluster
        if include_duplicates:
            self.split_ads = [r for r in self.cluster if r.has_tag('AD')]
        else:
            self.split_ads = [r for r in self.cluster if r.has_tag('AD') and not r.is_duplicate]
        self.three_p = self.find_three_p()
        self.five_p = self.find_five_p()

    @property
    def is_valid(self):
        """Return True if Target Site Duplication is valid."""
        if not hasattr(self, '_is_valid'):
            self._is_valid = self.three_p != self.five_p and self.five_p - self.three_p <= MAX_TSD_SIZE  # Super arbitrary, but I guess this is necessary
        return self._is_valid

    def find_five_p(self):
        """
        Find the five prime genomic position of a TSD.

        It is frequently further 3p than the three prime of the same TSD.
        See the below situation, read marked with * supports a TSD five prime, X indicates clipping.

          Genome:                     |012345678901234567890
          Insertion:                  |----------vv----------
          Read left, Mate in TE:      |>>>>>>>>>>
        * Read left, split in TE:     |    >>>>>>>>XX
          Target Site Duplication TSD:|          TT
          Read right, split in TE:    |        XX<<<<<<<<
          Read right, Mate in TE:     |           <<<<<<<<<<

        The five prime of a TSD is characterized by having
          - the rightmost alignment end (of reads that support an insertion with the AD tag)
          - the most frequent alignment end (of reads that support an insertion with the AD tag)
        >>> from collections import namedtuple
        >>> R = namedtuple('AlignedSegment', 'reference_end pos, has_tag')
        >>> r1 = R(reference_end=10, pos=2, has_tag=lambda x: True)
        >>> r2 = R(reference_end=12, pos=2, has_tag=lambda x: True)
        >>> r3 = R(reference_end=12, pos=2, has_tag=lambda x: True)
        >>> r4 = R(reference_end=12, pos=2, has_tag=lambda x: True)
        >>> tsd = TargetSiteDuplication(cluster = [r1, r2, r3, r4], include_duplicates=True)
        >>> tsd.five_p
        12
        """
        if not self.sorted_split_end_positions:
            return None
        min_five_p_aligned_end = min(self.sorted_split_end_positions)
        most_common_ends = Counter(self.sorted_split_end_positions).most_common()
        most_common_end_pos_occurence = most_common_ends[0][1]
        best_ends = [t[0] for t in most_common_ends if t[1] == most_common_end_pos_occurence]
        if min_five_p_aligned_end not in best_ends:
            # We could have a rare misaligned softclipped read (that happens if there is a mismatch close to the acutal clipped region),
            # so we check if the next position (in the genomic 3p direction) may be better (= the most frequent site).
            for p in self.sorted_split_end_positions:
                if p == min_five_p_aligned_end:
                    continue
                if p in best_ends:
                    return p
                else:
                    break
        return min_five_p_aligned_end

    def find_three_p(self):
        """
        Find the three prime genomic position of a TSD.

        It is frequently further 5p than the five prime of the same TSD.
        See the below situation, read marked with * supports a TSD five prime, X indicates clipping.

          Genome:                     |012345678901234567890
          Insertion:                  |----------vv----------
          Read left, Mate in TE:      |>>>>>>>>>>
          Read left, split in TE:     |    >>>>>>>>XX
          Target Site Duplication TSD:|          TT
        * Read right, split in TE:    |        XX<<<<<<<<
          Read right, Mate in TE:     |           <<<<<<<<<<

        The three prime of a TSD is characterized by having
          - the leftmost alignment start (of reads that support an insertion with the AD tag)
          - the most frequent alignment start (of reads that support an insertion with the AD tag)

        >>> from collections import namedtuple
        >>> R = namedtuple('AlignedSegment', 'reference_end pos, has_tag')
        >>> r1 = R(reference_end=20, pos=12, has_tag=lambda x: True)
        >>> r2 = R(reference_end=20, pos=12, has_tag=lambda x: True)
        >>> r3 = R(reference_end=20, pos=12, has_tag=lambda x: True)
        >>> r4 = R(reference_end=20, pos=14, has_tag=lambda x: True)
        >>> tsd = TargetSiteDuplication(cluster = [r1, r2, r3, r4], include_duplicates=True)
        >>> tsd.three_p
        12
        """
        if not self.sorted_split_start_positions:
            return None
        max_starting_position = max(self.sorted_split_start_positions)
        most_common_starts = Counter(self.sorted_split_start_positions).most_common()
        # Counter().most_common() returns a list of tuples,
        # where tuples are ordered from most to least common,
        # and where the first item in a tuple is the value
        # and the second is the occurence.
        most_common_occurence = most_common_starts[0][1]
        best_starts = [t[0] for t in most_common_starts if t[1] == most_common_occurence]
        if max_starting_position not in best_starts:
            # Normally the 3p soft clipped position for a TE insertion should be
            # - overrepresented among the starting positions of clipped reads
            # - the rightmost starting position
            # If that's not the case for certain reads (e.g the clip has been wrongly extended because there is an adjacent mismatch),
            # check if perhaps the next position is the mode and use this.
            for p in self.sorted_split_start_positions[::-1]:
                if p == max_starting_position:
                    continue
                if p in best_starts:
                    return p
                else:
                    break
        return max_starting_position

    @property
    def sorted_split_start_positions(self):
        """Return sorted start positions of split reads."""
        if not hasattr(self, '_sorted_split_positions'):
            self._sorted_split_positions = sorted([r.pos for r in self.split_ads])
        return self._sorted_split_positions

    @property
    def sorted_split_end_positions(self):
        """Return sorted end positions of split reads."""
        if not hasattr(self, '_sorted_split_end_positions'):
            self._sorted_split_end_positions = sorted(r.reference_end for r in self.split_ads)
        return self._sorted_split_end_positions

    @property
    def five_p_support_extension(self):
        """
        Return the longest clipped region that extends the five_p breakpoint.

        5p Breakpoint:           v
        3p Breakpoint:               v
        Genome:         |012345678901234567890
        5p split read:  |  >>>>>>XXXX
        3p split read:  |          XXX>>>>>>>

        In this case return 11 for the 5p breakpoint.
        """
        ad_cigars = [Tag.from_read(r).cigar for r in self.split_ads if r.pos == self.five_p]
        max_split = max([cig for cig in ad_cigars])
        return max_split

    @property
    def three_p_support(self):
        """Return list of Reads that support the inferred three prime position for this TSD."""
        if not hasattr(self, '_three_p_support'):
            self._three_p_support = [r.query_name for r in self.split_ads if r.pos == self.three_p]
        return self._three_p_support

    @property
    def five_p_support(self):
        """Return list of Reads that support the inferred five prime position for this TSD."""
        if not hasattr(self, '_five_p_support'):
            self._five_p_support = [r.query_name for r in self.split_ads if r.reference_end == self.five_p]
        return self._five_p_support

    @property
    def unassigned_support(self):
        """Return list of Reads that were not starting or ending at the three prime or five prime of this TSD."""
        if not hasattr(self, '_unassigned_support'):
            self._unassigned_support = [r.query_name for r in self.split_ads if r.query_name not in self.five_p_support + self.three_p_support]
        return self._unassigned_support