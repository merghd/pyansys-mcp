"""
solve_block.py
--------------
Builds a single-element (hex8) unit-cube mesh using pyDyna, writes a complete
LS-DYNA keyword file, then submits it to the remote solver via the same logic
as the `run_lsdyna_simulation` MCP tool defined in server.py.

Simulation: uniaxial compression of a 1 mm × 1 mm × 1 mm steel cube.
  - Bottom face (z = 0) fully constrained.
  - Top face (z = 1) prescribed downward displacement of -0.1 mm over 1 ms.
  - Steel: E = 200 GPa, ν = 0.3, ρ = 7.85e-9 t/mm³.
"""

import os
import httpx
import numpy as np
import pandas as pd
from ansys.dyna.core import Deck, keywords as kwd

# ---------------------------------------------------------------------------
# Configuration – must match server.py
# ---------------------------------------------------------------------------
REMOTE_IP   = "192.168.0.37"
DYNA_PORT   = 5000
OUTPUT_FILE = "block_compression.k"

# ---------------------------------------------------------------------------
# 1.  Build the mesh
# ---------------------------------------------------------------------------

deck = Deck()

# --- Nodes (unit cube, mm) --------------------------------------------------
#   Bottom face (z=0): nid 1-4   Top face (z=1): nid 5-8
#
#        8 ---- 7          z
#       /|     /|          |
#      5 ---- 6 |          +-- x
#      | 4 ---|-3         /
#      |/     |/         y
#      1 ---- 2
#
node_kw = kwd.Node()
node_kw.nodes = pd.DataFrame({
    "nid": [1, 2, 3, 4, 5, 6, 7, 8],
    "x":   [0, 1, 1, 0, 0, 1, 1, 0],
    "y":   [0, 0, 1, 1, 0, 0, 1, 1],
    "z":   [0, 0, 0, 0, 1, 1, 1, 1],
})
deck.append(node_kw)

# --- Single HEXA8 solid element --------------------------------------------
elem_kw = kwd.ElementSolid()
elem_kw.elements = pd.DataFrame({
    "eid":  [1],
    "pid":  [1],
    "n1":   [1],
    "n2":   [2],
    "n3":   [3],
    "n4":   [4],
    "n5":   [5],
    "n6":   [6],
    "n7":   [7],
    "n8":   [8],
})
deck.append(elem_kw)

# --- Material: MAT_024 Piecewise Linear Plasticity (steel, t-mm-s) ---------
# ρ = 7.85e-9 t/mm³ | E = 200,000 MPa | ν = 0.3
# Yield = 250 MPa, bilinear hardening with Et = 2,000 MPa
mat = kwd.Mat024(mid=1)
mat.ro   = 7.85e-9   # density      [t/mm³]
mat.e    = 200000.0  # Young's mod  [MPa]
mat.pr   = 0.3       # Poisson
mat.sigy = 250.0     # Yield stress [MPa]
mat.etan = 2000.0    # Tangent mod  [MPa] (post-yield slope)
mat.fail = 1e21      # No failure
deck.append(mat)

# --- Section: SECTION_SOLID (constant-stress solid, ELFORM=1) --------------
sec = kwd.SectionSolid(secid=1)
sec.elform = 1
deck.append(sec)

# --- Part ------------------------------------------------------------------
part = kwd.Part()
part.parts = pd.DataFrame({
    "heading": ["steel_block"],
    "pid":     [1],
    "secid":   [1],
    "mid":     [1],
})
deck.append(part)

# --- Boundary conditions ---------------------------------------------------
# Fix all DOF on bottom face nodes (1-4) using BOUNDARY_SPC_NODE
for nid in [1, 2, 3, 4]:
    bc = kwd.BoundarySpcNode()
    bc.nodes = pd.DataFrame({
        "nid":   [nid],
        "cid":   [0],
        "dofx":  [1],
        "dofy":  [1],
        "dofz":  [1],
        "dofrx": [1],
        "dofry": [1],
        "dofrz": [1],
    })
    deck.append(bc)

# Constrain x/y on top nodes (5-8) to enforce uniaxial compression
for nid in [5, 6, 7, 8]:
    bc = kwd.BoundarySpcNode()
    bc.nodes = pd.DataFrame({
        "nid":   [nid],
        "cid":   [0],
        "dofx":  [1],
        "dofy":  [1],
        "dofz":  [0],
        "dofrx": [0],
        "dofry": [0],
        "dofrz": [0],
    })
    deck.append(bc)

# --- Prescribed displacement on top face (load curve 1) -------------------
# Curve: linear ramp from 0 to -0.1 mm over 1 ms
lc = kwd.DefineCurve(lcid=1)
lc.curves = pd.DataFrame({
    "a1": [0.0, 1.0e-3],   # time [s]
    "o1": [0.0, -0.1],     # displacement [mm]
})
deck.append(lc)

# Apply as prescribed z-displacement on top nodes (DOF = 3)
for nid in [5, 6, 7, 8]:
    spcd = kwd.BoundaryPrescribedMotionNode()
    spcd.nid  = nid
    spcd.dof  = 3       # z-direction
    spcd.vad  = 2       # displacement
    spcd.lcid = 1
    spcd.sf   = 1.0
    deck.append(spcd)

# --- Control cards ---------------------------------------------------------
ctrl_term = kwd.ControlTermination()
ctrl_term.endtim = 1.0e-3   # 1 ms
ctrl_term.endcyc = 0
deck.append(ctrl_term)

ctrl_time = kwd.ControlTimestep()
ctrl_time.dtinit = 0.0      # auto
ctrl_time.tssfac = 0.9
deck.append(ctrl_time)

ctrl_energy = kwd.ControlEnergy()
ctrl_energy.hgen  = 2
ctrl_energy.rwen  = 2
ctrl_energy.slnten= 2
ctrl_energy.rylen = 2
deck.append(ctrl_energy)

# --- Database output -------------------------------------------------------
db_d3plot = kwd.DatabaseBinaryD3Plot()
db_d3plot.dt = 1.0e-4   # write every 0.1 ms
deck.append(db_d3plot)

# Request plastic strain output in d3plot (strflg=1)
db_extent = kwd.DatabaseExtentBinary()
db_extent.strflg = 1   # include strain tensors (elastic + plastic)
deck.append(db_extent)

db_glstat = kwd.DatabaseGlstat()
db_glstat.dt = 1.0e-5
deck.append(db_glstat)

db_nodout = kwd.DatabaseNodout()
db_nodout.dt = 1.0e-5
deck.append(db_nodout)

# --- Write keyword file ----------------------------------------------------
kw_text = deck.write()
with open(OUTPUT_FILE, "w") as f:
    f.write(kw_text)

print(f"[OK] Keyword file written: {os.path.abspath(OUTPUT_FILE)}")
print(f"     Nodes: 8 | Elements: 1 (HEXA8) | Material: MAT_001 Elastic")

# ---------------------------------------------------------------------------
# 2.  Submit to remote LS-DYNA solver via HTTP (mirrors server.py)
# ---------------------------------------------------------------------------

def run_lsdyna_simulation(keyword_file: str) -> str:
    """
    Upload keyword file to the remote HTTP solver API and trigger the solve.
    Mirrors the run_lsdyna_simulation MCP tool in server.py.
    """
    if not os.path.isfile(keyword_file):
        return f"Error: Local file '{keyword_file}' not found."

    try:
        url = f"http://{REMOTE_IP}:{DYNA_PORT}/solve"

        print(f"[..] POSTing '{keyword_file}' to {url} ...")
        with open(keyword_file, "rb") as f:
            files = {"file": (os.path.basename(keyword_file), f, "application/octet-stream")}
            response = httpx.post(url, files=files, timeout=600.0)

        result = response.json()

        if result.get("status") == "success":
            return f"Simulation complete on {REMOTE_IP}. d3plot is ready for DPF processing."
        else:
            return f"Remote solver failed. Logs:\n{result.get('output')}"

    except httpx.ReadTimeout:
        return "Error: Solver took longer than 10 minutes and timed out."
    except Exception as e:
        return f"Failed to connect to remote solver at {REMOTE_IP}: {e}"


result = run_lsdyna_simulation(OUTPUT_FILE)
print(f"\n[SOLVER RESULT]\n{result}")

if "complete" not in result:
    raise SystemExit("Solver failed — skipping post-processing.")

# ---------------------------------------------------------------------------
# 3.  Post-processing via remote DPF
# ---------------------------------------------------------------------------
from ansys.dpf import core as dpf
from ansys.dpf.core.server_factory import ServerConfig, CommunicationProtocols, GrpcMode
import pyvista as pv

DPF_PORT = 50068

config = ServerConfig(protocol=CommunicationProtocols.gRPC, grpc_mode=GrpcMode.Insecure)
print(f"\n[..] Connecting to DPF at {REMOTE_IP}:{DPF_PORT} ...")
dpf_server = dpf.connect_to_server(ip=REMOTE_IP, port=DPF_PORT, config=config)
print(f"[OK] DPF server version: {dpf_server.version}")

# Single model via DataSources — one connection for all results
ds = dpf.DataSources(server=dpf_server)
ds.set_result_file_path("d3plot", "d3plot")
model     = dpf.Model(ds, server=dpf_server)
final_set = model.metadata.time_freq_support.n_sets - 1  # last proper step

print(f"\n--- Results at t=1ms (set_id={final_set}) ---")

# Displacement
u_fc       = model.results.displacement(time_scoping=[final_set]).eval()
disp_field = u_fc[0]
top_nodes  = [5, 6, 7, 8]
top_idx    = [list(disp_field.scoping.ids).index(n) for n in top_nodes]
print("\nDisplacement top nodes (mm):")
for n, i in zip(top_nodes, top_idx):
    print(f"  Node {n}: UX={disp_field.data[i][0]:.4f}  UY={disp_field.data[i][1]:.4f}  UZ={disp_field.data[i][2]:.4f}")

# Stress
stress_fc = model.results.stress(time_scoping=[final_set]).eval()
s = stress_fc[0].data[0]  # element 1, [XX,YY,ZZ,XY,YZ,XZ]
print(f"\nStress tensor element 1 (MPa):")
print(f"  XX={s[0]:.2f}  YY={s[1]:.2f}  ZZ={s[2]:.2f}  XY={s[3]:.2f}  YZ={s[4]:.2f}  XZ={s[5]:.2f}")

# Von Mises
vm_fc  = model.results.stress_von_mises(time_scoping=[final_set]).eval()
vm_val = float(vm_fc[0].data.max())
print(f"\nVon Mises Stress: {vm_val:.2f} MPa")

# PEEQ
peeq_fc  = model.results.plastic_strain_eqv(time_scoping=[final_set]).eval()
peeq_val = float(peeq_fc[0].data.max())
print(f"\nEquiv. Plastic Strain (PEEQ): {peeq_val:.6f}")

# ---------------------------------------------------------------------------
# 4.  Static contour plot via PyVista
#     field.plot() doesn't expand elemental->nodal over a remote connection,
#     so we average manually and build the PyVista mesh directly.
# ---------------------------------------------------------------------------
print("\n[..] Generating plastic strain contour plot (PyVista) ...")

# Average PEEQ elemental -> nodal
avg_op     = dpf.operators.averaging.elemental_to_nodal()
avg_op.inputs.field(peeq_fc[0])
peeq_nodal = avg_op.outputs.field()

# Build deformed node coords from DPF displacement data
coords = np.array([
    [0,0,0],[1,0,0],[1,1,0],[0,1,0],
    [0,0,1],[1,0,1],[1,1,1],[0,1,1],
], dtype=float)
for i, nid in enumerate(u_fc[0].scoping.ids):
    coords[nid - 1] += u_fc[0].data[i]

cells  = np.array([8, 0,1,2,3,4,5,6,7])
ctypes = np.array([pv.CellType.HEXAHEDRON])
grid   = pv.UnstructuredGrid(cells, ctypes, coords)
peeq_values = np.zeros(8)
for i, nid in enumerate(peeq_nodal.scoping.ids):
    peeq_values[nid - 1] = peeq_nodal.data[i]
grid.point_data["PEEQ"] = peeq_values

sargs = dict(title="Equiv. Plastic Strain (PEEQ)", color="black", fmt="%.4f")

pv.OFF_SCREEN = True
pl = pv.Plotter(off_screen=True, window_size=[1024, 768])
pl.set_background("white")
pl.add_mesh(grid, scalars="PEEQ", cmap="plasma", show_edges=True,
            edge_color="black", scalar_bar_args=sargs)
pl.add_text(f"MAT_024 Steel | PEEQ={peeq_val:.4f} | VM={vm_val:.0f} MPa | UZ=-0.100 mm",
            position="upper_left", font_size=10, color="black")
pl.add_axes(color="black")
pl.camera_position = "iso"
pl.screenshot("plastic_strain_contour.png", return_img=False)
pl.close()
print(f"[OK] Contour plot saved: {os.path.abspath('plastic_strain_contour.png')}")

# ---------------------------------------------------------------------------
# 5.  Animated GIF — PEEQ evolving over all time steps (PyVista frame-by-frame)
#     FieldsContainer.animate() loses elemental->nodal mapping over a remote
#     connection, so we build each frame manually and write with imageio.
# ---------------------------------------------------------------------------
print("\n[..] Generating PEEQ animation ...")

import imageio.v3 as iio
import tempfile, pathlib

peeq_all = model.results.plastic_strain_eqv.on_all_time_freqs.eval()
u_all    = model.results.displacement.on_all_time_freqs.eval()

# Determine global colour range across all timesteps
all_peeq_vals = [float(f.data.max()) for f in peeq_all]
peeq_min, peeq_max = min(all_peeq_vals), max(all_peeq_vals)

ref_coords = np.array([
    [0,0,0],[1,0,0],[1,1,0],[0,1,0],
    [0,0,1],[1,0,1],[1,1,1],[0,1,1],
], dtype=float)

tmp_dir = pathlib.Path(tempfile.mkdtemp())
frame_paths = []

for idx, (peeq_f, u_f) in enumerate(zip(peeq_all, u_all)):
    avg = dpf.operators.averaging.elemental_to_nodal()
    avg.inputs.field(peeq_f)
    peeq_n = avg.outputs.field()

    coords = ref_coords.copy()
    for i, nid in enumerate(u_f.scoping.ids):
        coords[nid - 1] += u_f.data[i]

    cells  = np.array([8, 0,1,2,3,4,5,6,7])
    ctypes = np.array([pv.CellType.HEXAHEDRON])
    grid   = pv.UnstructuredGrid(cells, ctypes, coords)
    vals   = np.zeros(8)
    for i, nid in enumerate(peeq_n.scoping.ids):
        vals[nid - 1] = peeq_n.data[i]
    grid.point_data["PEEQ"] = vals

    fpath = str(tmp_dir / f"frame_{idx:03d}.png")
    pl = pv.Plotter(off_screen=True, window_size=[800, 600])
    pl.set_background("white")
    pl.add_mesh(grid, scalars="PEEQ", cmap="plasma", show_edges=True,
                edge_color="black", clim=[peeq_min, max(peeq_max, 1e-8)],
                scalar_bar_args=dict(title="PEEQ", color="black", fmt="%.4f"))
    pl.add_text(f"MAT_024 Steel | PEEQ={float(peeq_f.data.max()):.4f}",
                position="upper_left", font_size=10, color="black")
    pl.add_axes(color="black")
    pl.camera_position = "iso"
    pl.screenshot(fpath, return_img=False)
    pl.close()
    frame_paths.append(fpath)

frames = [iio.imread(f) for f in frame_paths]
iio.imwrite("plastic_strain_animation.gif", frames, duration=150, loop=0)
print(f"[OK] Animation saved: {os.path.abspath('plastic_strain_animation.gif')}")
