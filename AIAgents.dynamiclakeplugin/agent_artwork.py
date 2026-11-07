"""Small data-backed ring charts. Logos remain native image components above them."""
from functools import lru_cache
import math
import struct
import zlib

PALETTE={'claude':(240,157,99),'codex':(87,159,252),'opencode':(100,181,255)}


@lru_cache(maxsize=128)
def quota_ring(provider, remaining):
    """RGBA PNG, supersampled edges and round caps; None is an empty neutral track."""
    color=PALETTE[provider]
    size=192
    center=size/2
    radius=82
    thickness=6
    ratio=None if remaining is None else min(100,max(0,remaining))/100
    end=(ratio or 0)*2*math.pi
    endpoints=[(center+radius*math.sin(a),center-radius*math.cos(a)) for a in (0,end)]
    rows=[]
    for y in range(size):
        row=bytearray([0])
        for x in range(size):
            dist=math.hypot(x+.5-center,y+.5-center)
            alpha=max(0,min(1,thickness+.5-abs(dist-radius)))
            angle=math.atan2(x+.5-center,center-y-.5)%(2*math.pi)
            fill=ratio is not None and ratio>0 and (angle<=end or any(math.hypot(x+.5-a,y+.5-b)<thickness for a,b in endpoints))
            opacity=255 if fill else (45 if ratio is not None else 36)
            row.extend((*color,round(alpha*opacity)) if alpha else (0,0,0,0))
        rows.append(row)
    def chunk(kind,data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',size,size,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(b''.join(rows),6))+chunk(b'IEND',b'')
