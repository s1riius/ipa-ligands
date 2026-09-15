#!/usr/bin/env python3
"""
Run Executable_GFN2.exe over every ligand listed in ligand_file.txt, across
the three MISATO xyz subfolders, in parallel.

Expected layout (relative to --root, default: current directory):
    Executable_GFN2.exe
    ligand_file.txt                -- one shared list, reused for all 3 subfolders
    paris-main-MISATO-xyz_orig/   <ligand>_ligand.xyz
    paris-main-MISATO-xyz_ip/     <ligand>_ligand_ip.xyz
    paris-main-MISATO-xyz_opt/    <ligand>_ligand_opt.xyz

ligand_file.txt format, one entry per line, semicolon-separated:
    <name>;<charge>;<ignored>;<ignored>;<telec>
e.g.
    1a0q;-2;0.1;0;300.0

For each (subfolder, ligand) pair this runs, exactly as you specified:
    ./Executable_GFN2.exe <xyz_path> <charge> <telec> > <xyz_path with .out>

stderr is additionally captured to a sibling .err file (not part of your
original spec, but otherwise failures are invisible when running in
parallel -- delete/ignore the .err files if you don't want them).

Every run always overwrites any existing .out/.err for the tasks it selects
(no skip-if-done check) -- rerunning is the way to redo anything you suspect
is incomplete or stale.

Usage:
    python run_gfn2.py --root /path/to/folder --jobs 8
    python run_gfn2.py --root /path/to/folder --dry-run   # sanity check first
    python run_gfn2.py --jobs 10 \
        --subfolders paris-main-MISATO-xyz_ip,paris-main-MISATO-xyz_opt
        # restrict to just these two subfolders, rerunning everything in them
"""
import argparse
import concurrent.futures as cf
import subprocess
import sys
from pathlib import Path

SUBFOLDER_SUFFIX = {
    'paris-main-MISATO-xyz_orig': '_ligand.xyz',
    'paris-main-MISATO-xyz_ip': '_ligand_ip.xyz',
    'paris-main-MISATO-xyz_opt': '_ligand_opt.xyz',
}


def parse_ligand_file(path):
    """Yield (name, charge, telec) from a ligand_file.txt."""
    entries = []
    with open(path, encoding='utf-8') as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            fields = line.split(';')
            if len(fields) < 5:
                print(f"WARNING: {path}:{lineno} has fewer than 5 fields, skipping: {line!r}",
                      file=sys.stderr)
                continue
            name, charge, _ignored1, _ignored2, telec = fields[:5]
            entries.append((name.strip(), charge.strip(), telec.strip()))
    return entries


def build_tasks(root, executable, entries, subfolders=None):
    """subfolders: iterable of subfolder names to restrict to (default: all in SUBFOLDER_SUFFIX)."""
    active = {name: suffix for name, suffix in SUBFOLDER_SUFFIX.items()
              if subfolders is None or name in subfolders}
    tasks = []
    missing_xyz = []
    for subfolder_name, suffix in active.items():
        subfolder_path = root / subfolder_name
        if not subfolder_path.is_dir():
            print(f"WARNING: subfolder not found, skipping: {subfolder_path}", file=sys.stderr)
            continue
        for name, charge, telec in entries:
            xyz_path = subfolder_path / f"{name}{suffix}"
            if not xyz_path.exists():
                missing_xyz.append(str(xyz_path))
                continue
            out_path = xyz_path.with_suffix('.out')
            err_path = xyz_path.with_suffix('.err')
            tasks.append((str(executable), xyz_path, charge, telec, out_path, err_path))
    return tasks, missing_xyz


def run_one(task):
    executable, xyz_path, charge, telec, out_path, err_path = task
    cmd = [executable, str(xyz_path), charge, telec]
    try:
        with open(out_path, 'w') as out_f, open(err_path, 'w') as err_f:
            result = subprocess.run(cmd, stdout=out_f, stderr=err_f)
        if result.returncode != 0:
            return (str(xyz_path), False, f"exit code {result.returncode}, see {err_path}")
        return (str(xyz_path), True, None)
    except Exception as exc:
        return (str(xyz_path), False, str(exc))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--root', default='.', help='folder containing Executable_GFN2.exe and the 3 subfolders')
    ap.add_argument('--executable', default='Executable_GFN2.exe', help='name/path of the executable')
    ap.add_argument('--jobs', type=int, default=None, help='max parallel calculations (default: CPU count)')
    ap.add_argument('--dry-run', action='store_true', help='list what would run without executing anything')
    ap.add_argument('--names', help='comma-separated ligand names to restrict to (default: all entries in ligand_file.txt)')
    ap.add_argument('--subfolders',
                     help='comma-separated subfolder names to restrict to, e.g. '
                          'paris-main-MISATO-xyz_ip,paris-main-MISATO-xyz_opt '
                          '(default: all 3 subfolders)')
    args = ap.parse_args()

    root = Path(args.root).resolve()
    executable = root / args.executable
    if not args.dry_run and not executable.exists():
        print(f"ERROR: executable not found: {executable}", file=sys.stderr)
        sys.exit(1)

    ligand_file = root / 'ligand_file.txt'
    if not ligand_file.exists():
        print(f"ERROR: ligand_file.txt not found at {ligand_file}", file=sys.stderr)
        sys.exit(1)
    entries = parse_ligand_file(ligand_file)
    print(f"Loaded {len(entries)} ligand entries from {ligand_file} (reused for all 3 subfolders).")

    if args.names:
        wanted = [n.strip() for n in args.names.split(',') if n.strip()]
        entries_by_name = {name: (name, charge, telec) for name, charge, telec in entries}
        filtered = []
        not_found = []
        for name in wanted:
            if name in entries_by_name:
                filtered.append(entries_by_name[name])
            else:
                not_found.append(name)
        if not_found:
            print(f"WARNING: {len(not_found)} requested name(s) not found in ligand_file.txt: {not_found}",
                  file=sys.stderr)
        entries = filtered
        print(f"Restricted to {len(entries)} ligand entries (from --names).")

    subfolders = None
    if args.subfolders:
        subfolders = [s.strip() for s in args.subfolders.split(',') if s.strip()]
        unknown = [s for s in subfolders if s not in SUBFOLDER_SUFFIX]
        if unknown:
            print(f"ERROR: unknown subfolder name(s): {unknown}. "
                  f"Valid options: {list(SUBFOLDER_SUFFIX)}", file=sys.stderr)
            sys.exit(1)
        print(f"Restricted to subfolders: {subfolders}")

    tasks, missing_xyz = build_tasks(root, executable, entries, subfolders=subfolders)

    print(f"Found {len(tasks)} calculations to run.")
    if missing_xyz:
        print(f"WARNING: {len(missing_xyz)} ligands listed in ligand_file.txt had no matching xyz file:",
              file=sys.stderr)
        for m in missing_xyz[:20]:
            print(f"  missing: {m}", file=sys.stderr)
        if len(missing_xyz) > 20:
            print(f"  ... and {len(missing_xyz) - 20} more", file=sys.stderr)

    if args.dry_run:
        for executable_, xyz_path, charge, telec, out_path, _err_path in tasks:
            print(f"{executable_} {xyz_path} {charge} {telec} > {out_path}")
        return

    n_ok = 0
    failures = []
    with cf.ProcessPoolExecutor(max_workers=args.jobs) as pool:
        for xyz_path, ok, err in pool.map(run_one, tasks):
            if ok:
                n_ok += 1
            else:
                failures.append((xyz_path, err))
                print(f"FAILED: {xyz_path} ({err})", file=sys.stderr)

    print(f"\nDone. {n_ok} succeeded, {len(failures)} failed out of {len(tasks)}.")
    if failures:
        print("Failed cases:", file=sys.stderr)
        for xyz_path, err in failures:
            print(f"  {xyz_path}: {err}", file=sys.stderr)


if __name__ == '__main__':
    main()