"""Read raw X10A frames via the esphome-altherma query_register service.

Read-only: every call is a protocol-I read request (03 40 <reg> <crc>).
The service returns the whole frame (40 <reg> <len> <data...> <crc>), so one
call per register is enough; decode.py splits it into fields.

Run inside the ESPHome image (has aioesphomeapi; API key from secrets.yaml):

  docker run --rm -v "$PWD":/config:ro -v "$PWD/tools/x10a_probe":/probe \
    --entrypoint python3 ghcr.io/esphome/esphome:2026.9.1 \
    /probe/probe.py 192.168.1.225 /probe/out.json 10 20 21 30 60 61 62 63 64 A0 A1

Env: WAIT_RUNNING_S=180 waits until the compressor has run that long;
GAP_S=0.4 sets the pause between queries (default 1.5 s).
"""
import asyncio
import json
import os
import re
import sys
import time

import yaml
from aioesphomeapi import APIClient, TextSensorInfo, SensorInfo


def load_key():
    class L(yaml.SafeLoader):
        pass
    L.add_constructor("!secret", lambda l, n: None)
    return yaml.load(open("/config/secrets.yaml"), Loader=L)["api_encryption_key"]


async def main(host, out, regs):
    cli = APIClient(host, 6053, None, noise_psk=load_key())
    await cli.connect(login=True)
    entities, services = await cli.list_entities_services()
    svc = next(s for s in services if s.name == "query_register")
    ts = next(e for e in entities if isinstance(e, TextSensorInfo)
              and "manual_query" in e.object_id)

    queue = asyncio.Queue()
    rps_key = next(e.key for e in entities if isinstance(e, SensorInfo)
                   and "inv_frequency" in e.object_id)
    rps = {"v": 0.0, "since": None}

    def on_state(st):
        k = getattr(st, "key", None)
        if k == ts.key and getattr(st, "state", ""):
            queue.put_nowait(st.state)
        elif k == rps_key:
            v = st.state or 0.0
            if v > 0 and rps["since"] is None:
                rps["since"] = time.time()
            elif v <= 0:
                rps["since"] = None
            rps["v"] = v

    cli.subscribe_states(on_state)
    await asyncio.sleep(1)
    need = float(os.environ.get("WAIT_RUNNING_S", "0"))
    while need and not (rps["since"] and time.time() - rps["since"] >= need):
        await asyncio.sleep(10)
    if need:
        print(f"compressor running {rps['v']} rps for {time.time() - rps['since']:.0f}s", flush=True)
    while not queue.empty():
        queue.get_nowait()

    res = {}
    for reg in regs:
        r = f"0x{reg:02X}"
        await cli.execute_service(svc, {"register": r, "offset": 0, "convid": 152, "datasize": 1})
        final = None
        try:
            while True:
                msg = await asyncio.wait_for(queue.get(), timeout=8)
                if f"reg=0x{reg:02X}" not in msg and "rejected" not in msg:
                    continue
                if "accepted" in msg:
                    continue
                final = msg
                break
        except asyncio.TimeoutError:
            final = "timeout (no result)"
        m = re.search(r"buffer=([0-9A-F ]+)$", final)
        res[r] = {"status": final.split(" reg=")[0] if m is None else "ok",
                  "msg": final if m is None else None,
                  "frame": m.group(1).split() if m else None}
        print(r, res[r]["status"], " ".join(res[r]["frame"] or [])[:120], flush=True)
        await asyncio.sleep(float(os.environ.get("GAP_S", "1.5")))
    json.dump(res, open(out, "w"), indent=1)
    await cli.disconnect()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2], [int(x, 16) for x in sys.argv[3:]]))
