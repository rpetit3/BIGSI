#! /usr/bin/env python
from __future__ import print_function
from remcdbg.utils import min_lexo
from remcdbg.utils import seq_to_kmers
from remcdbg.mcdbg import McDBG
import argparse
import os.path
import time
from Bio import SeqIO
import json


def per(i):
    return float(sum(i))/len(i)


def parse_input(infile):
    gene_to_kmers = {}
    with open(infile, 'r') as inf:
        for record in SeqIO.parse(inf, 'fasta'):
            gene_to_kmers[record.id] = [
                k for k in seq_to_kmers(str(record.seq))]
    return gene_to_kmers


def run(parser, args, conn_config):
    gene_to_kmers = parse_input(args.fasta)
    mc = McDBG(conn_config=conn_config, storage={'redis': conn_config})
    colours_to_samples = mc.colours_to_sample_dict()
    results = {}
    found = {}
    for gene, kmers in gene_to_kmers.items():
        found[gene] = {}
        start = time.time()
        found[gene]['results'] = mc.query_kmers(kmers, args.threshold)
        diff = time.time() - start
        found[gene]['time'] = diff
    print(json.dumps(found, indent=4))
