import os
import inspect
import httpx
from bs4 import BeautifulSoup
import markdownify
from mcp.server.fastmcp import FastMCP

# PyAnsys Imports
from ansys.dyna.core import Deck, keywords as kwd
from ansys.dpf import core as dpf
from ansys.dpf import post

# ==========================================
# NETWORK CONFIGURATION (Update These!)
# ==========================================
REMOTE_IP = "192.168.0.37"  # IP of the remote machine with LS-DYNA installed
DYNA_PORT = 5000             # PyDyna Server Port on remote machine
DPF_PORT = 50068            # DPF Server Port on remote machine

# Initialize the FastMCP server
mcp = FastMCP("PyAnsys-Comprehensive-LAN-Assistant")

# ==========================================
# 1. PYDYNA TOOLS (Local Gen -> Remote Solve)
# ==========================================

@mcp.tool()
def generate_material_deck(
    filename: str, 
    material_id: int, 
    density: float, 
    youngs_modulus: float, 
    poissons_ratio: float, 
    yield_stress: float
) -> str:
    """
    Creates an LS-DYNA keyword file containing a MAT_003 definition locally on the laptop.
    """
    try:
        deck = Deck()
        mat = kwd.Mat003(mid=material_id)
        mat.ro = density
        mat.e = youngs_modulus
        mat.pr = poissons_ratio
        mat.sigy = yield_stress
        
        with open(filename, "w") as f:
            f.write(deck.write())
            
        return f"Success: Material deck {filename} written locally on laptop."
    except Exception as e:
        return f"Error generating deck: {str(e)}"

@mcp.tool()
def run_lsdyna_simulation(keyword_file: str) -> str:
    """
    Uploads the local keyword file to the remote server via HTTP and triggers the LS-DYNA solve.
    """
    if not os.path.isfile(keyword_file):
        return f"Error: Local file '{keyword_file}' not found."
    
    try:
        url = f"http://{REMOTE_IP}:{DYNA_PORT}/solve"
        
        # Open the file and send it as a multipart form upload
        with open(keyword_file, "rb") as f:
            files = {"file": (os.path.basename(keyword_file), f, "application/octet-stream")}
            
            # Note: timeout is set to 600 seconds (10 mins) to give the solver time to finish
            response = httpx.post(url, files=files, timeout=600.0) 
            
        result = response.json()
        
        if result.get("status") == "success":
            return f"Simulation complete on remote server {REMOTE_IP}. Output 'd3plot' is ready for DPF processing."
        else:
            return f"Remote solver failed to generate d3plot. Logs:\n{result.get('output')}"
            
    except httpx.ReadTimeout:
        return "Error: The solver took longer than 10 minutes and timed out the connection."
    except Exception as e:
         return f"Failed to connect to the remote solver API at {REMOTE_IP}: {str(e)}"


# ==========================================
# 2. DPF-POST TOOLS (Remote Data Extraction)
# ==========================================

@mcp.tool()
def extract_d3plot_summary(result_file: str = "d3plot") -> str:
    """
    Connects to the remote DPF server to summarize the simulation results without downloading the d3plot file.
    """
    try:
        # Connect to remote DPF Server
        remote_server = dpf.connect_to_server(ip=REMOTE_IP, port=DPF_PORT)
        
        # Load simulation directly from the remote server's hard drive
        simulation = post.load_simulation(result_file, server=remote_server)
        
        mesh_info = str(simulation.mesh)
        time_freq_support = str(simulation.time_freq_support)
        result_names = ", ".join(simulation.result_names)
        
        return (
            f"--- DPF Summary (Processed on {REMOTE_IP}) ---\n\n"
            f"**Mesh Info:**\n{mesh_info}\n\n"
            f"**Steps:**\n{time_freq_support}\n\n"
            f"**Available Results:**\n{result_names}\n"
        )
    except Exception as e:
        return f"Failed to connect or read results via remote DPF: {str(e)}"

@mcp.tool()
def extract_maximum_result_value(result_file: str, result_name: str) -> str:
    """
    Asks the remote DPF server to calculate the maximum result and send only the scalar answer back.
    """
    try:
        remote_server = dpf.connect_to_server(ip=REMOTE_IP, port=DPF_PORT)
        simulation = post.load_simulation(result_file, server=remote_server)
        
        if not hasattr(simulation, result_name):
            return f"Error: Result '{result_name}' is not supported."
            
        result_operator = getattr(simulation, result_name)()
        max_value = result_operator.max()
        
        return f"The maximum {result_name} on the remote server is:\n{max_value}"
    except Exception as e:
        return f"Failed to extract {result_name} remotely: {str(e)}"


# ==========================================
# 3. INTROSPECTION & DOC SCRAPING TOOLS
# ==========================================

@mcp.tool()
def search_pydyna_keywords(query: str) -> str:
    """
    Searches the installed ansys.dyna.core.keywords library for LS-DYNA keywords.
    """
    from ansys.dyna.core import keywords
    results = []
    
    for name, obj in inspect.getmembers(keywords, inspect.isclass):
        doc = obj.__doc__ or ""
        if query.lower() in name.lower() or query.lower() in doc.lower():
            summary = doc.strip().split('\n')[0] if doc else 'No docstring available'
            results.append(f"- Class: `{name}` | Summary: {summary}")
            
    if not results:
         return f"No classes found matching '{query}'"
    return "Found the following matching classes:\n" + "\n".join(results[:20])

@mcp.tool()
def get_pydyna_class_docs(class_name: str) -> str:
    """
    Retrieves the full Python docstring, arguments, and properties for a specific pyDyna class.
    """
    from ansys.dyna.core import keywords
    try:
        obj = getattr(keywords, class_name)
        docstring = inspect.getdoc(obj) or "No docstring available."
        sig = inspect.signature(obj.__init__)
        return f"Class: {class_name}\nSignature: {class_name}{sig}\n\nDocstring:\n{docstring}"
    except AttributeError:
        return f"Error: Class '{class_name}' not found."
    except ValueError:
        return f"Error: Could not retrieve signature for {class_name}. Docstring:\n{docstring}"

@mcp.tool()
def read_pydyna_web_docs(subpage: str = "api/ansys/dyna/core/index.html") -> str:
    """
    Fetches documentation directly from the pyDyna website (e.g., 'api/ansys/dyna/core/index.html').
    """
    url = "https://dyna.docs.pyansys.com/version/stable/" + subpage.lstrip('/')
    try:
        response = httpx.get(url, timeout=10.0, follow_redirects=True)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        main_content = soup.find('main') or soup.find('article') or soup.find('div', role='main') or soup.body
        markdown_text = markdownify.markdownify(str(main_content), heading_style="ATX")
        return f"--- Content from {url} ---\n\n" + markdown_text[:12000]
    except Exception as e:
        return f"Failed to fetch {url}: {str(e)}"

@mcp.tool()
def read_pydpf_web_docs(subpage: str = "api/index.html") -> str:
    """
    Fetches documentation directly from the PyDPF-Post website (e.g., 'api/index.html').
    """
    url = "https://post.docs.pyansys.com/version/stable/" + subpage.lstrip('/')
    try:
        response = httpx.get(url, timeout=10.0, follow_redirects=True)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        main_content = soup.find('main') or soup.find('article') or soup.body
        markdown_text = markdownify.markdownify(str(main_content), heading_style="ATX")
        return f"--- Content from {url} ---\n\n" + markdown_text[:12000]
    except Exception as e:
        return f"Failed to fetch {url}: {str(e)}"

if __name__ == "__main__":
    # Start the server via stdio for MCP clients
    mcp.run()