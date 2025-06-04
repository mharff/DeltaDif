#!/usr/bin/env python3
"""Generate a delta file describing the differences between two binaries."""

from __future__ import annotations

import struct
import sys
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional, BinaryIO


MAX_BLK = 1024 * 100  # Maximum block inspected when searching for matches


class EOPERATION(IntEnum):
    """Operations supported in the delta format."""

    COPY = 0
    INSERT = 1
    NU_OP = 2


@dataclass
class FileInfo:
    """Store information about an opened file."""

    f: BinaryIO
    total_size: int = field(init=False)

    def __post_init__(self) -> None:
        self.f.seek(0, 2)
        self.total_size = self.f.tell()
        self.f.seek(0)


@dataclass
class CopyData:
    """Describe a segment that should be copied from the origin file."""

    u32OrigFilePos: int
    u32Size: int


@dataclass
class InsertData:
    """Describe raw data to be inserted in the resulting file."""

    u32FinalFilePos: int
    pBlock: bytes

    @property
    def u32Size(self) -> int:
        return len(self.pBlock)


@dataclass
class FileBlock:
    """Node used to build the list of delta operations."""

    eType: EOPERATION = EOPERATION.NU_OP
    pData: Optional[object] = None
    pPrevFileBlock: Optional[FileBlock] = None
    pNextFileBlock: Optional[FileBlock] = None


def new_file_block(prev: Optional[FileBlock]) -> FileBlock:
    """Allocate a new ``FileBlock`` linked to ``prev``."""

    fb = FileBlock(pPrevFileBlock=prev)
    if prev is not None:
        prev.pNextFileBlock = fb
    return fb


def make_insert_block(psFb: Optional[FileBlock], buffer: bytes, startpos: int, sz: int) -> FileBlock:
    """Create an ``INSERT`` block with ``sz`` bytes from ``buffer``."""

    block = new_file_block(psFb)
    block.eType = EOPERATION.INSERT
    block.pData = InsertData(startpos, buffer[:sz])
    return block


def make_copy_block(psFb: Optional[FileBlock], startpos: int, sz: int) -> FileBlock:
    """Create a ``COPY`` block referencing ``startpos`` with length ``sz``."""

    block = new_file_block(psFb)
    block.eType = EOPERATION.COPY
    block.pData = CopyData(startpos, sz)
    return block


def print_tracker_file_blocks(blocks: Optional[FileBlock], fout: BinaryIO) -> None:
    """Write the chain of ``blocks`` to ``fout`` in the delta format."""

    # Find the first block
    while blocks and blocks.pPrevFileBlock:
        blocks = blocks.pPrevFileBlock

    finalsize = 0
    idx = 0
    while blocks:
        if blocks.eType == EOPERATION.COPY:
            d: CopyData = blocks.pData  # type: ignore[assignment]
            fout.write(struct.pack("<I", blocks.eType))
            fout.write(struct.pack("<I", d.u32OrigFilePos))
            fout.write(struct.pack("<I", d.u32Size))
            finalsize += d.u32Size
        elif blocks.eType == EOPERATION.INSERT:
            d: InsertData = blocks.pData  # type: ignore[assignment]
            fout.write(struct.pack("<I", blocks.eType))
            fout.write(struct.pack("<I", d.u32FinalFilePos))
            fout.write(struct.pack("<I", d.u32Size))
            fout.write(d.pBlock)
            finalsize += d.u32Size
        blocks = blocks.pNextFileBlock
        idx += 1

    print(f"finalsize: {finalsize}")

def find_matches(
    origin: FileInfo,
    end: FileInfo,
    buf_orig: bytes,
    buf_final: bytes,
    out: BinaryIO,
) -> None:
    """Compare ``buf_orig`` and ``buf_final`` and write delta operations."""

    last_pos = 0
    psFb: Optional[FileBlock] = None  # tail of the operations list
    u32TotalSaved = 0
    u32Total = 0
    idxFinalFile = 0

    while idxFinalFile < end.total_size:
        idxFinalMem = 0  # best match position in final file
        idxOrigCmpMem = 0  # best match position in origin file
        zm = 0  # length of the best match
        for idxOrigCmpFile in range(0, origin.total_size, 4):
            for z in range(4, MAX_BLK, 4):
                if idxOrigCmpFile + z > origin.total_size or idxFinalFile + z > end.total_size:
                    continue
                if buf_orig[idxOrigCmpFile:idxOrigCmpFile+z] != buf_final[idxFinalFile:idxFinalFile+z]:
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
                    psFb = make_insert_block(psFb, buf_final[last_pos:idxFinalMem], last_pos, idxFinalMem - last_pos)
                    u32Total += idxFinalMem - last_pos
                psFb = make_copy_block(psFb, idxOrigCmpMem, zm)
                u32TotalSaved += zm
                u32Total += zm
                last_pos = idxFinalFile + zm
            idxFinalFile += zm
        else:
            idxFinalFile += 4

    if u32Total < end.total_size:
        psFb = make_insert_block(psFb, buf_final[u32Total:], u32Total, end.total_size - u32Total)

    ratio = 1.0 - float(u32TotalSaved) / float(end.total_size)
    print(f"Total: {end.total_size} , igual: {u32TotalSaved}, ratio: {ratio} ")

    # Persist operations to the output file
    if psFb:
        print_tracker_file_blocks(psFb, out)


def main() -> None:
    """Entry point: generate a delta file from two binary inputs."""

    if len(sys.argv) < 4:
        print(f"Falta de parametros {sys.argv[0]} <old file> <new file> <delta file>")
        sys.exit(1)

    # Load both files entirely into memory
    with open(sys.argv[1], "rb") as hOrig, open(sys.argv[2], "rb") as hNew, open(sys.argv[3], "wb") as hPatch:
        sOriginalFile = FileInfo(hOrig)
        sEndFile = FileInfo(hNew)

        pBufferOriginal = hOrig.read()
        pBufferFinal = hNew.read()

        find_matches(sOriginalFile, sEndFile, pBufferOriginal, pBufferFinal, hPatch)

if __name__ == '__main__':
    main()

