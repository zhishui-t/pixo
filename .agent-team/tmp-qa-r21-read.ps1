import json, pathlib
for name in ("tmp-r21-d1-table.txt", "tmp-r21-gate-final.txt"):
    p = pathlib.Path(r"K:\work\project\pixo\.agent-team") / name
    raw = p.read_bytes()
    for enc in ("utf-8", "utf-16", "cp936", "utf-8-sig"):
        try:
            text = raw.decode(enc); break
        except Exception:
            continue
    print("=" * 20, name, "bytes=", len(raw), "enc=", enc)
    print(text.strip()[:1600])
