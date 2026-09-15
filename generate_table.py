#!/usr/bin/env python3
"""
Merge the three grepped energies.txt files (orig, ip, opt subfolders) into
one table: id, orig_energy, ip_energy, opt_energy.

Each input line looks like:
    13gs_ligand.out:Total Energy = -80.64459028483240388        (orig)
    13gs_ligand_ip.out:Total Energy = -80.64459028483240388     (ip)
    13gs_ligand_opt.out:Total Energy = -80.64459028483240388    (opt)

The ligand id is recovered by stripping the subfolder-specific filename
suffix (_ligand.out / _ligand_ip.out / _ligand_opt.out).

Usage:
    python merge_energies.py orig_energies.txt ip_energies.txt opt_energies.txt -o merged_energies.txt

Output columns: id, orig_energy, ip_energy, opt_energy, flag
Delimiter defaults to tab; use --delimiter comma or --delimiter semicolon
for a .csv-style file instead.
An id missing from one or more of the three tables is still included, with
'NA' in the missing column(s) and a flag noting which table(s) it's missing
from -- nothing is silently dropped. A companion <output>.report.txt lists
counts, duplicate ids within a single table (all their values, unresolved),
and every incomplete id.
"""
import argparse
import re
import sys
from collections import defaultdict

LINE_RE = re.compile(r'^(?P<fname>\S+):\s*Total Energy\s*=\s*(?P<value>[-+]?\d+\.?\d*(?:[eE][-+]?\d+)?)\s*$')

# (subfolder label, filename suffix to strip to recover the ligand id)
KINDS = [
    ('orig', '_ligand.out'),
    ('ip', '_ligand_ip.out'),
    ('opt', '_ligand_opt.out'),
]


def load_energies(path, suffix):
    """Parse a grepped energies.txt. Returns (data, bad_lines).

    data: dict id -> list of float values (list, to preserve/detect duplicates)
    bad_lines: list of (line_number, raw_line) that didn't parse
    """
    data = defaultdict(list)
    bad_lines = []
    with open(path, encoding='utf-8') as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.rstrip('\n').rstrip('\r')
            if not line.strip():
                continue
            m = LINE_RE.match(line)
            if not m:
                bad_lines.append((lineno, line))
                continue
            fname = m.group('fname')
            if not fname.endswith(suffix):
                bad_lines.append((lineno, line))
                continue
            ligand_id = fname[: -len(suffix)]
            try:
                value = float(m.group('value'))
            except ValueError:
                bad_lines.append((lineno, line))
                continue
            data[ligand_id].append(value)
    return data, bad_lines


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('orig_file', help='energies.txt grepped from paris-main-MISATO-xyz_orig')
    ap.add_argument('ip_file', help='energies.txt grepped from paris-main-MISATO-xyz_ip')
    ap.add_argument('opt_file', help='energies.txt grepped from paris-main-MISATO-xyz_opt')
    ap.add_argument('-o', '--output', default='merged_energies.txt')
    ap.add_argument('--delimiter', choices=['tab', 'comma', 'semicolon'], default='tab',
                     help='output column separator (default: tab)')
    args = ap.parse_args()

    delim = {'tab': '\t', 'comma': ',', 'semicolon': ';'}[args.delimiter]

    paths = [args.orig_file, args.ip_file, args.opt_file]
    tables = {}
    bad_lines_by_kind = {}
    for (kind, suffix), path in zip(KINDS, paths):
        data, bad_lines = load_energies(path, suffix)
        tables[kind] = data
        bad_lines_by_kind[kind] = bad_lines

    all_ids = sorted(set().union(*(t.keys() for t in tables.values())))

    dupes = {kind: {k: v for k, v in t.items() if len(v) > 1} for kind, t in tables.items()}

    rows = []          # (id, orig, ip, opt, flag_text) -- for the output table
    missing_by_kind = {kind: [] for kind, _ in KINDS}
    dup_by_kind = {kind: [] for kind, _ in KINDS}
    for ligand_id in all_ids:
        vals = {}
        missing = []
        dup_here = []
        for kind, _suffix in KINDS:
            v = tables[kind].get(ligand_id)
            if v is None:
                vals[kind] = 'NA'
                missing.append(kind)
                missing_by_kind[kind].append(ligand_id)
            elif len(v) == 1:
                vals[kind] = v[0]
            else:
                vals[kind] = v[0]  # first value used in the main row; full list in report
                dup_here.append(kind)
                dup_by_kind[kind].append(ligand_id)

        flags = []
        if missing:
            flags.append('MISSING_' + '_'.join(missing).upper())
        if dup_here:
            flags.append('DUPLICATE_' + '_'.join(dup_here).upper())

        # '|' (not ';') joins multiple flags on one row, so a semicolon-delimited
        # output file never confuses a flag separator with a column separator.
        rows.append((ligand_id, vals['orig'], vals['ip'], vals['opt'], '|'.join(flags)))

    with open(args.output, 'w', newline='') as f:
        f.write(delim.join(['id', 'orig_energy', 'ip_energy', 'opt_energy', 'flag']) + '\n')
        for row in rows:
            f.write(delim.join(str(v) for v in row) + '\n')

    report_path = args.output.rsplit('.', 1)[0] + '.report.txt'
    with open(report_path, 'w') as f:
        for kind, _suffix in KINDS:
            f.write(f"{kind}: {sum(len(v) for v in tables[kind].values())} entries, "
                    f"{len(tables[kind])} unique ids, {len(bad_lines_by_kind[kind])} unparsable lines\n")
        f.write(f"\nTotal distinct ligand ids across all 3 tables: {len(all_ids)}\n")

        complete = sum(1 for r in rows if not r[4])
        f.write(f"Complete rows (present in all 3, no duplicates): {complete}\n")
        f.write(f"Incomplete/flagged rows: {len(rows) - complete}\n\n")

        for kind, _suffix in KINDS:
            missing_here = missing_by_kind[kind]
            f.write(f"--- Missing from {kind} ({len(missing_here)}) ---\n")
            f.write("\n".join(missing_here))
            f.write("\n\n")

        for kind, _suffix in KINDS:
            f.write(f"--- Duplicate ids within {kind} table ({len(dupes[kind])}) ---\n")
            for k, v in dupes[kind].items():
                f.write(f"{k}: {v}\n")
            f.write("\n")

        for kind, _suffix in KINDS:
            bad = bad_lines_by_kind[kind]
            if bad:
                f.write(f"--- Unparsable lines ({kind}) ---\n")
                for ln, txt in bad:
                    f.write(f"line {ln}: {txt!r}\n")
                f.write("\n")

    print(f"Wrote {len(rows)} rows to {args.output}")
    print(f"Report written to {report_path}")


if __name__ == '__main__':
    main()