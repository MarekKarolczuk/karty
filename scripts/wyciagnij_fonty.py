"""Jednorazowa ekstrakcja fontów UI z bundla HTML designu.

Bundel (Design/Generator Kart - offline.html) osadza fonty Archivo,
Cormorant Garamond i JetBrains Mono jako base64 w manifeście
(<script type="__bundler/manifest">). Skrypt dekoduje je, konwertuje
woff/woff2 na ttf (wymaga: fonttools + brotli) i zapisuje do
assets/fonts/ui/.

UWAGA: fonty trafiają do podfolderu ui/, NIE do assets/fonts/ —
config.find_serif_font() bierze pierwszy *.ttf z assets/fonts/ do
rysowania wartości NA generowanych kartach i font UI zepsułby ich wygląd.

Uruchomienie:  python -m scripts.wyciagnij_fonty
"""
from __future__ import annotations

import base64
import gzip
import io
import json
import sys
import zlib
from pathlib import Path

from app import config

HTML_PATH = config.ROOT / "Design" / "Generator Kart - offline.html"
OUT_DIR = config.FONTS_DIR / "ui"


def _find_manifest(text: str) -> dict:
    marker = '<script type="__bundler/manifest">'
    start = text.index(marker) + len(marker)
    end = text.index("</script>", start)
    return json.loads(text[start:end].strip())


def _decompress(raw: bytes) -> bytes:
    if raw[:2] == b"\x1f\x8b":
        return gzip.decompress(raw)
    try:
        return zlib.decompress(raw)
    except zlib.error:
        return raw


def _font_filename(data: bytes, fallback: str) -> str:
    """Nazwa pliku z tabeli name fontu (rodzina + odmiana)."""
    from fontTools.ttLib import TTFont

    font = TTFont(io.BytesIO(data), fontNumber=0, lazy=True)
    name = font["name"]
    family = name.getDebugName(1) or "Font"
    subfamily = name.getDebugName(2) or "Regular"
    font.close()
    safe = f"{family}-{subfamily}".replace(" ", "")
    return f"{safe}.ttf" if safe else fallback


def _to_ttf(data: bytes) -> bytes:
    """woff/woff2 -> ttf (fonttools czyta oba przy zainstalowanym brotli)."""
    from fontTools.ttLib import TTFont

    font = TTFont(io.BytesIO(data))
    font.flavor = None
    out = io.BytesIO()
    font.save(out)
    return out.getvalue()


def _merge_subsets(blobs: list[bytes]) -> bytes:
    """Scala podzestawy unicode tej samej odmiany w jeden ttf."""
    import tempfile

    from fontTools.merge import Merger, Options

    with tempfile.TemporaryDirectory() as tmp:
        paths = []
        for i, blob in enumerate(blobs):
            p = Path(tmp) / f"subset{i}.ttf"
            p.write_bytes(blob)
            paths.append(str(p))
        # Podzestawy pochodzą z fontów variable — tabele wariacyjne i OpenType
        # layout blokują merge, a dla UI są zbędne (tracimy tylko kerning).
        drop = ["vmtx", "vhea", "MATH", "GDEF", "GSUB", "GPOS", "STAT",
                "avar", "fvar", "gvar", "HVAR", "MVAR", "VVAR", "DSIG"]
        merger = Merger(options=Options(drop_tables=drop))
        merged = merger.merge(paths)
        out = io.BytesIO()
        merged.save(out)
        return out.getvalue()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not HTML_PATH.exists():
        print(f"Nie znaleziono bundla: {HTML_PATH}")
        return 1
    try:
        import fontTools  # noqa: F401
        import brotli  # noqa: F401
    except ImportError:
        print("Zainstaluj zależności skryptu:  pip install fonttools brotli")
        return 1

    manifest = _find_manifest(HTML_PATH.read_text(encoding="utf-8"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Google Fonts tnie fonty na podzestawy unicode (latin, latin-ext...)
    # o tej samej nazwie odmiany — zbieramy wszystkie i scalamy w jeden ttf,
    # żeby nie zgubić polskich znaków (są tylko w latin-ext).
    font_mimes = {"font/ttf", "font/woff2", "font/woff"}
    subsets: dict[str, list[bytes]] = {}
    for uuid, entry in manifest.items():
        mime = entry.get("mime", "")
        if mime not in font_mimes:
            continue
        raw = base64.b64decode(entry["data"])
        if entry.get("compressed"):
            raw = _decompress(raw)
        try:
            ttf = raw if mime == "font/ttf" else _to_ttf(raw)
            filename = _font_filename(ttf, f"{uuid}.ttf")
        except Exception as exc:
            print(f"✖ pominięto {uuid} ({mime}): {exc}")
            continue
        subsets.setdefault(filename, []).append(ttf)

    saved: dict[str, int] = {}
    for filename, blobs in subsets.items():
        blobs.sort(key=len, reverse=True)   # największy podzbiór jako baza
        data = blobs[0]
        if len(blobs) > 1:
            try:
                data = _merge_subsets(blobs)
            except Exception as exc:
                print(f"! {filename}: scalanie nieudane ({exc}) — "
                      f"zapisuję największy podzbiór")
        (OUT_DIR / filename).write_bytes(data)
        saved[filename] = len(data)
        print(f"✔ {filename}  ({len(blobs)} podzb., {len(data) // 1024} KB)")

    print(f"\nZapisano {len(saved)} fontów do {OUT_DIR}")
    return 0 if saved else 1


if __name__ == "__main__":
    sys.exit(main())
