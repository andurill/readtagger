from readtagger.bam_io import BamAlignmentReader as Reader
from readtagger.mateoperations import AnnotateMateInformation

TEST_BAM = 'dm6.bam'


def test_mateoperations(datadir_copy, tmpdir, mocker):  # noqa: D103
    out = tmpdir.join('out.bam')
    AnnotateMateInformation(target=str(datadir_copy[TEST_BAM]), source=str(datadir_copy[TEST_BAM]), output_path=out.strpath, mate_sequence_tag='MS')
    with Reader(out.strpath) as reader:
        reads = [r for r in reader]
        assert len([True for r in reads if r.has_tag('MS')]) == 2
        assert reads[0].query_sequence == reads[1].get_tag('MS')
