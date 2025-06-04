#!/usr/bin/env python3

import sys
import struct
from enum import IntEnum

MAX_BLK = 1024 * 100

class EOPERATION(IntEnum):
    COPY = 0
    INSERT = 1
    NU_OP = 2

class FileInfo:
    def __init__(self, f):
        self.f = f
        self.read_pos = 0
        f.seek(0, 2)
        self.total_size = f.tell()
        f.seek(0)

class CopyData:
    def __init__(self, orig_pos, size):
        self.u32OrigFilePos = orig_pos
        self.u32Size = size

class InsertData:
    def __init__(self, final_pos, data):
        self.u32FinalFilePos = final_pos
        self.u32Size = len(data)
        self.pBlock = data

class FileBlock:
    def __init__(self, prev=None):
        self.eType = EOPERATION.NU_OP
        self.pData = None
        self.pNextFileBlock = None
        self.pPrevFileBlock = prev
        if prev:
            prev.pNextFileBlock = self

def new_file_block(prev):
    return FileBlock(prev)

def make_insert_block(psFb, buffer, startpos, sz):
    p = new_file_block(psFb)
    p.eType = EOPERATION.INSERT
    pdata = InsertData(startpos, buffer[:sz])
    p.pData = pdata
    return p

def make_copy_block(psFb, startpos, sz):
    p = new_file_block(psFb)
    p.eType = EOPERATION.COPY
    p.pData = CopyData(startpos, sz)
    return p

def print_tracker_file_blocks(blocks, fout):
    while blocks and blocks.pPrevFileBlock:
        blocks = blocks.pPrevFileBlock
    i = 0
    while blocks:
        if blocks.eType == EOPERATION.COPY:
            d = blocks.pData
            fout.write(struct.pack('<I', blocks.eType))
            fout.write(struct.pack('<I', d.u32OrigFilePos))
            fout.write(struct.pack('<I', d.u32Size))
            print(f"OP[{i}]: COPY")
        elif blocks.eType == EOPERATION.INSERT:
            d = blocks.pData
            fout.write(struct.pack('<I', blocks.eType))
            fout.write(struct.pack('<I', d.u32FinalFilePos))
            fout.write(struct.pack('<I', d.u32Size))
            fout.write(d.pBlock)
            print(f"OP[{i}]: INSERT")
        blocks = blocks.pNextFileBlock
        i += 1

def find_matches(args):
    last_pos = 0
    sEnd = args['sEnd']
    sOrigin = args['sOrigin']
    pBufOrig = args['pBufferOriginal']
    pBufFinal = args['pBufferFinal']
    psFb = None
    u32Total = 0
    idxFinalFile = 0

    while idxFinalFile < sEnd.total_size:
        idxFinalMem = 0
        idxOrigCmpMem = 0
        zm = 0
        for idxOrigCmpFile in range(0, sOrigin.total_size, 4):
            for z in range(4, MAX_BLK, 4):
                if idxOrigCmpFile + z > sOrigin.total_size or idxFinalFile + z > sEnd.total_size:
                    continue
                if pBufOrig[idxOrigCmpFile:idxOrigCmpFile+z] != pBufFinal[idxFinalFile:idxFinalFile+z]:
                    break
                if z > zm:
                    idxFinalMem = idxFinalFile
                    idxOrigCmpMem = idxOrigCmpFile
                    zm = z
        if zm > 0:
            if zm > 16:
                if psFb is None:
                    last_pos = 0
                if last_pos != idxFinalMem:
                    psFb = make_insert_block(psFb, pBufFinal[last_pos:idxFinalMem], last_pos, idxFinalMem - last_pos)
                psFb = make_copy_block(psFb, idxOrigCmpMem, zm)
                u32Total += zm
                last_pos = idxFinalFile + zm
            idxFinalFile += zm
        else:
            idxFinalFile += 4

    if psFb and isinstance(psFb.pData, CopyData):
        pc = psFb.pData
        end_pos = pc.u32OrigFilePos + pc.u32Size
        if end_pos < sEnd.total_size:
            psFb = make_insert_block(psFb, pBufFinal[end_pos:], end_pos, sEnd.total_size - end_pos)

    ratio = 1.0 - float(u32Total) / float(sEnd.total_size)
    print(f"Total: {sEnd.total_size} , igual: {u32Total}, ratio: {ratio} ")

    print_tracker_file_blocks(psFb, args['out'])


def main():
    if len(sys.argv) < 4:
        print(f"Falta de parametros {sys.argv[0]} <old file> <new file> <delta file>")
        sys.exit(1)

    with open(sys.argv[1], 'rb') as hOrig, open(sys.argv[2], 'rb') as hNew, open(sys.argv[3], 'wb') as hPatch:
        sOriginalFile = FileInfo(hOrig)
        sEndFile = FileInfo(hNew)

        pBufferOriginal = hOrig.read()
        pBufferFinal = hNew.read()

        args = {
            'sEnd': sEndFile,
            'sOrigin': sOriginalFile,
            'pBufferOriginal': pBufferOriginal,
            'pBufferFinal': pBufferFinal,
            'out': hPatch
        }

        find_matches(args)

if __name__ == '__main__':
    main()

