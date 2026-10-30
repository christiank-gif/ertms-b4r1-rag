"""Extract variables, packets and messages from SUBSET-026 chapter texts (ch7, ch8)."""
import re, json, sys

SPEC = "/workspace/specs"
HEADER_RE = re.compile(r'^(ERA \* UNISIG|===== PAGE|SUBSET-026|4\.0\.0|05/07/2023|System Requirements|Chapter \d|ERTMS/ETCS$|Page \d+/\d+|Management of older|ERTMS/ETCS language$|Messages$)')

def clean(lines):
    return [l.strip() for l in lines if l.strip() and not HEADER_RE.match(l.strip())]

def extract_variables(ch7):
    pat = re.compile(r'^7\.5\.\d+\.\d+(?:\.\d+)?\s+([A-Z0-9_()]+)\s*$', re.M)
    variables = {}
    for m in pat.finditer(ch7):
        name = m.group(1).replace('(k)', '').strip()
        seg = ch7[m.end():]
        nxt = re.search(r'\n7\.5\.\d+\.\d+', seg)
        if nxt: seg = seg[:nxt.start()]
        lines = clean(seg.splitlines())
        length = minv = maxv = res = special = None
        for i, l in enumerate(lines):
            if l == 'Resolution/formula':
                vals = lines[i+1:i+5]
                if len(vals) >= 4:
                    length, minv, maxv, res = vals[0], vals[1], vals[2], vals[3]
                elif len(vals) == 3:
                    length, minv, maxv = vals
                break
        if length is not None and 'bits' not in str(length):
            # maybe fields not in block order; fallback: first line containing 'bits'
            for l in lines:
                bm = re.match(r'(\d+)\s*bits?', l)
                if bm and length is None:
                    length = l; break
        lm = re.search(r'(\d+)\s*bits?', str(length))
        variables[name] = {
            "name": name,
            "length_bits": int(lm.group(1)) if lm else None,
            "min": minv, "max": maxv, "resolution": res, "special": special,
        }
    return variables

def extract_packets(ch7):
    pat = re.compile(r'Packet Number (\d+):\s*(.+)', re.M)
    pkts = {}
    for m in pat.finditer(ch7):
        num = int(m.group(1))
        if num not in pkts:
            pkts[num] = {"number": num, "name": m.group(2).strip()}
    return pkts

def extract_messages(ch8):
    pat = re.compile(r'Message (\d+):\s*(.+)', re.M)
    msgs = {}
    for m in pat.finditer(ch8):
        num = int(m.group(1))
        if num not in msgs:
            msgs[num] = {"id": num, "title": m.group(2).strip()}
    return msgs

if __name__ == "__main__":
    ch7 = open(f"{SPEC}/ch7.txt").read()
    ch8 = open(f"{SPEC}/ch8.txt").read()
    out = {
        "variables": extract_variables(ch7),
        "packets": {str(k): v for k, v in sorted(extract_packets(ch7).items())},
        "messages": {str(k): v for k, v in sorted(extract_messages(ch8).items())},
    }
    with open(sys.argv[1], "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    nov = [k for k, v in out['variables'].items() if v['length_bits'] is None]
    print("variables:", len(out['variables']), "without length:", len(nov), nov[:15])
    print("packets:", len(out['packets']), "messages:", len(out['messages']))
