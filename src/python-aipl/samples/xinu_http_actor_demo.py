#!/usr/bin/env python3
"""Mac-side AIPL "actor" that drives a Xinu actor over the http:// scheme.

This exercises the Phase M1 path in aipl_remote.py end-to-end against the
real xinu-rpi5 HTTP actor gateway (system/tcp_server.c + system/actor.c):

    Mac actor  --http GET /send-->  Xinu actor (id 0 "counter", id 1 "store")

Run (after flashing the HTTP-gateway kernel and booting the Pi 4):

    python3 xinu_http_actor_demo.py                 # default 192.168.3.100
    python3 xinu_http_actor_demo.py 192.168.3.100   # explicit host

Make sure the Mac has the static ARP entry first:
    sudo arp -s 192.168.3.100 d8:3a:dd:a7:fd:bf
"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import aipl_remote as R


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else "192.168.3.100"
    hub  = f"http://{host}"          # the http:// prefix selects the Xinu gateway
    print(f"[mac-actor] target Xinu gateway: {hub}")

    # Fire-and-forget message to actor 0 (counter): bump.
    R.remote_send(hub, "0", "bump", [])
    print("[mac-actor] sent bump (fire-and-forget)")

    # Synchronous calls — block on the Xinu actor's reply (the result int).
    v = R.remote_call_sync(hub, "0", "bump", [])
    print(f"[mac-actor] counter.bump -> {v}")
    v = R.remote_call_sync(hub, "0", "add", [40])
    print(f"[mac-actor] counter.add(40) -> {v}")
    v = R.remote_call_sync(hub, "0", "get", [])
    print(f"[mac-actor] counter.get -> {v}")

    # A second Xinu actor (id 1 "store").
    R.remote_call_sync(hub, "1", "set", [7])
    v = R.remote_call_sync(hub, "1", "add", [35])
    print(f"[mac-actor] store.set(7).add(35) -> {v}")

    print("[mac-actor] done — messages delivered to Xinu actors over TCP/HTTP.")


if __name__ == "__main__":
    main()
