#!/usr/bin/env python3
"""Drive an interactive claude in a pty. usage: pty-run.py <cwd> <total_seconds> -- <cmd...>
Sends scripted keystrokes from env PTY_SCRIPT = JSON list of [at_seconds, "text"]."""
import os, pty, sys, time, select, json, re, struct, fcntl, termios, signal

cwd, total = sys.argv[1], float(sys.argv[2])
cmd = sys.argv[sys.argv.index('--') + 1:]
script = json.loads(os.environ.get('PTY_SCRIPT', '[]'))
pid, fd = pty.fork()
if pid == 0:
    os.chdir(cwd)
    os.environ['TERM'] = 'xterm-256color'
    os.execvp(cmd[0], cmd)
fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', 50, 200, 0, 0))
t0 = time.time()
buf = b''
sent = 0
while time.time() - t0 < total:
    r, _, _ = select.select([fd], [], [], 0.2)
    if r:
        try:
            d = os.read(fd, 65536)
        except OSError:
            break
        if not d:
            break
        buf += d
    now = time.time() - t0
    while sent < len(script) and now >= script[sent][0]:
        os.write(fd, script[sent][1].encode().decode('unicode_escape').encode())
        sent += 1
try:
    os.kill(pid, signal.SIGTERM)
except Exception:
    pass
txt = buf.decode('utf8', 'replace')
txt = re.sub(r'\x1b\[[0-9;?]*[ -/]*[@-~]', ' ', txt)
txt = re.sub(r'\x1b\][^\x07]*\x07', '', txt)
open(os.environ.get('PTY_OUT', '/tmp/pty-out.txt'), 'w').write(txt)
print(f'captured {len(buf)} bytes')
