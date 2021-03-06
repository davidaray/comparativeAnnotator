"""
This file contains helper functions for comparativeAnnotator. These functions revolve around analyzing indels,
frameshifts and codons.
"""

__author__ = "Ian Fiddes"


def insertion_iterator(a, t, aln, mult3=None):
    """
    Target insertion:
    query:   AATTAT--GCATGGA
    target:  AATTATAAGCATGGA

    Analyze a given annotation transcript, transcript and alignment for insertions.

    mult3 controls whether only multiple of 3 or only not multiple of 3 are reported. Set to None to report all.
    """
    prev_target_i = None
    exon_starts = [x.start for x in a.exons]
    for query_i in xrange(len(a)):
        if query_i in exon_starts:
            # don't call a intron an insertion
            prev_target_i = None
            continue
        target_i = aln.query_coordinate_to_target(query_i)
        if target_i is None:
            # deletion; ignore
            prev_target_i = target_i
            continue
        if prev_target_i is not None and abs(target_i - prev_target_i) != 1:
            # jumped over a insertion
            insert_size = abs(target_i - prev_target_i) - 1
            start = min(prev_target_i, target_i) + 1
            stop = max(prev_target_i, target_i)
            if mult3 is True and insert_size % 3 == 0:
                yield start, stop, insert_size
            elif mult3 is False and insert_size % 3 != 0:
                yield start, stop, insert_size
            elif mult3 is None:
                yield start, stop, insert_size
        prev_target_i = target_i


def deletion_iterator(a, t, aln, mult3=None):
    """
    Target deletion:
    query:   AATTATAAGCATGGA
    target:  AATTAT--GCATGGA

    Analyze a given annotation transcript, transcript and alignment for deletions.

    mult3 controls whether only multiple of 3 or only not multiple of 3 are reported.
    """
    prev_query_i = None
    for target_i in xrange(len(t)):
        target_chrom_i = t.transcript_coordinate_to_chromosome(target_i)
        query_i = aln.target_coordinate_to_query(target_chrom_i)
        if query_i is None:
            # insertion; ignore
            prev_query_i = query_i
            continue
        if prev_query_i is not None and abs(query_i - prev_query_i) != 1:
            # jumped over a deletion
            delete_size = abs(query_i - prev_query_i) - 1
            if t.strand is True:
                start = stop = target_chrom_i - 1
            else:
                start = stop = target_chrom_i + 1
            if mult3 is True and delete_size % 3 == 0:
                yield start, stop, -delete_size
            elif mult3 is False and delete_size % 3 != 0:
                yield start, stop, -delete_size
            elif mult3 is None:
                yield start, stop, -delete_size
        prev_query_i = query_i


def frame_shift_iterator(a, t, aln):
    """
    Yields frameshift-causing mutations. These are defined as non mult3 indels within CDS.
    """
    deletions = list(deletion_iterator(a, t, aln, mult3=False))
    insertions = list(insertion_iterator(a, t, aln, mult3=False))
    # need to fix case where indel immediately precedes indel by merging overlapping ranges and combining spans
    merged = []
    for higher in sorted(deletions + insertions):
        if not merged:
            merged.append(higher)
        else:
            lower = merged[-1]
            if higher[0] <= lower[1]:
                upper_bound = max(lower[1], higher[1])
                merged[-1] = (lower[0], upper_bound, merged[-1][2] + higher[2])
            else:
                merged.append(higher)
    if t.strand is False:
        merged = [[y, x, z] for x, y, z in reversed(merged) if z % 3 != 0]
    else:
        merged = [[x, y, z] for x, y, z in merged if z % 3 != 0]
    for start, stop, span in merged:
        if start >= t.thickStart and stop < t.thickStop:
            yield start, stop, span


def codon_pair_iterator(a, t, aln, target_seq_dict, query_seq_dict):
    """
    Inputs:
    Transcript objects representing the annotation (query) transcript and the target transcript.
    PslRow object that represents the alignment between the transcript objects.
    SeqDicts/TwoBitFileObjs that contain the genomic sequence for these two transcripts

    Order is (target_cds_pos, target, query)
    """
    target_cds = t.get_cds(target_seq_dict)
    query_cds = a.get_cds(query_seq_dict)
    a_frames = [x for x in a.exonFrames if x != -1]
    if a.strand is True:
        a_offset = a_frames[0]
    else:
        a_offset = 3 - a_frames[-1]
    for i in xrange(a_offset, a.getCdsLength(), 3):
        target_cds_positions = [t.chromosome_coordinate_to_cds(
                                aln.query_coordinate_to_target(
                                a.cds_coordinate_to_transcript(j)))
                                for j in xrange(i, i + 3)]
        if None in target_cds_positions:
            continue
        # sanity check - should probably remove. But should probably write tests too...
        assert all([target_cds_positions[2] - target_cds_positions[1] == 1, target_cds_positions[1] -
                    target_cds_positions[0] == 1, target_cds_positions[2] - target_cds_positions[0] == 2])
        target_codon = target_cds[target_cds_positions[0]:target_cds_positions[0] + 3]
        query_codon = query_cds[i:i + 3]
        yield target_cds_positions[0], target_codon, query_codon


def compare_intron_to_reference(intron, a, aln, compare_dict, ref_dict):
    """
    For use with the splicing classifiers. Given an index of an intron in t that has a problem,
    determines if this intron exists in the reference. Then, determines if this reference splice
    also has the problem defined by compare_dict. Returns True if the reference also has a splicing problem.

    TODO: I don't understand why I am effectively adding 2 below, once before and once after. a_start cannot ever have
    been None because this would raise a TypeError. I am scared to change this without a test...
    """
    a_start = a.transcript_coordinate_to_chromosome(aln.target_coordinate_to_query(intron.start - 1)) + 1
    a_stop = a.transcript_coordinate_to_chromosome(aln.target_coordinate_to_query(intron.stop))
    if a_start is None or a_stop is None:
        return False
    a_start += 1
    for a_intron in a.intronIntervals:
        if a_intron.start == a_start and a_intron.stop == a_stop:
            ref_seq = a_intron.get_sequence(ref_dict, strand=True)
            donor, acceptor = ref_seq[:2], ref_seq[-2:]
            if donor not in compare_dict or compare_dict[donor] != acceptor:
                return True
    return False