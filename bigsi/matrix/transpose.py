from bitarray import bitarray
import copy
import logging
logger = logging.getLogger(__name__)
from bigsi.utils import DEFAULT_LOGGING_LEVEL
logger.setLevel(DEFAULT_LOGGING_LEVEL)
import numpy as np
logger = logging.getLogger(__name__)

def transpose_low_mem(bitarrays):
    logger.info("Using slow, low memory transpose")
        # Takes a list of bitarrays and returns the transpose as a list of
        # bitarrays
    x = len(bitarrays)
    y = bitarrays[0].length()
    logger.info("BFM dims %i %i" % (x, y))

    tbitarrays = []
    for ii in range(y):
        tbitarrays.append(bitarray('0'*x))
    for i in range(x):
        for j in range(y):
            tbitarrays[j][i] = bitarrays[i][j]
    return tbitarrays


def transpose_numpy_old(bitarrays):
    logger.info("Using high memory transpose")

    # Takes a list of bitarrays and returns the transpose as a list of
    # bitarrays
    X = np.array(bitarrays).transpose()
    tbitarrays=[bitarray(i.tolist()) for i in X]  
    return tbitarrays
    
def transpose_numpy(bitarrays):
    # Takes a list of bitarrays and returns the transpose as a list of
    # bitarrays
    
    X=np.array([np.frombuffer(ba.unpack(),dtype=bool) for ba in bitarrays],dtype=bool)
    for row in X.T:
        ba=bitarray()
        ba.pack(row.tobytes())         
        yield ba

def transpose(bitarrays, lowmem=False):
    if lowmem:
        return transpose_low_mem(bitarrays)
    else:
        return transpose_numpy(bitarrays)
