#! /usr/bin/env python
from __future__ import print_function
import sys
import os
import argparse
import redis
import json
sys.path.append(
    os.path.realpath(
        os.path.join(
            os.path.dirname(__file__),
            "..")))
from bfg.version import __version__
import logging
logging.basicConfig(level=logging.DEBUG)

logger = logging.getLogger(__name__)
from bfg.utils import DEFAULT_LOGGING_LEVEL
logger.setLevel(DEFAULT_LOGGING_LEVEL)


import hug
import tempfile
from bfg.graph import ProbabilisticMultiColourDeBruijnGraph as Graph

BFSIZE = int(os.environ.get("BFSIZE", 25000000))
NUM_HASHES = int(os.environ.get("NUM_HASHES", 3))
CREDIS = bool(os.environ.get("CREDIS", True))
CELERY = bool(int(os.environ.get("CELERY", 0)))
# if CREDIS:
#     logger.info(
#         "You're running with credis.")
# if CELERY:
#     logger.info(
#         "You're running using celery background process. Please make sure celery is running in the background otherwise tasks may hang indefinitely ")
CONN_CONFIG = []
redis_envs = [env for env in os.environ if "REDIS" in env]
if len(redis_envs) == 0:
    CONN_CONFIG = [('localhost', 7000, 2)]
else:
    for i in range(int(len(redis_envs)/2)):
        hostname = os.environ.get("REDIS_IP_%s" % str(i + 1))
        port = int(os.environ.get("REDIS_PORT_%s" % str(i + 1)))
        CONN_CONFIG.append((hostname, port, 2))
from bfg.cmds.insert import insert
from bfg.cmds.search import search
from bfg.cmds.stats import stats
from bfg.cmds.samples import samples
from bfg.cmds.dump import dump
from bfg.cmds.load import load
from bfg.cmds.delete import delete
from bfg.cmds.bloom import bloom
from bfg.cmds.build import build
from bfg.cmds.merge import merge
from bfg.cmds.rowjoin import rowjoin
# from bfg.cmds.bitcount import bitcount
# from bfg.cmds.jaccard_index import jaccard_index
from bfg.utils.cortex import GraphReader


API = hug.API('atlas')
STORAGE = os.environ.get("STORAGE", 'berkeleydb')
BDB_DB_FILENAME = os.environ.get("BDB_DB_FILENAME", './db')


def get_graph(bdb_db_filename=None, cachesize=1, mode='c'):
    logger.info("Loading graph with %s storage." % (STORAGE))

    if STORAGE == "berkeleydb":

        if bdb_db_filename is None:
            bdb_db_filename = BDB_DB_FILENAME
        logger.info("Using Berkeley DB - %s" % (bdb_db_filename))

        GRAPH = Graph(storage={'berkeleydb': {'filename': bdb_db_filename, 'cachesize': cachesize, 'mode': mode}},
                      bloom_filter_size=BFSIZE, num_hashes=NUM_HASHES)
    else:
        GRAPH = Graph(storage={'redis-cluster': {"conn": CONN_CONFIG,
                                                 "credis": CREDIS}},
                      bloom_filter_size=BFSIZE, num_hashes=NUM_HASHES)
    return GRAPH


def extract_kmers_from_ctx(ctx):
    gr = GraphReader(ctx)
    for i in gr:
        yield i.kmer.canonical_value


@hug.object(name='atlas', version='0.0.1', api=API)
@hug.object.urls('/', requires=())
class bfg(object):

    @hug.object.cli
    @hug.object.post('/insert', output_format=hug.output_format.json)
    def insert(self, bloom_filter):
        """Inserts a bloom filter into the graph

        e.g. bfg insert ERR1010211.bloom

        """
        graph = get_graph()
        result = insert(bloom_filter, async=CELERY)
        graph.sync()
        return {"result": result, 'took':
                float(hug_timer)}

    @hug.object.cli
    @hug.object.post('/bloom')
    def bloom(self, outfile, kmers=None, seqfile=None, ctx=None):
        """Creates a bloom filter from a sequence file or cortex graph. (fastq,fasta,bam,ctx)

        e.g. bfg insert ERR1010211.ctx

        """
        if ctx:
            kmers = extract_kmers_from_ctx(ctx)
        if not kmers and not seqfile:
            return "--kmers or --seqfile must be provided"
        bf = bloom(outfile=outfile, kmers=kmers,
                   seqfile=seqfile, bloom_filter_size=BFSIZE, num_hashes=NUM_HASHES)

    @hug.object.cli
    @hug.object.post('/build', output_format=hug.output_format.json)
    def build(self, outfile: hug.types.text, bloomfilters: hug.types.multiple, samples: hug.types.multiple = []):
        if samples:
            assert len(samples) == len(bloomfilters)
        else:
            samples = bloomfilters
        return build(bloomfilter_filepaths=bloomfilters, samples=samples, graph=get_graph(bdb_db_filename=outfile))

    @hug.object.cli
    @hug.object.post('/merge')
    def merge(self, build_results: hug.types.multiple, indexes: hug.types.multiple = []):
        sizes = []
        uncompressed_graphs = []
        cols_list = []
        for build_result in build_results:
            with open(build_result, 'r') as inf:
                metadata = json.load(inf)
                sizes.append(metadata.get('shape'))
                uncompressed_graphs.append(metadata.get('uncompressed_graphs'))
                cols_list.append(metadata.get('cols'))
                if not indexes:
                    indexes = list(
                        metadata.get('uncompressed_graphs').keys())
        indexes = [int(i) for i in indexes]
        return json.dumps(merge(graph=get_graph(), uncompressed_graphs=uncompressed_graphs,
                                indexes=indexes,
                                cols_list=cols_list))

    @hug.object.cli
    @hug.object.get('/search', examples="seq=ACACAAACCATGGCCGGACGCAGCTTTCTGA",
                    output_format=hug.output_format.json)
    def search(self, db: hug.types.text=None, seq: hug.types.text=None, seqfile: hug.types.text=None,
               threshold: hug.types.float_number=1.0,
               output_format: hug.types.one_of(("json", "tsv", "fasta"))='json',
               pipe_out: hug.types.smart_boolean=False,
               pipe_in: hug.types.smart_boolean=False,
               cachesize: hug.types.number=4):
        """Returns samples that contain the searched sequence.
        Use -f to search for sequence from fasta"""
        if output_format in ["tsv", "fasta"]:
            pipe_out = True

        if not pipe_in and (not seq and not seqfile):
            return "-s or -f must be provided"
        if seq == "-" or pipe_in:
            _, fp = tempfile.mkstemp(text=True)
            with open(fp, 'w') as openfile:
                for line in sys.stdin:
                    openfile.write(line)
            result = search(
                seq=None, fasta_file=fp, threshold=threshold, graph=get_graph(bdb_db_filename=db, cachesize=cachesize, mode='r'), output_format=output_format, pipe=pipe_out)

        else:
            result = search(seq=seq,
                            fasta_file=seqfile, threshold=threshold, graph=get_graph(bdb_db_filename=db, cachesize=cachesize, mode='r'), output_format=output_format, pipe=pipe_out)

        if not pipe_out:
            return result

    @hug.object.cli
    @hug.object.delete('/', output_format=hug.output_format.json)
    def delete(self, db: hug.types.text=None):
        return delete(graph=get_graph(bdb_db_filename=db))

    @hug.object.cli
    @hug.object.get('/graph', output_format=hug.output_format.json)
    def stats(self):
        return stats(graph=get_graph())

    @hug.object.cli
    @hug.object.get('/samples', output_format=hug.output_format.json)
    def samples(self, sample_name: hug.types.text=None, db: hug.types.text=None, delete: hug.types.smart_boolean=False):
        return samples(sample_name, graph=get_graph(bdb_db_filename=db), delete=delete)

    @hug.object.cli
    @hug.object.post('/dump', output_format=hug.output_format.json)
    def dump(self, filepath):
        r = dump(graph=get_graph(), file=filepath)
        return r

    @hug.object.cli
    @hug.object.post('/load', output_format=hug.output_format.json)
    def load(self, filepath):
        r = load(graph=get_graph(), file=filepath)
        return r


def main():
    API.cli()

if __name__ == "__main__":
    main()