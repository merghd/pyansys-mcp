"""
solve_block_multi.py
--------------------
Multi-element version of solve_block.py.

Geometry: 1 mm × 1 mm × 4 mm block meshed into a 2×2×4 grid = 16 HEXA8 elements.
The non-uniform loading (pinched top face) creates a PEEQ gradient across elements,
making the contour plot actually useful.

Load: top face compressed -0.3 mm over 1 ms (30% strain — well into plasticity).
BCs:  bottom face fully fixed. Top face lateral motion free (uniaxial).
Mat:  MAT_024 steel, yield=250 MPa, Et=2000 MPa.
"""

import os
import httpx
import numpy as np
import pandas as pd
from itertools import product
from ansys.dyna.core import Deck, keywords as kwd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
REMOTE_IP   = "192.168.0.37"
DYNA_PORT   = 5000
DPF_PORT    = 50068
OUTPUT_FILE = "block_multi.k"

# ---------------------------------------------------------------------------
# 1. Build the mesh — 2×2×4 grid of HEXA8 elements
# ---------------------------------------------------------------------------
deck = Deck()

NX, NY, NZ = 2, 2, 4   # elements per direction
LX, LY, LZ = 1.0, 1.0, 4.0  # total dimensions [mm]

dx = LX / NX
dy = LY / NY
dz = LZ / NZ

# Node numbering: (ix, iy, iz) -> nid, 1-based
def nid(ix, iy, iz):
    return iz * (NX+1) * (NY+1) + iy * (NX+1) + ix + 1

# Generate nodes
node_rows = []
for iz in range(NZ+1):
    for iy in range(NY+1):
        for ix in range(NX+1):
            node_rows.append({
                "nid": nid(ix, iy, iz),
                "x":   ix * dx,
                "y":   iy * dy,
                "z":   iz * dz,
            })

node_kw = kwd.Node()
node_kw.nodes = pd.DataFrame(node_rows)
deck.append(node_kw)

total_nodes = len(node_rows)
print(f"Nodes: {total_nodes}")

# Generate elements
elem_rows = []
eid = 1
for iz in range(NZ):
    for iy in range(NY):
        for ix in range(NX):
            elem_rows.append({
                "eid": eid,
                "pid": 1,
                "n1": nid(ix,   iy,   iz  ),
                "n2": nid(ix+1, iy,   iz  ),
                "n3": nid(ix+1, iy+1, iz  ),
                "n4": nid(ix,   iy+1, iz  ),
                "n5": nid(ix,   iy,   iz+1),
                "n6": nid(ix+1, iy,   iz+1),
                "n7": nid(ix+1, iy+1, iz+1),
                "n8": nid(ix,   iy+1, iz+1),
            })
            eid += 1

elem_kw = kwd.ElementSolid()
elem_kw.elements = pd.DataFrame(elem_rows)
deck.append(elem_kw)

total_elems = len(elem_rows)
print(f"Elements: {total_elems} (HEXA8)")

# ---------------------------------------------------------------------------
# 2. Material, section, part
# ---------------------------------------------------------------------------
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

part = kwd.Part()
part.parts = pd.DataFrame({"heading": ["steel_block"], "pid": [1], "secid": [1], "mid": [1]})
deck.append(part)

# ---------------------------------------------------------------------------
# 3. Boundary conditions
# ---------------------------------------------------------------------------
# Fix all DOF on bottom face (z=0)
for ix in range(NX+1):
    for iy in range(NY+1):
        bc = kwd.BoundarySpcNode()
        bc.nodes = pd.DataFrame({
            "nid": [nid(ix, iy, 0)], "cid": [0],
            "dofx": [1], "dofy": [1], "dofz": [1],
            "dofrx": [1], "dofry": [1], "dofrz": [1],
        })
        deck.append(bc)

# Constrain x/y on top face to keep uniaxial compression
for ix in range(NX+1):
    for iy in range(NY+1):
        bc = kwd.BoundarySpcNode()
        bc.nodes = pd.DataFrame({
            "nid": [nid(ix, iy, NZ)], "cid": [0],
            "dofx": [1], "dofy": [1], "dofz": [0],
            "dofrx": [0], "dofry": [0], "dofrz": [0],
        })
        deck.append(bc)

# ---------------------------------------------------------------------------
# 4. Prescribed displacement on top face — ramp to -0.3 mm over 1 ms
# ---------------------------------------------------------------------------
lc = kwd.DefineCurve(lcid=1)
lc.curves = pd.DataFrame({"a1": [0.0, 1.0e-3], "o1": [0.0, -0.3]})
deck.append(lc)

for ix in range(NX+1):
    for iy in range(NY+1):
        spcd = kwd.BoundaryPrescribedMotionNode()
        spcd.nid  = nid(ix, iy, NZ)
        spcd.dof  = 3
        spcd.vad  = 2
        spcd.lcid = 1
        spcd.sf   = 1.0
        deck.append(spcd)

# ---------------------------------------------------------------------------
# 5. Control & output
# ---------------------------------------------------------------------------
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

# Write keyword file
with open(OUTPUT_FILE, "w") as f:
    f.write(deck.write())
print(f"[OK] Keyword file written: {os.path.abspath(OUTPUT_FILE)}")

# ---------------------------------------------------------------------------
# 6. Submit to remote LS-DYNA
# ---------------------------------------------------------------------------
def run_lsdyna_simulation(keyword_file):
    if not os.path.isfile(keyword_file):
        return f"Error: '{keyword_file}' not found."
    try:
        url = f"http://{REMOTE_IP}:{DYNA_PORT}/solve"
        print(f"[..] POSTing '{keyword_file}' to {url} ...")
        with open(keyword_file, "rb") as f:
            response = httpx.post(
                url,
                files={"file": (os.path.basename(keyword_file), f, "application/octet-stream")},
                timeout=600.0,
            )
        result = response.json()
        if result.get("status") == "success":
            return f"Simulation complete on {REMOTE_IP}."
        else:
            return f"Solver failed:\n{result.get('output')}"
    except httpx.ReadTimeout:
        return "Error: Solver timed out."
    except Exception as e:
        return f"Connection failed: {e}"


result = run_lsdyna_simulation(OUTPUT_FILE)
print(f"\n[SOLVER RESULT]\n{result}")

if "complete" not in result:
    raise SystemExit("Solver failed — skipping post-processing.")

# ---------------------------------------------------------------------------
# 7. Post-processing via remote DPF
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

# Single model — d3plot is always named 'd3plot' on the remote regardless of input filename
ds = dpf.DataSources(server=dpf_server)
ds.set_result_file_path("d3plot", "d3plot")
model     = dpf.Model(ds, server=dpf_server)
final_set = model.metadata.time_freq_support.n_sets - 1  # last proper step

# Results
u_fc       = model.results.displacement(time_scoping=[final_set]).eval()
disp_field = u_fc[0]

vm_fc  = model.results.stress_von_mises(time_scoping=[final_set]).eval()
vm_val = float(vm_fc[0].data.max())
print(f"\nMax Von Mises: {vm_val:.2f} MPa")

peeq_fc  = model.results.plastic_strain_eqv(time_scoping=[final_set]).eval()
peeq_val = float(peeq_fc[0].data.max())
print(f"Max PEEQ:      {peeq_val:.6f}")

# ---------------------------------------------------------------------------
# 8. Build PyVista mesh from DPF mesh metadata + results
# ---------------------------------------------------------------------------
def build_pv_grid(model, peeq_field, disp_field):
    """Build a deformed PyVista UnstructuredGrid with PEEQ nodal values."""
    mesh = model.metadata.meshed_region

    # Node coordinates (deformed)
    coords = mesh.nodes.coordinates_field.data.copy()
    node_ids = list(mesh.nodes.scoping.ids)
    nid_to_idx = {nid: i for i, nid in enumerate(node_ids)}

    for i, nid_val in enumerate(disp_field.scoping.ids):
        idx = nid_to_idx.get(nid_val)
        if idx is not None:
            coords[idx] += disp_field.data[i]

    # Element connectivity — DPF returns 0-based indices into the node list
    cells, ctypes = [], []
    for e in mesh.elements:
        conn = list(e.connectivity)
        cells.extend([8] + conn)
        ctypes.append(pv.CellType.HEXAHEDRON)

    grid = pv.UnstructuredGrid(np.array(cells), np.array(ctypes), coords)

    # Nodal PEEQ via elemental->nodal average
    avg = dpf.operators.averaging.elemental_to_nodal()
    avg.inputs.field(peeq_field)
    peeq_nodal = avg.outputs.field()

    vals = np.zeros(len(node_ids))
    for i, nid_val in enumerate(peeq_nodal.scoping.ids):
        idx = nid_to_idx.get(nid_val)
        if idx is not None:
            vals[idx] = peeq_nodal.data[i]
    grid.point_data["PEEQ"] = vals
    return grid


grid = build_pv_grid(model, peeq_fc[0], disp_field)

# Static contour plot
print("\n[..] Generating PEEQ contour plot ...")
sargs = dict(title="Equiv. Plastic Strain (PEEQ)", color="black", fmt="%.4f")

pv.OFF_SCREEN = True
pl = pv.Plotter(off_screen=True, window_size=[1024, 768])
pl.set_background("white")
pl.add_mesh(grid, scalars="PEEQ", cmap="plasma", show_edges=True,
            edge_color="black", scalar_bar_args=sargs)
pl.add_text(f"MAT_024 | {total_elems} elements | PEEQ_max={peeq_val:.4f} | VM_max={vm_val:.0f} MPa",
            position="upper_left", font_size=9, color="black")
pl.add_axes(color="black")
pl.camera_position = "iso"
pl.screenshot("block_multi_peeq.png", return_img=False)
pl.close()
print(f"[OK] Contour plot saved: {os.path.abspath('block_multi_peeq.png')}")

# Animated GIF
print("\n[..] Generating PEEQ animation ...")
peeq_all = model.results.plastic_strain_eqv.on_all_time_freqs.eval()
u_all    = model.results.displacement.on_all_time_freqs.eval()

all_peeq_vals = [float(f.data.max()) for f in peeq_all]
peeq_min, peeq_max = 0.0, max(all_peeq_vals)

tmp_dir = pathlib.Path(tempfile.mkdtemp())
frame_paths = []

for idx, (peeq_f, u_f) in enumerate(zip(peeq_all, u_all)):
    g = build_pv_grid(model, peeq_f, u_f)
    fpath = str(tmp_dir / f"frame_{idx:03d}.png")
    pl = pv.Plotter(off_screen=True, window_size=[800, 600])
    pl.set_background("white")
    pl.add_mesh(g, scalars="PEEQ", cmap="plasma", show_edges=True,
                edge_color="black", clim=[peeq_min, max(peeq_max, 1e-8)],
                scalar_bar_args=dict(title="PEEQ", color="black", fmt="%.4f"))
    pl.add_text(f"MAT_024 | PEEQ_max={float(peeq_f.data.max()):.4f}",
                position="upper_left", font_size=10, color="black")
    pl.add_axes(color="black")
    pl.camera_position = "iso"
    pl.screenshot(fpath, return_img=False)
    pl.close()
    frame_paths.append(fpath)

frames = [iio.imread(f) for f in frame_paths]
iio.imwrite("block_multi_animation.gif", frames, duration=150, loop=0)
print(f"[OK] Animation saved: {os.path.abspath('block_multi_animation.gif')}")
