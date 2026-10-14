"""Download the official pinned release with resumable, verified byte ranges."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import urllib.request
import time

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "tools/voicevox"
URL = "https://github.com/VOICEVOX/voicevox_engine/releases/download/0.25.2/voicevox_engine-linux-cpu-x64-0.25.2.7z.001"
SIZE = 1815385564
CHUNK = 128 * 1024 * 1024


def main():
    FOLDER.mkdir(parents=True, exist_ok=True)
    output = FOLDER / "engine.7z.001"
    # Reuse complete ranges from a previous sequential download.
    if output.exists() and output.stat().st_size < SIZE:
        with output.open("rb") as stream:
            for i in range(output.stat().st_size // CHUNK):
                part = FOLDER / f"part-{i:02}"
                if not part.exists():
                    part.write_bytes(stream.read(CHUNK))
                else:
                    stream.seek(CHUNK, 1)

    def download(i):
        start, end = i * CHUNK, min(SIZE, (i + 1) * CHUNK) - 1
        part = FOLDER / f"part-{i:02}"
        if part.exists() and part.stat().st_size == end - start + 1:
            return part
        for attempt in range(3):
            try:
                request = urllib.request.Request(URL, headers={"Range": f"bytes={start}-{end}"})
                with urllib.request.urlopen(request, timeout=120) as response:
                    if response.status != 206 or response.headers.get("Content-Range") != f"bytes {start}-{end}/{SIZE}":
                        raise RuntimeError("Release server did not honor the requested byte range")
                    with part.open("wb") as stream:
                        while block := response.read(1024 * 1024):
                            stream.write(block)
                if part.stat().st_size != end - start + 1:
                    raise RuntimeError("Incomplete byte range")
                print(f"Downloaded range {i}", flush=True)
                return part
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2)
    with ThreadPoolExecutor(max_workers=6) as pool:
        parts = list(pool.map(download, range((SIZE + CHUNK - 1) // CHUNK)))
    with output.open("wb") as stream:
        for part in parts:
            with part.open("rb") as source:
                while block := source.read(1024 * 1024):
                    stream.write(block)
    assert output.stat().st_size == SIZE
    print(f"Release downloaded: {output}", flush=True)


if __name__ == "__main__":
    main()
