"""
host_solver.py
--------------
FastAPI server running on the remote machine.

POST /solve       — saves the .k file, starts LS-DYNA in a background thread,
                    returns {"job_id": "..."} immediately.
GET  /status/{id} — returns {"status": "running"|"success"|"error", "output": "..."}

This avoids keeping a long-lived idle TCP connection open while the solver runs
(which causes routers to silently drop the connection via NAT timeout).
"""

import os
import uuid
import shutil
import subprocess
import threading
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse

app = FastAPI()

LSDYNA_EXE = r"C:\Program Files\ANSYS Inc\v251\ansys\bin\win64\lsdyna_dp.exe"

# In-memory job store  {job_id: {"status": ..., "output": ...}}
jobs: dict[str, dict] = {}


def _run_solver(job_id: str, filename: str):
    command = [LSDYNA_EXE, f"i={filename}", "memory=100m", "nproc=4"]
    process = subprocess.run(command, shell=False, capture_output=True, text=True)
    if os.path.isfile("d3plot"):
        jobs[job_id] = {"status": "success", "output": process.stdout[-500:]}
    else:
        jobs[job_id] = {"status": "error", "output": process.stderr[-500:]}


@app.post("/solve")
def start_simulation(file: UploadFile = File(...)):
    with open(file.filename, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "running", "output": ""}
    print(f"[{job_id}] Starting solver for: {file.filename}")

    t = threading.Thread(target=_run_solver, args=(job_id, file.filename), daemon=True)
    t.start()

    return {"job_id": job_id}


@app.get("/status/{job_id}")
def get_status(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        return JSONResponse(status_code=404, content={"error": "unknown job_id"})
    return job


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
