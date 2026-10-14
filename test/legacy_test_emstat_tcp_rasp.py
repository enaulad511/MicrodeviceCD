# -*- coding: utf-8 -*-
from Drivers.EmstatUtils import LineBufferedSocketReader
from Drivers.EmstatUtils import EmstatStreamParser
import socket
import json

__author__ = "Edisson Naula"
__date__ = "$ 19/11/2025 at 10:56 $"


CD_IP = "10.22.25.201"
TCP_PORT = 5006

payload = {
    "t_e": 5,
    "E_b": -200,
    "E_1": 600,
    "E_2": -600,
    "E_s": 10,
    "sc_r": 100,
    "n_sc": 3,
    "method": "cv",
}

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect((CD_IP, TCP_PORT))
s.sendall((json.dumps(payload) + "\n").encode())

reader = LineBufferedSocketReader(s)
parser = EmstatStreamParser(experiment="cv")
data_lines = []
reading = True
while reading:
    lines = reader.read_lines()
    if lines is None:
        break

    for line in lines:
        # print("RAW LINE:", line)
        data_lines.append(line)
        # Solo procesa líneas EMSTAT:
        if line.startswith("EMSTAT:"):
            raw_json = line[len("EMSTAT:") :]

            try:
                msg = json.loads(raw_json)
            except Exception:
                continue

            if msg.get("type") == "emstat_data":
                event = parser.feed_raw(msg["raw"])
                if event:
                    print("EVENT:", event)

            elif msg.get("type") == "emstat_end":
                print("END OF EXPERIMENT")
                reading = False
                break
s.close()
filename = "files_test/data_sample_cv.txt"
with open(filename, "w") as f:
    for line in data_lines:
        f.write(line + "\n")
exit(0)
