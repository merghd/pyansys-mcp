"""
solve_combined.py
-----------------
One keyword file, one solve, one d3plot.

Two cubes side by side (1 mm gap between them):
  - Left:  1×1×1 mm,  1 HEXA8 element  (part 1)
  - Right: 1×1×1 mm, 4×4×4 = 64 HEXA8 elements (part 2, offset +2 mm in X)

Same loading on both:
  - Bottom face fully fixed.
  - Top face: x/y constrained, z prescribed -0.1 mm over 1 ms.
  - MAT_024 steel: E=200 GPa, ν=0.3, yield=250 MPa, Et=2000 MPa.

Post-processing produces:
  - Side-by-side PEEQ contour plot (PNG).
  - Side-by-side animated GIF over all time steps.
"""

import os
import httpx
import numpy as np
import pandas as pd
from ansys.dyna.core import Deck, keywords as kwd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
REMOTE_IP   = "192.168.0.37"
DYNA_PORT   = 5000
DPF_PORT    = 50068
OUTPUT_FILE = "combined.k"

# ---------------------------------------------------------------------------
# 1. Build keyword file
# ---------------------------------------------------------------------------
deck = Deck()

# ---- Shared material, section, part(s) ------------------------------------
mat = kwd.Mat024(mid=1)
mat.ro   = 7.85e-9
mat.e    = 200000.0
mat.pr   = 0.3
mat.sigy = 250.0
mat.etan = 2000.0
mat.fail = 1e21
deck.append(mat)

sec = kwd.SectionSolid(secid=1)
sec.elform = 1
deck.append(sec)

# Both cubes use the same material/section but different part IDs so we can
# filter results later by element range if needed (here we use one part for
# simplicity — the pids are the same so DPF sees a single contiguous model).
part = kwd.Part()
part.parts = pd.DataFrame({
    "heading": ["steel_block"],
    "pid":     [1],
    "secid":   [1],
    "mid":     [1],
})
deck.append(part)

# ---- Load curve (shared) --------------------------------------------------
lc = kwd.DefineCurve(lcid=1)
lc.curves = pd.DataFrame({"a1": [0.0, 1.0e-3], "o1": [0.0, -0.1]})
deck.append(lc)

# ===========================================================================
# CUBE A — single HEXA8 element, x=0..1, y=0..1, z=0..1
#   Nodes 1-8, Element 1
# ===========================================================================
X0 = 0.0   # left cube x-origin

node_rows_A = [
    {"nid": 1, "x": X0+0, "y": 0, "z": 0},
    {"nid": 2, "x": X0+1, "y": 0, "z": 0},
    {"nid": 3, "x": X0+1, "y": 1, "z": 0},
    {"nid": 4, "x": X0+0, "y": 1, "z": 0},
    {"nid": 5, "x": X0+0, "y": 0, "z": 1},
    {"nid": 6, "x": X0+1, "y": 0, "z": 1},
    {"nid": 7, "x": X0+1, "y": 1, "z": 1},
    {"nid": 8, "x": X0+0, "y": 1, "z": 1},
]
node_kw_A = kwd.Node()
node_kw_A.nodes = pd.DataFrame(node_rows_A)
deck.append(node_kw_A)

elem_kw_A = kwd.ElementSolid()
elem_kw_A.elements = pd.DataFrame([
    {"eid": 1, "pid": 1, "n1":1,"n2":2,"n3":3,"n4":4,"n5":5,"n6":6,"n7":7,"n8":8}
])
deck.append(elem_kw_A)

# BCs — bottom face fixed (z=0)
for n in [1, 2, 3, 4]:
    bc = kwd.BoundarySpcNode()
    bc.nodes = pd.DataFrame({"nid":[n],"cid":[0],"dofx":[1],"dofy":[1],"dofz":[1],"dofrx":[1],"dofry":[1],"dofrz":[1]})
    deck.append(bc)

# BCs — top face: fix x/y, free z
for n in [5, 6, 7, 8]:
    bc = kwd.BoundarySpcNode()
    bc.nodes = pd.DataFrame({"nid":[n],"cid":[0],"dofx":[1],"dofy":[1],"dofz":[0],"dofrx":[0],"dofry":[0],"dofrz":[0]})
    deck.append(bc)

# Prescribed z-displacement on top face
for n in [5, 6, 7, 8]:
    spcd = kwd.BoundaryPrescribedMotionNode()
    spcd.nid  = n
    spcd.dof  = 3
    spcd.vad  = 2
    spcd.lcid = 1
    spcd.sf   = 1.0
    deck.append(spcd)

print("Cube A: 8 nodes, 1 element")

# ===========================================================================
# CUBE B — 4×4×4 HEXA8 grid, x=2..3, y=0..1, z=0..1
#   Nodes start at NID 9, Elements start at EID 2
# ===========================================================================
X1  = 2.0   # right cube x-origin (1 mm gap between cubes)
NB  = 4     # elements per direction
NID_BASE = 9
EID_BASE = 2

def nid_B(ix, iy, iz):
    return NID_BASE + iz * (NB+1)**2 + iy * (NB+1) + ix

node_rows_B = []
for iz in range(NB+1):
    for iy in range(NB+1):
        for ix in range(NB+1):
            node_rows_B.append({
                "nid": nid_B(ix, iy, iz),
                "x":   X1 + ix / NB,
                "y":   iy / NB,
                "z":   iz / NB,
            })

node_kw_B = kwd.Node()
node_kw_B.nodes = pd.DataFrame(node_rows_B)
deck.append(node_kw_B)

elem_rows_B = []
eid = EID_BASE
for iz in range(NB):
    for iy in range(NB):
        for ix in range(NB):
            elem_rows_B.append({
                "eid": eid, "pid": 1,
                "n1": nid_B(ix,   iy,   iz  ),
                "n2": nid_B(ix+1, iy,   iz  ),
                "n3": nid_B(ix+1, iy+1, iz  ),
                "n4": nid_B(ix,   iy+1, iz  ),
                "n5": nid_B(ix,   iy,   iz+1),
                "n6": nid_B(ix+1, iy,   iz+1),
                "n7": nid_B(ix+1, iy+1, iz+1),
                "n8": nid_B(ix,   iy+1, iz+1),
            })
            eid += 1

elem_kw_B = kwd.ElementSolid()
elem_kw_B.elements = pd.DataFrame(elem_rows_B)
deck.append(elem_kw_B)

# BCs — bottom face (iz=0)
for ix in range(NB+1):
    for iy in range(NB+1):
        bc = kwd.BoundarySpcNode()
        bc.nodes = pd.DataFrame({"nid":[nid_B(ix,iy,0)],"cid":[0],"dofx":[1],"dofy":[1],"dofz":[1],"dofrx":[1],"dofry":[1],"dofrz":[1]})
        deck.append(bc)

# BCs — top face (iz=NB): fix x/y
for ix in range(NB+1):
    for iy in range(NB+1):
        bc = kwd.BoundarySpcNode()
        bc.nodes = pd.DataFrame({"nid":[nid_B(ix,iy,NB)],"cid":[0],"dofx":[1],"dofy":[1],"dofz":[0],"dofrx":[0],"dofry":[0],"dofrz":[0]})
        deck.append(bc)

# Prescribed z-displacement on top face
for ix in range(NB+1):
    for iy in range(NB+1):
        spcd = kwd.BoundaryPrescribedMotionNode()
        spcd.nid  = nid_B(ix, iy, NB)
        spcd.dof  = 3
        spcd.vad  = 2
        spcd.lcid = 1
        spcd.sf   = 1.0
        deck.append(spcd)

total_nodes = 8 + len(node_rows_B)
total_elems = 1 + len(elem_rows_B)
print(f"Cube B: {len(node_rows_B)} nodes, {len(elem_rows_B)} elements")
print(f"Total:  {total_nodes} nodes, {total_elems} elements")

# ---- Control & output -----------------------------------------------------
ctrl_term = kwd.ControlTermination()
ctrl_term.endtim = 1.0e-3
deck.append(ctrl_term)

ctrl_time = kwd.ControlTimestep()
ctrl_time.tssfac = 0.9
deck.append(ctrl_time)

ctrl_energy = kwd.ControlEnergy()
ctrl_energy.hgen = 2; ctrl_energy.rwen = 2
ctrl_energy.slnten = 2; ctrl_energy.rylen = 2
deck.append(ctrl_energy)

db_d3plot = kwd.DatabaseBinaryD3Plot()
db_d3plot.dt = 1.0e-4
deck.append(db_d3plot)

db_extent = kwd.DatabaseExtentBinary()
db_extent.strflg = 1
deck.append(db_extent)

db_glstat = kwd.DatabaseGlstat()
db_glstat.dt = 1.0e-5
deck.append(db_glstat)

with open(OUTPUT_FILE, "w") as f:
    f.write(deck.write())
print(f"[OK] Keyword file written: {os.path.abspath(OUTPUT_FILE)}")

# ---------------------------------------------------------------------------
# 2. Submit to remote LS-DYNA
# ---------------------------------------------------------------------------
def run_lsdyna_simulation(keyword_file):
    """Submit job, then poll /status until done. Avoids NAT idle-timeout hang."""
    if not os.path.isfile(keyword_file):
        return f"Error: '{keyword_file}' not found."
    try:
        # 1. Submit — returns immediately with a job_id
        url_solve = f"http://{REMOTE_IP}:{DYNA_PORT}/solve"
        print(f"[..] Submitting '{keyword_file}' to {url_solve} ...")
        with open(keyword_file, "rb") as f:
            resp = httpx.post(
                url_solve,
                files={"file": (os.path.basename(keyword_file), f, "application/octet-stream")},
                timeout=30.0,
            )
        data = resp.json()

        # New server returns job_id for async polling
        if "job_id" in data:
            job_id = data["job_id"]
            print(f"[OK] Job started: {job_id}")
            import time
            url_status = f"http://{REMOTE_IP}:{DYNA_PORT}/status/{job_id}"
            while True:
                time.sleep(5)
                status_resp = httpx.get(url_status, timeout=10.0)
                data = status_resp.json()
                state = data.get("status")
                print(f"    ... {state}")
                if state == "success":
                    return f"Simulation complete on {REMOTE_IP}."
                elif state == "error":
                    return f"Solver failed:\n{data.get('output')}"

        # Old server returns status directly (blocking solve)
        elif data.get("status") == "success":
            return f"Simulation complete on {REMOTE_IP}."
        else:
            return f"Solver failed:\n{data.get('output')}"

    except Exception as e:
        return f"Connection failed: {e}"

result = run_lsdyna_simulation(OUTPUT_FILE)
print(f"\n[SOLVER RESULT]\n{result}")

if "complete" not in result:
    raise SystemExit("Solver failed — skipping post-processing.")

# ---------------------------------------------------------------------------
# 3. Post-processing via remote DPF
# ---------------------------------------------------------------------------
from ansys.dpf import core as dpf
from ansys.dpf.core.server_factory import ServerConfig, CommunicationProtocols, GrpcMode
import pyvista as pv
import imageio.v3 as iio
import tempfile, pathlib

config = ServerConfig(protocol=CommunicationProtocols.gRPC, grpc_mode=GrpcMode.Insecure)
print(f"\n[..] Connecting to DPF at {REMOTE_IP}:{DPF_PORT} ...")
dpf_server = dpf.connect_to_server(ip=REMOTE_IP, port=DPF_PORT, config=config)
print(f"[OK] DPF server version: {dpf_server.version}")

ds = dpf.DataSources(server=dpf_server)
ds.set_result_file_path("d3plot", "d3plot")
model     = dpf.Model(ds, server=dpf_server)
final_set = model.metadata.time_freq_support.n_sets - 1

u_fc       = model.results.displacement(time_scoping=[final_set]).eval()
disp_field = u_fc[0]

peeq_fc  = model.results.plastic_strain_eqv(time_scoping=[final_set]).eval()
peeq_val = float(peeq_fc[0].data.max())

vm_fc  = model.results.stress_von_mises(time_scoping=[final_set]).eval()
vm_val = float(vm_fc[0].data.max())

print(f"\nMax Von Mises: {vm_val:.2f} MPa")
print(f"Max PEEQ:      {peeq_val:.6f}")

# ---------------------------------------------------------------------------
# 4. Build PyVista grids
# ---------------------------------------------------------------------------
# Element IDs in each cube
ELEM_IDS_A = [1]
ELEM_IDS_B = list(range(2, 2 + NB**3))

def build_pv_grid(model, peeq_field, disp_field, elem_ids):
    """Build a deformed PyVista UnstructuredGrid for a subset of elements."""
    mesh = model.metadata.meshed_region

    # Full node map
    all_node_ids = list(mesh.nodes.scoping.ids)
    all_coords   = mesh.nodes.coordinates_field.data.copy()
    nid_to_idx   = {n: i for i, n in enumerate(all_node_ids)}

    # Apply displacements
    for i, nid_val in enumerate(disp_field.scoping.ids):
        idx = nid_to_idx.get(nid_val)
        if idx is not None:
            all_coords[idx] += disp_field.data[i]

    # Elemental PEEQ -> nodal average
    avg = dpf.operators.averaging.elemental_to_nodal(server=dpf_server)
    avg.inputs.field(peeq_field)
    peeq_nodal = avg.outputs.field()

    peeq_vals = np.zeros(len(all_node_ids))
    for i, nid_val in enumerate(peeq_nodal.scoping.ids):
        idx = nid_to_idx.get(nid_val)
        if idx is not None:
            peeq_vals[idx] = peeq_nodal.data[i]

    # Collect connectivity for requested elements
    elem_id_set = set(elem_ids)
    cells, ctypes = [], []
    local_node_set = set()

    for e in mesh.elements:
        if e.id not in elem_id_set:
            continue
        conn = list(e.connectivity)   # 0-based indices into all_node_ids
        cells.extend([8] + conn)
        ctypes.append(pv.CellType.HEXAHEDRON)
        local_node_set.update(conn)

    grid = pv.UnstructuredGrid(np.array(cells), np.array(ctypes), all_coords)
    grid.point_data["PEEQ"] = peeq_vals
    return grid


print("\n[..] Building PyVista grids ...")
grid_A = build_pv_grid(model, peeq_fc[0], disp_field, ELEM_IDS_A)
grid_B = build_pv_grid(model, peeq_fc[0], disp_field, ELEM_IDS_B)

peeq_A = float(grid_A.point_data["PEEQ"].max())
peeq_B = float(grid_B.point_data["PEEQ"].max())
print(f"  Cube A PEEQ max = {peeq_A:.6f}")
print(f"  Cube B PEEQ max = {peeq_B:.6f}")

# ---------------------------------------------------------------------------
# 5. Side-by-side static PEEQ contour plot
# ---------------------------------------------------------------------------
print("\n[..] Generating side-by-side PEEQ contour plot ...")

clim = [0.0, max(peeq_A, peeq_B, 1e-8)]
sargs = dict(color="black", fmt="%.4f")

pv.OFF_SCREEN = True
pl = pv.Plotter(shape=(1, 2), off_screen=True, window_size=[1600, 700])

pl.subplot(0, 0)
pl.set_background("white")
pl.add_mesh(grid_A, scalars="PEEQ", cmap="plasma", show_edges=True,
            edge_color="black", clim=clim,
            scalar_bar_args=dict(title="PEEQ (1-elem)", **sargs))
pl.add_text(f"1 element\nPEEQ_max={peeq_A:.4f}\nVM_max={vm_val:.0f} MPa",
            position="upper_left", font_size=9, color="black")
pl.add_axes(color="black")
pl.camera_position = "iso"

pl.subplot(0, 1)
pl.set_background("white")
pl.add_mesh(grid_B, scalars="PEEQ", cmap="plasma", show_edges=True,
            edge_color="black", clim=clim,
            scalar_bar_args=dict(title="PEEQ (64-elem)", **sargs))
pl.add_text(f"64 elements (4×4×4)\nPEEQ_max={peeq_B:.4f}",
            position="upper_left", font_size=9, color="black")
pl.add_axes(color="black")
pl.camera_position = "iso"

pl.screenshot("combined_peeq.png", return_img=False)
pl.close()
print(f"[OK] Saved: {os.path.abspath('combined_peeq.png')}")

# ---------------------------------------------------------------------------
# 6. Side-by-side animated GIF
# ---------------------------------------------------------------------------
print("\n[..] Generating side-by-side animation ...")

peeq_all = model.results.plastic_strain_eqv.on_all_time_freqs.eval()
u_all    = model.results.displacement.on_all_time_freqs.eval()

all_peeq_max = [max(float(f.data.max()), 1e-8) for f in peeq_all]
gif_clim = [0.0, max(all_peeq_max)]

tmp_dir     = pathlib.Path(tempfile.mkdtemp())
frame_paths = []

for idx, (peeq_f, u_f) in enumerate(zip(peeq_all, u_all)):
    gA = build_pv_grid(model, peeq_f, u_f, ELEM_IDS_A)
    gB = build_pv_grid(model, peeq_f, u_f, ELEM_IDS_B)
    step_peeq = float(peeq_f.data.max())

    fpath = str(tmp_dir / f"frame_{idx:03d}.png")
    pl = pv.Plotter(shape=(1, 2), off_screen=True, window_size=[1400, 600])

    pl.subplot(0, 0)
    pl.set_background("white")
    pl.add_mesh(gA, scalars="PEEQ", cmap="plasma", show_edges=True,
                edge_color="black", clim=gif_clim,
                scalar_bar_args=dict(title="PEEQ (1-elem)", color="black", fmt="%.4f"))
    pl.add_text(f"1 element | PEEQ={float(gA.point_data['PEEQ'].max()):.4f}",
                position="upper_left", font_size=9, color="black")
    pl.add_axes(color="black")
    pl.camera_position = "iso"

    pl.subplot(0, 1)
    pl.set_background("white")
    pl.add_mesh(gB, scalars="PEEQ", cmap="plasma", show_edges=True,
                edge_color="black", clim=gif_clim,
                scalar_bar_args=dict(title="PEEQ (64-elem)", color="black", fmt="%.4f"))
    pl.add_text(f"64 elements | PEEQ={float(gB.point_data['PEEQ'].max()):.4f}",
                position="upper_left", font_size=9, color="black")
    pl.add_axes(color="black")
    pl.camera_position = "iso"

    pl.screenshot(fpath, return_img=False)
    pl.close()
    frame_paths.append(fpath)
    print(f"  Frame {idx+1}/{len(peeq_all)} done")

frames = [iio.imread(f) for f in frame_paths]
iio.imwrite("combined_animation.gif", frames, duration=150, loop=0)
print(f"[OK] Animation saved: {os.path.abspath('combined_animation.gif')}")
