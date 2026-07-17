#!/usr/bin/env python3
"""
COG Header Analyzer — no GDAL required.

Parses TIFF/BigTIFF binary structure to measure header size, report IFD layout,
and identify the drivers of header byte consumption.

CDSE Sentinel Hub BYOC requires COG header < 1 MB.  The header consists of all
IFD metadata (tags, geo keys, ColorMap/LUTs) plus the TileOffsets and
TileByteCounts (or StripOffsets/StripByteCounts) arrays across all IFDs (main
+ overviews).  ColourInterpretation / PhotometricInterpretation are stored
inline in the IFD and do not add measurable header bytes for single-band
rasters.  Palette-based rasters include a ColorMap tag (tag 320) stored out-
of-line, which is correctly captured in the header extent.

Output:
  - File size, format (Classic vs BigTIFF), byte order
  - Header bytes (and % of file)
  - Gap between header end and first tile/strip offset
  - Per-IFD breakdown: dimensions, tile size, compression, tile/pointer count
  - Table mode for multiple files (sorted by filename)

Usage:
  python3 cog_header.py file1.tif file2.tif ...
  python3 cog_header.py /path/to/dir/*.tif
  python3 cog_header.py .                    # finds all .tif in CWD
"""

# © European Union, 2025
# Licensed under the EUPL, Version 1.2 or later (the "Licence").
# You may not use this work except in compliance with the Licence.
# You may obtain a copy of the Licence at:
#   https://joinup.ec.europa.eu/collection/eupl/eupl-text-eupl-12
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the Licence is distributed on an "AS IS" basis,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.  See the Licence for the specific language governing
# permissions and limitations under the Licence.

import struct
import os
import sys
from pathlib import Path

TAG_NAMES = {
    256: 'ImageWidth', 257: 'ImageLength', 258: 'BitsPerSample',
    259: 'Compression', 262: 'Photometric', 273: 'StripOffsets',
    277: 'SamplesPerPixel', 278: 'RowsPerStrip', 279: 'StripByteCounts',
    282: 'XResolution', 283: 'YResolution', 284: 'PlanarConfig',
    296: 'ResolutionUnit', 322: 'TileWidth', 323: 'TileLength',
    324: 'TileOffsets', 325: 'TileByteCounts', 339: 'SampleFormat',
    33550: 'ModelPixelScale', 33922: 'ModelTiepoint',
    34735: 'GeoKeyDirectory', 42112: 'GDAL_METADATA',
}
TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2,
              9: 4, 10: 8, 11: 4, 12: 8, 13: 4, 16: 8}
TYPE_FMTS = {3: 'H', 4: 'I', 5: 'I'}
COMPRESSION = {1: 'None', 5: 'LZW', 7: 'JPEG', 8: 'DEFLATE',
               32946: 'DEFLATE', 34712: 'JPEG2000', 50001: 'ZSTD',
               50002: 'ZLIB'}


def analyze(fp):
    with open(fp, 'rb') as f:
        fsize = f.seek(0, 2)
        f.seek(0)
        bo = f.read(2)
        if bo == b'II':
            endian = '<'
        elif bo == b'MM':
            endian = '>'
        else:
            return None  # not TIFF

        magic = struct.unpack(endian + 'H', f.read(2))[0]
        if magic == 42:
            bigtiff, off_sz, off_fmt, cnt_fmt, tag_sz = False, 4, endian + 'I', endian + 'H', 12
        elif magic == 43:
            bigtiff, off_sz, off_fmt, cnt_fmt, tag_sz = True, 8, endian + 'Q', endian + 'Q', 20
            f.read(4)  # offset_size (8) + always-zero
        else:
            return None

        ifd_off = struct.unpack(off_fmt, f.read(off_sz))[0]

    # Walk IFDs
    seen = set()
    ifds = []
    max_ext = 0
    first_tile_offset = None
    idx = 0

    with open(fp, 'rb') as f:
        while ifd_off and ifd_off not in seen:
            seen.add(ifd_off)
            f.seek(ifd_off)
            ntags = struct.unpack(cnt_fmt, f.read(struct.calcsize(cnt_fmt)))[0]
            tags_start = f.tell()
            ifd_struct_end = tags_start + ntags * tag_sz + off_sz
            this_ext = ifd_struct_end

            info = {'ntags': ntags, 'tags': {}, 'offset': ifd_off}
            w = h = tw = tl = comp = None

            for i in range(ntags):
                f.seek(tags_start + i * tag_sz)
                tid = struct.unpack(endian + 'H', f.read(2))[0]
                ttype = struct.unpack(endian + 'H', f.read(2))[0]
                ts = TYPE_SIZES.get(ttype, 1)
                tcnt = struct.unpack(endian + ('Q' if bigtiff else 'I'),
                                     f.read(8 if bigtiff else 4))[0]
                vp = f.tell()
                total = tcnt * ts
                name = TAG_NAMES.get(tid, f'T{tid}')

                if total <= off_sz:
                    fmt_char = TYPE_FMTS.get(ttype)
                    if fmt_char and tid in (256, 257, 259, 322, 323):
                        f.seek(vp)
                        val = struct.unpack(endian + fmt_char * tcnt, f.read(total))[0]
                        if tid == 256: w = val
                        elif tid == 257: h = val
                        elif tid == 259: comp = val
                        elif tid == 322: tw = val
                        elif tid == 323: tl = val
                else:
                    data_off = struct.unpack(off_fmt, f.read(off_sz))[0]
                    this_ext = max(this_ext, data_off + total)
                    if name in ('TileOffsets', 'StripOffsets'):
                        f.seek(data_off)
                        ft = struct.unpack(off_fmt, f.read(off_sz))[0]
                        if first_tile_offset is None or ft < first_tile_offset:
                            first_tile_offset = ft
                        info['first_data_off'] = ft
                        info['n_tiles'] = tcnt

            max_ext = max(max_ext, this_ext)
            if w and h:
                info['dims'] = (w, h)
                info['tiles'] = (tw, tl) if tw and tl else None
                info['compression'] = COMPRESSION.get(comp, f'0x{comp:x}' if comp else '?')
                info['label'] = 'MAIN' if idx == 0 else f'OVR{idx}'
            ifds.append(info)

            f.seek(tags_start + ntags * tag_sz)
            ifd_off = struct.unpack(off_fmt, f.read(off_sz))[0]
            idx += 1

    return {
        'filepath': fp,
        'filename': os.path.basename(fp),
        'fsize': fsize,
        'endian': 'LE' if endian == '<' else 'BE',
        'format': 'BigTIFF' if bigtiff else 'Classic',
        'n_ifds': len(ifds),
        'header_bytes': max_ext,
        'first_tile': first_tile_offset,
        'ifds': ifds,
    }


def format_size(n):
    if n >= 1024**3:
        return f'{n/1024**3:.2f} GB'
    if n >= 1024**2:
        return f'{n/1024**2:.1f} MB'
    if n >= 1024:
        return f'{n/1024:.0f} KB'
    return f'{n} B'


def print_summary(r):
    print(f"File:        {r['filename']}")
    print(f"Size:        {format_size(r['fsize'])} ({r['fsize']:,} bytes)")
    print(f"Format:      {r['format']} ({r['endian']})")
    print(f"IFDs:        {r['n_ifds']} ({r['ifds'][0]['label']} + {r['n_ifds'] - 1} overviews)")
    print(f"Header:      {format_size(r['header_bytes'])} ({r['header_bytes']:,} bytes)")
    print(f"             {r['header_bytes']/r['fsize']*100:.4f}% of file")
    if r['first_tile']:
        print(f"First tile:  offset {r['first_tile']:,}  "
              f"(gap after header: {r['first_tile'] - r['header_bytes']:,} bytes)")
    print()

    for ifd in r['ifds']:
        dims = ifd.get('dims')
        tiles = ifd.get('tiles')
        label = ifd.get('label', f'IFD{ifd["index"]}' if 'index' in ifd else '?')
        comp = ifd.get('compression', '?')
        nt = ifd.get('n_tiles', '?')

        dim_str = f'{dims[0]}×{dims[1]}' if dims else '?'
        tile_str = f', tiles {tiles[0]}×{tiles[1]}' if tiles else ''
        print(f"  [{label:4s}] {dim_str:>16s}{tile_str:<20s} "
              f"compr: {comp:<8s}  [{nt} tile ptrs]")


def print_table_header():
    print(f"{'File':<55s} {'Size':>8s} {'Header':>8s} {'%':>6s} {'IFDs':>4s} "
          f"{'Format':>8s}  {'Compression':>10s}  {'Dimensions':>16s}")
    print('-' * 135)


def print_table_row(r):
    name = r['filename'][:54]
    sz = format_size(r['fsize']).replace(' ', '')
    hdr = format_size(r['header_bytes']).replace(' ', '')
    pct = f"{r['header_bytes']/r['fsize']*100:.4f}"
    main = r['ifds'][0] if r['ifds'] else {}
    comp = main.get('compression', '?')
    dims = f"{main['dims'][0]}×{main['dims'][1]}" if main.get('dims') else '?'
    print(f"{name:<55s} {sz:>8s} {hdr:>8s} {pct:>6s}% {r['n_ifds']:>4d} "
          f"{r['format']:>8s}  {comp:>10s}  {dims:>16s}")


def collect_files(args):
    """Expand args to a list of .tif/.tiff files."""
    files = []
    for arg in args:
        p = Path(arg)
        if p.is_file():
            files.append(str(p))
        elif p.is_dir():
            for ext in ('*.tif', '*.tiff'):
                files.extend(str(x) for x in sorted(p.rglob(ext)))
        else:
            expanded = sorted(Path().glob(arg))
            for ep in expanded:
                if ep.is_file():
                    files.append(str(ep))
    return files


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <file.tif> [file2.tif ...] [directory/] [glob]")
        sys.exit(1)

    files = collect_files(sys.argv[1:])
    if not files:
        print("No .tif/.tiff files found.")
        sys.exit(1)

    results = []
    for fp in files:
        r = analyze(fp)
        if r:
            results.append(r)
        else:
            print(f"SKIP: {fp} (not a valid TIFF)", file=sys.stderr)

    if len(results) == 1:
        print_summary(results[0])
    else:
        print_table_header()
        for r in results:
            print_table_row(r)

        print()
        headers = [r['header_bytes'] for r in results]
        print(f"Summary: {len(results)} files  |  "
              f"Header range: {format_size(min(headers))} – {format_size(max(headers))}  |  "
              f"Mean: {format_size(sum(headers)//len(results))}")


if __name__ == '__main__':
    main()