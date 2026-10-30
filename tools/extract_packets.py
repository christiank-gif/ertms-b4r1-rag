"""Parse packet content tables from SUBSET-026-7 sections 7.4.2.x / 7.4.3.x."""
import re, json, sys

SPEC = "/workspace/specs"
HEADER_RE = re.compile(r'^(ERA \* UNISIG|===== PAGE|SUBSET-026|4\.0\.0|05/07/2023|System Requirements|Chapter \d|ERTMS/ETCS$|Page \d+/\d+|ERTMS/ETCS language$|Messages$|PACKETS.*$|TRACK TO TRAIN|TRAIN TO TRACK|Intentionally deleted$)')

def clean(lines):
    return [l.strip() for l in lines if l.strip() and not HEADER_RE.match(l.strip())]

def parse_packet_fields(ch7, start, end):
    seg = ch7[start:end]
    lines = clean(seg.splitlines())
    # locate 'Content' then 'Variable','Length','Comment'
    try:
        ci = lines.index('Content')
    except ValueError:
        return []
    body = lines[ci+1:]
    # skip header row
    while body and body[0] in ('Variable','Length','Comment'):
        body = body[1:]
    fields = []
    var_re = re.compile(r'^([A-Z0-9_]+)(\((k|\d+)\))?$')
    i = 0
    while i < len(body):
        m = var_re.match(body[i])
        if m and i+1 < len(body) and re.match(r'^\d+$', body[i+1]):
            name, rep = m.group(1), m.group(2)
            length = int(body[i+1])
            comments = []
            j = i+2
            while j < len(body) and not var_re.match(body[j]):
                comments.append(body[j]); j += 1
            fields.append({"name": name, "repeat": bool(rep), "length_bits": length,
                           "comment": ' '.join(comments)})
            i = j
        else:
            i += 1
    return fields

def extract(ch7):
    pat = re.compile(r'Packet Number (\d+):\s*(.+?)\s*$', re.M)
    pkts = {}
    matches = list(pat.finditer(ch7))
    for idx, m in enumerate(matches):
        pnum, title = int(m.group(1)), m.group(2).strip()
        end = matches[idx+1].start() if idx+1 < len(matches) else len(ch7)
        fields = parse_packet_fields(ch7, m.end(), end)
        # direction from the enclosing section 7.4.2 (t2t) vs 7.4.3 (train)
        sec_pos = m.start()
        s2 = ch7.rfind('7.4.2', 0, sec_pos)
        s3 = ch7.rfind('7.4.3', 0, sec_pos)
        direction = 'track_to_train' if s2 > s3 else 'train_to_track'
        key = str(pnum)
        if key in pkts:
            key = f"{pnum}#{direction}"
        pkts[key] = {"number": pnum, "name": title,
                     "direction": direction, "fields": fields}
    return pkts

if __name__ == "__main__":
    ch7 = open(f"{SPEC}/ch7.txt").read()
    pkts = extract(ch7)
    out = {str(k): v for k, v in sorted(pkts.items(), key=lambda kv: str(kv[0]))}
    with open(sys.argv[1], "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    nofields = [k for k,v in out.items() if not v['fields']]
    print("packets:", len(out), "without fields:", len(nofields), nofields[:20])
    for k in ["15","0","42","11","2#train_to_track","255","136","3"]:
        if k in out:
            print(k, out[k]['name'], '->', [(f['name'], f['length_bits'], f['repeat']) for f in out[k]['fields']])
