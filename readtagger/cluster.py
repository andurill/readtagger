from cached_property import cached_property
from .genotype import Genotype
from .cap3 import Cap3Assembly
from .tagcluster import TagCluster


class Cluster(list):
    """A Cluster of reads."""

    left_blast_result = None
    right_blast_result = None

    @cached_property
    def min(self):
        """
        Cache leftmost start of cluster.

        This assumes that the cluster is filled from left to right.
        """
        return self[0].pos

    @cached_property
    def tid(self):
        """Cache current reference id."""
        return self[0].tid

    @property
    def max(self):
        """Reference end of last read added to cluster."""
        return self[-1].reference_end

    def overlaps(self, r):
        """Determine if r overlaps the current cluster."""
        return r.pos <= self.max

    def same_chromosome(self, r):
        """Whether r is on same chromsome as cluster."""
        return self.tid == r.tid

    def read_is_compatible(self, r):
        """Determine if read overlaps cluster and is on same chromosome."""
        return self.overlaps(r) and self.same_chromosome(r)

    @property
    def read_index(self):
        """Index of read names in cluster."""
        if not hasattr(self, '_read_index') or (hasattr(self, '_clusterlen') and len(self) != self._clusterlen):
            self._read_index = set([r.query_name for r in self])
        return self._read_index

    def read_in_cluster(self, read):
        """Return whether read.query_name is in cluster."""
        return read.query_name in self.read_index

    @property
    def hash(self):
        """Calculate a hash based on read name and read sequence for all reads in this cluster."""
        string_to_hash = "|".join(["%s%s" % (r.query_name, r.query_sequence) for r in self])
        return hash(string_to_hash)

    @property
    def clustertag(self):
        """Return clustertag for current cluster of reads."""
        if not hasattr(self, '_clustertag') or (hasattr(self, '_clusterlen') and len(self) != self._clusterlen):
            self._clusterlen = len(self)
            self._clustertag = TagCluster(self)
        return self._clustertag

    def can_join(self, other_cluster, max_distance=1500):
        """
        Join clusters that have been split or mates that are not directly connected.

        This can happen when an insertion erodes a number of nucleotides at the insertion site. Example in HUM4 at chr3R:13,373,242-13,374,019.
        The situation looks like this then:

        Reference Genome:       012345678901234567890
        left cluster read1:     >>>>>>>>XXXXX
        left cluster read2:       >>>>>>XXXXX
        right cluster read1             XXXXX<<<<<<<<
        right cluster read2:            XXXXX<<<<<

        Bunch of characteristics here:
          - left cluster shouldn't have any 3'support, right cluster no 5' support
          - clipped reads should overlap (except if a large number of nucleotides have been eroded: that could be an interesting mechanism.)
          - inferred insert should point to same TE # TODO: implement this
        """
        if hasattr(self, '_cannot_join_d'):
            # We already tried joining this cluster with another cluster,
            # so if we checked if we can try joining the exact same clusters
            # (self.hash is key in self._cannot_join and other_cluster.hash is value in self._cannot_join)
            # we know this didn't work and save ourselves the expensive assembly check
            other_hash = self._cannot_join_d.get(self.hash)
            if other_hash == other_cluster.hash:
                return False
        if hasattr(self, '_can_join_d'):
            other_hash = self._can_join_d.get(self.hash)
            if other_hash == other_cluster.hash:
                return True
        return self._can_join(other_cluster, max_distance)

    def _can_join(self, other_cluster, max_distance):
        other_clustertag = TagCluster(other_cluster)
        # First check ... are three_p and five_p of cluster overlapping?
        if not self.clustertag.tsd.three_p and not other_clustertag.tsd.five_p:
            if self.clustertag.tsd.five_p and other_clustertag.tsd.three_p:
                extended_three_p = other_clustertag.tsd.three_p - other_clustertag.tsd.three_p_clip_length
                extended_five_p = self.clustertag.tsd.five_p_clip_length + self.clustertag.tsd.five_p
                if extended_three_p <= extended_five_p:
                    self._can_join_d = {self.hash: other_cluster.hash}
                    return True
        # Next check ... can informative parts of mates be assembled into the proper insert sequence
        if self.clustertag.left_sequences and other_clustertag.left_sequences:
            # A cluster that provides support for a 5p insertion will have the reads always annotated as left sequences.
            # That's a bit confusing, since the mates are to the right of the cluster ... but that's how it is.
            if (other_clustertag.five_p_breakpoint - self.clustertag.five_p_breakpoint) < max_distance:
                # We don't want clusters to be spaced too far away. Not sure if this is really a problem in practice.
                if Cap3Assembly.sequences_contribute_to_same_contig(self.clustertag.left_sequences, other_clustertag.left_sequences):
                    self._can_join_d = {self.hash: other_cluster.hash}
                    return True
        # We know this cluster (self) cannot be joined with other_cluster, so we cache this result,
        # Since we may ask this question multiple times when joining the clusters.
        self._cannot_join_d = {self.hash: other_cluster.hash}
        return False

    @cached_property
    def left_support(self):
        """Number of supporting reads on the left side of cluster."""
        return len(set(list(self.clustertag.left_sequences.keys())))

    @cached_property
    def right_support(self):
        """Number of supporting reads on the right side of cluster."""
        return len(set(list(self.clustertag.right_sequences.keys())))

    @cached_property
    def score(self):
        """Sum of all supporting reads for this cluster."""
        return self.left_support + self.right_support

    @cached_property
    def left_contigs(self):
        """Left contigs for this cluster."""
        if self.clustertag.left_sequences:
            return [contig.sequence for contig in self.clustertag.left_insert.assembly.contigs]
        else:
            return []

    @cached_property
    def right_contigs(self):
        """Right contigs for this cluster."""
        if self.clustertag.right_sequences:
            return [contig.sequence for contig in self.clustertag.right_insert.assembly.contigs]
        else:
            return []

    @cached_property
    def start(self):
        """Start coordinate for this cluster."""
        return self._start_and_end[0]

    @cached_property
    def end(self):
        """End coordinate for this cluster."""
        return self._start_and_end[1]

    @cached_property
    def _start_and_end(self):
        start = self.clustertag.five_p_breakpoint
        end = self.clustertag.three_p_breakpoint
        if start is None:
            start = end
        if end is None:
            end = start
        if start > end:
            end, start = start, end
        if start == end:
            end += 1
        return start, end

    @cached_property
    def valid_tsd(self):
        """Current cluster is a TSD."""
        return self.clustertag.tsd.is_valid

    def genotype_likelihood(self):
        r"""
        Calculate genotype likelihood for current cluster.

        P(g|D) = P(g)P(D\g)/sum(P(g)P(D|g')) where P(D|g) = Pbin(Nalt, Nalt + Nfef)
        :return:
        """
        nref = len(self.non_support_evidence())
        nalt = len(self.read_index)
        return Genotype(nref=nref, nalt=nalt)

    def non_support_evidence(self, alignment_file=None, include_duplicates=False):
        """
        Get all reads that are close to the insertion site but that do not support the insertion.

        A relevant readpair does not support an insertion if the region between the minimum and maximum of a readpair
        covers either self.start or self.end but is not listed in self.left_support or self.right_support
        :return:
        """
        if not hasattr(self, '_non_support_evidence') and alignment_file:  # Hacky, there should be a better way to access non_support_evidence
            upstream = self.start - 500
            downstream = self.end + 500
            region = {r.query_name: r for r in alignment_file.fetch(start=upstream,
                                                                    end=downstream,
                                                                    tid=self.tid) if r.is_proper_pair and not self.read_in_cluster(r)}
            non_support_reads = []
            for r in region.values():
                if r.is_duplicate and include_duplicates:
                    min_start = min([r.pos, r.mpos])
                    max_end = max(r.aend, r.pos + r.isize)
                    if self.overlaps_cluster(left=min_start, right=max_end):
                        non_support_reads.append(r)
            self._non_support_evidence = non_support_reads
        return self._non_support_evidence

    def overlaps_cluster(self, left, right):
        """Return whether a read overlaps a cluster."""
        return left < self.start < right or left < self.end < right
