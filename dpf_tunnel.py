"""
dpf_tunnel.py
-------------
Run this on the REMOTE machine. It listens on 0.0.0.0:50069 and forwards
all traffic transparently to the DPF server on 127.0.0.1:50068.

Usage:
    python dpf_tunnel.py

Requires only the Python standard library.
"""

import asyncio

LISTEN_HOST  = "0.0.0.0"
LISTEN_PORT  = 50069          # LAN-facing port (open this in the firewall)
TARGET_HOST  = "127.0.0.1"
TARGET_PORT  = 50068          # DPF server local port


async def pipe(reader, writer):
    try:
        while chunk := await reader.read(65536):
            writer.write(chunk)
            await writer.drain()
    finally:
        writer.close()


async def handle(client_reader, client_writer):
    addr = client_writer.get_extra_info("peername")
    print(f"[+] Connection from {addr}")
    try:
        server_reader, server_writer = await asyncio.open_connection(TARGET_HOST, TARGET_PORT)
        await asyncio.gather(
            pipe(client_reader, server_writer),
            pipe(server_reader, client_writer),
        )
    except Exception as e:
        print(f"[-] {addr} disconnected: {e}")
    finally:
        client_writer.close()


async def main():
    server = await asyncio.start_server(handle, LISTEN_HOST, LISTEN_PORT)
    print(f"[*] DPF tunnel listening on {LISTEN_HOST}:{LISTEN_PORT} -> {TARGET_HOST}:{TARGET_PORT}")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
